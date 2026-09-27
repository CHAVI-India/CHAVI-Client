"""Query/Retrieve SCU — pull studies from configured remote DICOM nodes.

All functions take a RemoteDICOMNode and use our configured AE title as the
calling AET. Retrieval is pull-only: C-MOVE delivers to our own SCP's AE title,
C-GET receives sub-ops on the same association (handled by the same ingest path
as the SCP's C-STORE handler).
"""
import logging
import socket

from pydicom.dataset import Dataset
from pynetdicom import AE, evt, build_role, StoragePresentationContexts
from pynetdicom.sop_class import (
    Verification,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelGet,
)

from dicom_server.models import DICOMServerConfiguration, RemoteDICOMNode
from dicom_server.scp.handlers import handle_store

logger = logging.getLogger(__name__)


def _scu_ae() -> AE:
    config = DICOMServerConfiguration.load()
    ae = AE(ae_title=config.ae_title)
    ae.connection_timeout = config.qr_timeout
    ae.network_timeout = config.qr_timeout
    ae.acse_timeout = config.qr_timeout
    ae.dimse_timeout = config.qr_timeout
    return ae


def echo(node: RemoteDICOMNode) -> tuple[bool, str]:
    """C-ECHO against a remote node.

    Returns (ok, reason): reason is '' on success, otherwise a short
    description of the failing stage (DNS, TCP connect, association
    reject/abort, or non-zero echo status).
    """
    ae = _scu_ae()
    ae.add_requested_context(Verification)
    try:
        assoc = _connect(ae, node)
    except ConnectionError as e:
        logger.warning('C-ECHO association to %s failed: %s', node, e)
        return False, str(e)
    try:
        status = assoc.send_c_echo()
        if status and status.Status == 0x0000:
            logger.info('C-ECHO %s: success', node)
            return True, ''
        reason = (
            f'C-ECHO returned status 0x{status.Status:04X}'
            if status is not None else 'C-ECHO timed out'
        )
        logger.info('C-ECHO %s: failed (%s)', node, reason)
        return False, reason
    finally:
        assoc.release()


def _connect(ae: AE, node: RemoteDICOMNode, **assoc_kwargs):
    """Open an association or raise ConnectionError with the actual cause.

    A bare TCP pre-flight runs first so DNS, refused and timeout failures are
    distinguished from DICOM-layer rejections (pynetdicom reports them all as
    'aborted'). assoc_kwargs are forwarded to AE.associate (e.g. ext_neg,
    evt_handlers for C-GET).
    """
    try:
        sock = socket.create_connection(
            (node.host, node.port), timeout=ae.connection_timeout or 30,
        )
    except socket.gaierror as e:
        raise ConnectionError(
            f'{node}: cannot resolve hostname {node.host!r} ({e})'
        ) from e
    except OSError as e:
        raise ConnectionError(
            f'{node}: TCP connect to {node.host}:{node.port} '
            f'refused or timed out ({e})'
        ) from e
    else:
        sock.close()

    assoc = ae.associate(
        node.host, node.port, ae_title=node.ae_title, **assoc_kwargs,
    )
    if assoc.is_established:
        return assoc
    if assoc.is_rejected:
        detail = 'rejected by peer (check AE titles)'
    elif assoc.is_aborted:
        detail = 'aborted (connection failed or dropped)'
    elif getattr(assoc.acceptor, 'primitive', None) is not None:
        detail = 'no accepted presentation contexts (peer does not support this SOP class)'
    else:
        detail = 'rejected or timed out'
    raise ConnectionError(f'Association to {node} {detail}')


def find_studies(node: RemoteDICOMNode, patient_id: str) -> list[dict]:
    """Study Root C-FIND at STUDY level for a PatientID.

    Returns a list of dicts: study_instance_uid, study_date, study_description,
    modalities, instances.
    """
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    assoc = _connect(ae, node)
    try:
        q = Dataset()
        q.QueryRetrieveLevel = 'STUDY'
        q.PatientID = patient_id
        q.StudyInstanceUID = ''
        q.StudyDate = ''
        q.StudyDescription = ''
        q.ModalitiesInStudy = ''
        q.NumberOfStudyRelatedInstances = ''

        results = []
        for status, identifier in assoc.send_c_find(
            q, StudyRootQueryRetrieveInformationModelFind
        ):
            if status is None:
                raise ConnectionError(f'C-FIND on {node} timed out or aborted')
            if status.Status in (0xFF00, 0xFF01) and identifier:
                results.append({
                    'study_instance_uid': str(getattr(identifier, 'StudyInstanceUID', '') or ''),
                    'study_date': str(getattr(identifier, 'StudyDate', '') or ''),
                    'study_description': str(getattr(identifier, 'StudyDescription', '') or ''),
                    'modalities': str(getattr(identifier, 'ModalitiesInStudy', '') or ''),
                    'instances': getattr(identifier, 'NumberOfStudyRelatedInstances', None),
                })
            elif status.Status not in (0xFF00, 0xFF01, 0x0000):
                logger.warning('C-FIND on %s returned status 0x%04X', node, status.Status)
        logger.info('C-FIND %s patient %s: %d studies', node, patient_id, len(results))
        return results
    finally:
        assoc.release()


def find_studies_for_patient(node: RemoteDICOMNode, patient, aliases=None) -> list[dict]:
    """Union C-FIND results for the canonical patient ID plus any node aliases.

    Duplicates are removed by StudyInstanceUID. Raises ConnectionError if every
    patient ID tried failed (e.g. the node is unreachable) — callers must not
    treat that as "no studies".
    """
    patient_ids = [patient.patient_id]
    if aliases:
        patient_ids.extend(aliases)
    patient_ids = list(dict.fromkeys(patient_ids))

    seen = set()
    results = []
    errors = []
    for pid in patient_ids:
        try:
            for study in find_studies(node, pid):
                uid = study.get('study_instance_uid')
                if uid and uid not in seen:
                    seen.add(uid)
                    results.append(study)
        except Exception as e:
            logger.exception('C-FIND failed for patient ID %r on %s', pid, node)
            errors.append(f'{pid}: {e}')
    if errors and len(errors) == len(patient_ids):
        raise ConnectionError(
            f'C-FIND on {node} failed for every patient ID tried: '
            + '; '.join(errors)
        )
    return results


def _subop_stats(status) -> dict:
    """Extract C-MOVE/C-GET sub-operation counters from the final status."""
    if status is None:
        return {'status': None, 'remaining': 0, 'completed': 0, 'failed': 0, 'warning': 0}
    remaining = int(getattr(status, 'NumberOfRemainingSuboperations', 0) or 0)
    return {
        'status': getattr(status, 'Status', None),
        'remaining': remaining,
        'completed': int(getattr(status, 'NumberOfCompletedSuboperations', 0) or 0),
        # instances still pending when the operation ended never arrived
        'failed': int(getattr(status, 'NumberOfFailedSuboperations', 0) or 0) + remaining,
        'warning': int(getattr(status, 'NumberOfWarningSuboperations', 0) or 0),
    }


def _collect_subop_stats(responses, operation: str) -> dict:
    """Consume a send_c_move/send_c_get response iterator into sub-op stats.

    On DIMSE timeout pynetdicom aborts and yields a status dataset with no
    Status attribute — fall back to the last valid response for the counters
    and flag the error instead of crashing.
    """
    final = last_valid = None
    for status, _ in responses:
        if status is None:
            raise ConnectionError(f'{operation} timed out or aborted')
        final = status
        if getattr(status, 'Status', None) is not None:
            last_valid = status
    stats = _subop_stats(last_valid or final)
    if final is not None and getattr(final, 'Status', None) is None:
        stats['error'] = f'{operation} timed out before final response'
    return stats


def _study_identifier(study_instance_uid: str, patient_id: str | None) -> Dataset:
    q = Dataset()
    q.QueryRetrieveLevel = 'STUDY'
    if patient_id:
        q.PatientID = patient_id
    q.StudyInstanceUID = study_instance_uid
    return q


def move_study(node: RemoteDICOMNode, study_instance_uid: str,
               patient_id: str | None = None, destination: str | None = None) -> dict:
    """C-MOVE a study to our own Storage SCP (destination = our AE title).

    The remote must be able to resolve our AE title to host:port (PACS config).
    Returns sub-op stats: status/completed/failed/warning.
    """
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
    assoc = _connect(ae, node)
    try:
        destination = destination or DICOMServerConfiguration.load().ae_title
        q = _study_identifier(study_instance_uid, patient_id)
        stats = _collect_subop_stats(
            assoc.send_c_move(q, destination, StudyRootQueryRetrieveInformationModelMove),
            f'C-MOVE on {node}',
        )
        logger.info('C-MOVE %s study %s -> %s: %s', node, study_instance_uid, destination, stats)
        return stats
    finally:
        assoc.release()


# Extra storage SOP classes offered on C-GET beyond the curated common set.
# An association negotiates at most 128 presentation contexts and the Q/R-GET
# model takes one slot, leaving room for 127 — the curated 120 plus 7 extras,
# spent on the second-generation RT objects an oncology PACS serves.
_EXTRA_STORAGE_UIDS = (
    '1.2.840.10008.5.1.4.1.1.481.10',  # RT Physician Intent
    '1.2.840.10008.5.1.4.1.1.481.11',  # RT Segment Annotation
    '1.2.840.10008.5.1.4.1.1.481.12',  # RT Radiation Set
    '1.2.840.10008.5.1.4.1.1.481.16',  # RT Radiation Record Set
    '1.2.840.10008.5.1.4.1.1.481.22',  # RT Treatment Preparation
    '1.2.840.10008.5.1.4.1.1.481.23',  # Enhanced RT Image
    '1.2.840.10008.5.1.4.1.1.481.24',  # Enhanced Continuous RT Image
)


def _get_storage_uids() -> list:
    """Storage SOP classes to request on a C-GET association (SCP role is
    negotiated per-class via role selection)."""
    return [cx.abstract_syntax for cx in StoragePresentationContexts] \
        + list(_EXTRA_STORAGE_UIDS)


def get_study(node: RemoteDICOMNode, study_instance_uid: str,
              patient_id: str | None = None) -> dict:
    """C-GET a study — instances arrive as C-STORE sub-ops on the same
    association and go through the normal ingest path (patient gating applies).

    Works when the remote cannot open a connection back to us (e.g. NAT).
    Returns sub-op stats: status/completed/failed/warning.
    """
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
    storage_uids = _get_storage_uids()
    for uid in storage_uids:
        ae.add_requested_context(uid)
    roles = [build_role(uid, scp_role=True) for uid in storage_uids]
    assoc = _connect(
        ae, node, ext_neg=roles,
        evt_handlers=[(evt.EVT_C_STORE, handle_store)],
    )
    try:
        q = _study_identifier(study_instance_uid, patient_id)
        stats = _collect_subop_stats(
            assoc.send_c_get(q, StudyRootQueryRetrieveInformationModelGet),
            f'C-GET on {node}',
        )
        logger.info('C-GET %s study %s: %s', node, study_instance_uid, stats)
        return stats
    finally:
        assoc.release()

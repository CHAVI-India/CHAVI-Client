"""Query/Retrieve SCU — pull studies from configured remote DICOM nodes.

All functions take a RemoteDICOMNode and use our configured AE title as the
calling AET. Retrieval is pull-only: C-MOVE delivers to our own SCP's AE title,
C-GET receives sub-ops on the same association (handled by the same ingest path
as the SCP's C-STORE handler).
"""
import logging

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
    ae.network_timeout = config.qr_timeout
    ae.acse_timeout = config.qr_timeout
    ae.dimse_timeout = config.qr_timeout
    return ae


def echo(node: RemoteDICOMNode) -> bool:
    """C-ECHO against a remote node. Returns True on success."""
    ae = _scu_ae()
    ae.add_requested_context(Verification)
    try:
        assoc = ae.associate(node.host, node.port, ae_title=node.ae_title)
    except Exception as e:
        logger.warning("C-ECHO association to %s failed: %s", node, e)
        return False
    if not assoc.is_established:
        reason = (
            'rejected by peer (check AE titles)' if assoc.is_rejected
            else 'aborted' if assoc.is_aborted
            else 'not established'
        )
        logger.warning("C-ECHO association to %s %s", node, reason)
        return False
    try:
        status = assoc.send_c_echo()
        ok = bool(status and status.Status == 0x0000)
        logger.info("C-ECHO %s: %s", node, 'success' if ok else 'failed')
        return ok
    finally:
        assoc.release()


def _connect(ae: AE, node: RemoteDICOMNode):
    """Open an association or raise ConnectionError with the actual cause."""
    assoc = ae.associate(node.host, node.port, ae_title=node.ae_title)
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

    Duplicates are removed by StudyInstanceUID.
    """
    patient_ids = [patient.patient_id]
    if aliases:
        patient_ids.extend(aliases)
    patient_ids = list(dict.fromkeys(patient_ids))

    seen = set()
    results = []
    for pid in patient_ids:
        try:
            for study in find_studies(node, pid):
                uid = study.get('study_instance_uid')
                if uid and uid not in seen:
                    seen.add(uid)
                    results.append(study)
        except Exception:
            logger.exception('C-FIND failed for patient ID %r on %s', pid, node)
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
    assoc = ae.associate(node.host, node.port, ae_title=node.ae_title)
    if not assoc.is_established:
        raise ConnectionError(f'Association to {node} rejected or timed out')
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


def get_study(node: RemoteDICOMNode, study_instance_uid: str,
              patient_id: str | None = None) -> dict:
    """C-GET a study — instances arrive as C-STORE sub-ops on the same
    association and go through the normal ingest path (patient gating applies).

    Works when the remote cannot open a connection back to us (e.g. NAT).
    Returns sub-op stats: status/completed/failed/warning.
    """
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
    for cx in StoragePresentationContexts:
        ae.add_requested_context(cx.abstract_syntax)
    roles = [
        build_role(cx.abstract_syntax, scp_role=True)
        for cx in StoragePresentationContexts
    ]
    assoc = ae.associate(
        node.host, node.port, ae_title=node.ae_title,
        ext_neg=roles,
        evt_handlers=[(evt.EVT_C_STORE, handle_store)],
    )
    if not assoc.is_established:
        raise ConnectionError(f'Association to {node} rejected or timed out')
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

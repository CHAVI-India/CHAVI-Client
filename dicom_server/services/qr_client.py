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
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    PatientRootQueryRetrieveInformationModelGet,
)

from dicom_server.models import DICOMServerConfiguration, RemoteDICOMNode
from dicom_server.scp.handlers import handle_store

logger = logging.getLogger(__name__)


class QRModelNotAcceptedError(ConnectionError):
    """The peer accepted the association but rejected the Q/R presentation
    contexts needed for the requested DIMSE operation."""


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
        code = getattr(status, 'Status', None)
        if code == 0x0000:
            logger.info('C-ECHO %s: success', node)
            return True, ''
        reason = (
            f'C-ECHO returned status 0x{code:04X}'
            if code is not None else 'C-ECHO timed out or aborted'
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

    # The peer accepted the association but rejected every requested
    # presentation context — pynetdicom then aborts the association itself, so
    # this check must run before the is_aborted branch. The per-context
    # reasons (e.g. "Abstract Syntax Not Supported") say what the remote
    # doesn't support.
    if assoc.rejected_contexts and not assoc.accepted_contexts:
        reasons = ', '.join(
            f'{cx.abstract_syntax.name}: {cx.status}'
            for cx in assoc.rejected_contexts
        )
        detail = (
            f'peer rejected all presentation contexts ({reasons}) — check the '
            "node's AE title matches its DICOM AET and that it supports "
            'Query/Retrieve for our calling AE title'
        )
    elif assoc.is_rejected:
        primitive = getattr(assoc.acceptor, 'primitive', None)
        if primitive is not None:
            detail = (
                f'rejected by peer: {primitive.result_str}, '
                f'{primitive.source_str}, {primitive.reason_str}'
            )
        else:
            detail = 'rejected by peer (check AE titles)'
    elif assoc.is_aborted:
        detail = 'aborted (connection failed or dropped)'
    else:
        detail = 'rejected or timed out'
    raise ConnectionError(f'Association to {node} {detail}')


def _negotiated_qr_model(assoc, study_root_uid, patient_root_uid,
                       operation: str, node: RemoteDICOMNode):
    """Return the Q/R model the peer accepted, preferring Study Root.

    Both models are proposed on the association so patient-root-only remotes
    still work. Raises QRModelNotAcceptedError — with the rejection reasons
    and a remediation hint — if neither was accepted.
    """
    accepted = {cx.abstract_syntax for cx in assoc.accepted_contexts}
    for uid in (study_root_uid, patient_root_uid):
        if uid in accepted:
            return uid

    rejected = {cx.abstract_syntax: cx.status for cx in assoc.rejected_contexts}
    reasons = ', '.join(
        f'{uid.name}: {rejected[uid]}'
        for uid in (study_root_uid, patient_root_uid)
        if uid in rejected
    )
    detail = f' ({reasons})' if reasons else ''

    if operation == 'C-GET':
        local_aet = DICOMServerConfiguration.load().ae_title
        hint = (
            f'Edit remote node {node.name!r} and uncheck "Prefer C-GET" to '
            f'use C-MOVE (requires AE {local_aet!r} registered as a C-MOVE '
            'destination on the peer)'
        )
    elif operation == 'C-MOVE':
        hint = (
            f'Enable "Prefer C-GET" on remote node {node.name!r} '
            '(no inbound connection needed)'
        )
    else:
        hint = 'the peer does not accept Study/Patient Root C-FIND for our calling AE title'

    raise QRModelNotAcceptedError(
        f'peer {node.ae_title!r} does not support {operation}{detail} — {hint}'
    )


def _find_studies_on_assoc(assoc, model, node, patient_id: str) -> list[dict]:
    """STUDY-level C-FIND on an open association.

    Returns a list of dicts: study_instance_uid, study_date, study_time,
    study_description, accession_number, modalities, series_count, instances.
    Raises ConnectionError if the peer drops the association mid-query."""
    q = Dataset()
    q.QueryRetrieveLevel = 'STUDY'
    q.PatientID = patient_id
    q.StudyInstanceUID = ''
    q.StudyDate = ''
    q.StudyTime = ''
    q.StudyDescription = ''
    q.AccessionNumber = ''
    q.ModalitiesInStudy = ''
    q.NumberOfStudyRelatedSeries = ''
    q.NumberOfStudyRelatedInstances = ''

    results = []
    for status, identifier in assoc.send_c_find(q, model):
        code = getattr(status, 'Status', None)
        if status is None or code is None:
            raise ConnectionError(
                f'C-FIND on {node} aborted or timed out — the peer '
                'accepted the association but dropped it during the '
                'query. The node likely has no Query/Retrieve service '
                '(common for treatment machines); it can only receive '
                'data via push (C-STORE).'
            )
        if code in (0xFF00, 0xFF01) and identifier:
            results.append({
                'study_instance_uid': str(getattr(identifier, 'StudyInstanceUID', '') or ''),
                'study_date': str(getattr(identifier, 'StudyDate', '') or ''),
                'study_time': str(getattr(identifier, 'StudyTime', '') or ''),
                'study_description': str(getattr(identifier, 'StudyDescription', '') or ''),
                'accession_number': str(getattr(identifier, 'AccessionNumber', '') or ''),
                'modalities': str(getattr(identifier, 'ModalitiesInStudy', '') or ''),
                'series_count': getattr(identifier, 'NumberOfStudyRelatedSeries', None),
                'instances': getattr(identifier, 'NumberOfStudyRelatedInstances', None),
            })
        elif code not in (0xFF00, 0xFF01, 0x0000):
            comment = getattr(status, 'ErrorComment', '') or ''
            logger.warning(
                'C-FIND on %s returned status 0x%04X%s',
                node, code, f' ({comment})' if comment else '',
            )
    logger.info('C-FIND %s patient %s: %d studies', node, patient_id, len(results))
    return results


def find_studies(node: RemoteDICOMNode, patient_id: str) -> list[dict]:
    """C-FIND at STUDY level for a PatientID (Study Root preferred, Patient
    Root used when the peer accepts only that model)."""
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
    assoc = _connect(ae, node)
    try:
        model = _negotiated_qr_model(
            assoc,
            StudyRootQueryRetrieveInformationModelFind,
            PatientRootQueryRetrieveInformationModelFind,
            'C-FIND', node,
        )
        return _find_studies_on_assoc(assoc, model, node, patient_id)
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
                    study['remote_patient_id'] = pid
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


def _find_series_on_assoc(assoc, model, node, study_instance_uid: str,
                          patient_id: str | None = None) -> tuple[list[dict], str]:
    """SERIES-level C-FIND on an open association.

    Returns (series, error): on success ([dicts], ''); on peer-level failure
    ([], reason). Does not raise — a peer that refuses/aborts series queries
    degrades the study to whole-study selection rather than sinking the
    batch query.
    """
    q = Dataset()
    q.QueryRetrieveLevel = 'SERIES'
    if patient_id:
        q.PatientID = patient_id
    q.StudyInstanceUID = study_instance_uid
    q.SeriesInstanceUID = ''
    q.SeriesDescription = ''
    q.Modality = ''
    q.SeriesDate = ''
    q.SeriesNumber = ''
    q.NumberOfSeriesRelatedInstances = ''

    results = []
    try:
        for status, identifier in assoc.send_c_find(q, model):
            code = getattr(status, 'Status', None) if status is not None else None
            if status is None or code is None:
                return [], 'C-FIND aborted or timed out during series query'
            if code in (0xFF00, 0xFF01) and identifier:
                results.append({
                    'series_instance_uid': str(getattr(identifier, 'SeriesInstanceUID', '') or ''),
                    'series_description': str(getattr(identifier, 'SeriesDescription', '') or ''),
                    'modality': str(getattr(identifier, 'Modality', '') or ''),
                    'series_date': str(getattr(identifier, 'SeriesDate', '') or ''),
                    'series_number': str(getattr(identifier, 'SeriesNumber', '') or ''),
                    'instances': getattr(identifier, 'NumberOfSeriesRelatedInstances', None),
                })
            elif code not in (0xFF00, 0xFF01, 0x0000):
                comment = getattr(status, 'ErrorComment', '') or ''
                return [], f'series query returned status 0x{code:04X} ({comment})'
    except Exception as e:
        logger.exception('SERIES C-FIND failed on %s for study %s', node, study_instance_uid)
        return [], str(e)
    return results, ''


def find_series(node: RemoteDICOMNode, study_instance_uid: str,
                patient_id: str | None = None) -> tuple[list[dict], str]:
    """SERIES-level C-FIND for one study on its own association.

    Returns (series, error) like _find_series_on_assoc; raises only if the
    association or model negotiation itself fails."""
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
    assoc = _connect(ae, node)
    try:
        model = _negotiated_qr_model(
            assoc,
            StudyRootQueryRetrieveInformationModelFind,
            PatientRootQueryRetrieveInformationModelFind,
            'C-FIND', node,
        )
        return _find_series_on_assoc(
            assoc, model, node, study_instance_uid, patient_id,
        )
    finally:
        assoc.release()


def find_studies_with_series(node: RemoteDICOMNode,
                             patient_ids: list[str]) -> tuple[list[dict], list[str]]:
    """One association: STUDY-level C-FIND for each patient ID, then
    SERIES-level C-FIND for every discovered study.

    Returns (studies, errors). Studies are deduped by StudyInstanceUID and
    tagged with remote_patient_id (the ID whose query produced them); each
    gains 'series' (list of series dicts) and optionally 'series_error'.
    errors collects per-ID failures. Raises ConnectionError when the
    association cannot be established or every patient ID's study query
    failed."""
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
    assoc = _connect(ae, node)
    try:
        model = _negotiated_qr_model(
            assoc,
            StudyRootQueryRetrieveInformationModelFind,
            PatientRootQueryRetrieveInformationModelFind,
            'C-FIND', node,
        )
        seen = set()
        studies = []
        errors = []
        for pid in patient_ids:
            try:
                for study in _find_studies_on_assoc(assoc, model, node, pid):
                    uid = study.get('study_instance_uid')
                    if uid and uid not in seen:
                        seen.add(uid)
                        study['remote_patient_id'] = pid
                        studies.append(study)
            except Exception as e:
                logger.exception('C-FIND failed for patient ID %r on %s', pid, node)
                errors.append(f'{pid}: {e}')
        if errors and len(errors) == len(patient_ids):
            raise ConnectionError(
                f'C-FIND on {node} failed for every patient ID tried: '
                + '; '.join(errors)
            )
        for study in studies:
            series, series_error = _find_series_on_assoc(
                assoc, model, node, study['study_instance_uid'],
                study.get('remote_patient_id'),
            )
            study['series'] = series
            if series_error:
                study['series_error'] = series_error
        return studies, errors
    finally:
        assoc.release()


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


def _retrieve_identifier(level: str, study_instance_uid: str,
                         series_instance_uid: str | None = None,
                         patient_id: str | None = None) -> Dataset:
    """Build a C-MOVE/C-GET identifier at STUDY or SERIES level."""
    q = Dataset()
    q.QueryRetrieveLevel = level
    if patient_id:
        q.PatientID = patient_id
    q.StudyInstanceUID = study_instance_uid
    if series_instance_uid:
        q.SeriesInstanceUID = series_instance_uid
    return q


def move_study(node: RemoteDICOMNode, study_instance_uid: str,
               patient_id: str | None = None, destination: str | None = None) -> dict:
    """C-MOVE a study to our own Storage SCP (destination = our AE title).

    The remote must be able to resolve our AE title to host:port (PACS config).
    Returns sub-op stats: status/completed/failed/warning.
    """
    return _move(node, 'STUDY', study_instance_uid, None, patient_id, destination)


def move_series(node: RemoteDICOMNode, study_instance_uid: str,
                series_instance_uid: str, patient_id: str | None = None,
                destination: str | None = None) -> dict:
    """C-MOVE a single series of a study to our own Storage SCP."""
    return _move(
        node, 'SERIES', study_instance_uid, series_instance_uid,
        patient_id, destination,
    )


def _move(node: RemoteDICOMNode, level: str, study_instance_uid: str,
          series_instance_uid: str | None, patient_id: str | None,
          destination: str | None) -> dict:
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelMove)
    assoc = _connect(ae, node)
    try:
        model = _negotiated_qr_model(
            assoc,
            StudyRootQueryRetrieveInformationModelMove,
            PatientRootQueryRetrieveInformationModelMove,
            'C-MOVE', node,
        )
        destination = destination or DICOMServerConfiguration.load().ae_title
        q = _retrieve_identifier(
            level, study_instance_uid, series_instance_uid, patient_id,
        )
        stats = _collect_subop_stats(
            assoc.send_c_move(q, destination, model),
            f'C-MOVE on {node}',
        )
        logger.info(
            'C-MOVE %s %s %s -> %s: %s', node, level,
            series_instance_uid or study_instance_uid, destination, stats,
        )
        return stats
    finally:
        assoc.release()


# Extra storage SOP classes offered on C-GET beyond the curated common set.
# An association negotiates at most 128 presentation contexts and the two
# Q/R-GET models (Study Root + Patient Root) take two slots, leaving room for
# 126 — the curated 120 plus 6 extras, spent on the second-generation RT
# objects an oncology PACS serves.
_EXTRA_STORAGE_UIDS = (
    '1.2.840.10008.5.1.4.1.1.481.10',  # RT Physician Intent
    '1.2.840.10008.5.1.4.1.1.481.11',  # RT Segment Annotation
    '1.2.840.10008.5.1.4.1.1.481.12',  # RT Radiation Set
    '1.2.840.10008.5.1.4.1.1.481.16',  # RT Radiation Record Set
    '1.2.840.10008.5.1.4.1.1.481.22',  # RT Treatment Preparation
    '1.2.840.10008.5.1.4.1.1.481.23',  # Enhanced RT Image
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
    return _get(node, 'STUDY', study_instance_uid, None, patient_id)


def get_series(node: RemoteDICOMNode, study_instance_uid: str,
               series_instance_uid: str, patient_id: str | None = None) -> dict:
    """C-GET a single series of a study (same ingest path as get_study)."""
    return _get(node, 'SERIES', study_instance_uid, series_instance_uid, patient_id)


def _get(node: RemoteDICOMNode, level: str, study_instance_uid: str,
         series_instance_uid: str | None, patient_id: str | None) -> dict:
    ae = _scu_ae()
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelGet)
    storage_uids = _get_storage_uids()
    for uid in storage_uids:
        ae.add_requested_context(uid)
    roles = [build_role(uid, scp_role=True) for uid in storage_uids]
    assoc = _connect(
        ae, node, ext_neg=roles,
        evt_handlers=[(evt.EVT_C_STORE, handle_store)],
    )
    try:
        model = _negotiated_qr_model(
            assoc,
            StudyRootQueryRetrieveInformationModelGet,
            PatientRootQueryRetrieveInformationModelGet,
            'C-GET', node,
        )
        q = _retrieve_identifier(
            level, study_instance_uid, series_instance_uid, patient_id,
        )
        stats = _collect_subop_stats(
            assoc.send_c_get(q, model),
            f'C-GET on {node}',
        )
        logger.info(
            'C-GET %s %s %s: %s', node, level,
            series_instance_uid or study_instance_uid, stats,
        )
        return stats
    finally:
        assoc.release()


# Representative storage SOP classes for the capability probe — enough to tell
# whether the peer accepts storage presentation contexts with us in the SCP
# role (required for it to deliver instances during C-GET).
_PROBE_STORAGE_UIDS = (
    '1.2.840.10008.5.1.4.1.1.2',      # CT Image Storage
    '1.2.840.10008.5.1.4.1.1.4',      # MR Image Storage
    '1.2.840.10008.5.1.4.1.1.128',    # PET Image Storage
    '1.2.840.10008.5.1.4.1.1.1',      # Computed Radiography Image Storage
    '1.2.840.10008.5.1.4.1.1.6.1',    # Ultrasound Image Storage
    '1.2.840.10008.5.1.4.1.1.20',     # Nuclear Medicine Image Storage
    '1.2.840.10008.5.1.4.1.1.7',      # Secondary Capture Image Storage
    '1.2.840.10008.5.1.4.1.1.481.1',  # RT Image Storage
    '1.2.840.10008.5.1.4.1.1.481.5',  # RT Plan Storage
    '1.2.840.10008.5.1.4.1.1.481.2',  # RT Dose Storage
    '1.2.840.10008.5.1.4.1.1.481.3',  # RT Structure Set Storage
    '1.2.840.10008.5.1.4.1.1.481.23',  # Enhanced RT Image Storage
)

_PROBE_PATIENT_ID = 'ZZ_CHAVI_CAPABILITY_PROBE'


def probe_qr_capabilities(node: RemoteDICOMNode) -> dict:
    """Probe which Query/Retrieve services a remote node actually supports.

    Returns a dict: find/move/get each 'study' | 'patient' | 'broken' | None
    ('broken' = the FIND context was negotiated but the query itself aborted —
    the tell-tale of a storage-only node like a treatment machine's data
    system), get_storage = count of storage contexts accepted with us in the
    SCP role (needed for C-GET delivery), and 'error' if the association
    itself could not be established.

    C-FIND is exercised with a real (non-matching) query because negotiation
    alone cannot distinguish an implemented service from an accept-then-abort
    stub. MOVE/GET are reported at negotiation level only — issuing real
    retrieves would have side effects.
    """
    ae = _scu_ae()
    ops = {
        'find': (StudyRootQueryRetrieveInformationModelFind,
                 PatientRootQueryRetrieveInformationModelFind),
        'move': (StudyRootQueryRetrieveInformationModelMove,
                 PatientRootQueryRetrieveInformationModelMove),
        'get': (StudyRootQueryRetrieveInformationModelGet,
                PatientRootQueryRetrieveInformationModelGet),
    }
    for study_uid, patient_uid in ops.values():
        ae.add_requested_context(study_uid)
        ae.add_requested_context(patient_uid)
    for uid in _PROBE_STORAGE_UIDS:
        ae.add_requested_context(uid)
    roles = [build_role(uid, scp_role=True) for uid in _PROBE_STORAGE_UIDS]

    try:
        assoc = _connect(ae, node, ext_neg=roles)
    except ConnectionError as e:
        return {'find': None, 'move': None, 'get': None,
                'get_storage': 0, 'error': str(e)}

    try:
        accepted = {cx.abstract_syntax for cx in assoc.accepted_contexts}
        caps = {}
        for op, (study_uid, patient_uid) in ops.items():
            caps[op] = (
                'study' if study_uid in accepted
                else 'patient' if patient_uid in accepted
                else None
            )
        caps['get_storage'] = sum(
            1 for uid in _PROBE_STORAGE_UIDS if uid in accepted
        )

        if caps['find']:
            find_model = (
                StudyRootQueryRetrieveInformationModelFind
                if caps['find'] == 'study'
                else PatientRootQueryRetrieveInformationModelFind
            )
            q = Dataset()
            q.QueryRetrieveLevel = 'STUDY'
            q.PatientID = _PROBE_PATIENT_ID
            q.StudyInstanceUID = ''
            responded = False
            try:
                for status, _ in assoc.send_c_find(q, find_model):
                    if getattr(status, 'Status', None) is not None:
                        responded = True
            except Exception:
                pass
            if not responded:
                caps['find'] = 'broken'

        logger.info('Q/R capabilities %s: %s', node, caps)
        return caps
    finally:
        assoc.release()

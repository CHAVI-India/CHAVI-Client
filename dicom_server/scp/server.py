"""DICOM SCP server lifecycle — build the AE and run the listener."""
import logging
import signal
import threading

from pynetdicom import AE, evt, AllStoragePresentationContexts
from pynetdicom.sop_class import (
    Verification,
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
)

from dicom_server.models import DICOMServerConfiguration
from dicom_server.scp.handlers import handle_echo, handle_store, handle_find

logger = logging.getLogger(__name__)

HANDLERS = [
    (evt.EVT_C_ECHO, handle_echo),
    (evt.EVT_C_STORE, handle_store),
    (evt.EVT_C_FIND, handle_find),
]


def build_ae() -> AE:
    """AE for the SCP role: all storage classes, verification, QR-Find."""
    config = DICOMServerConfiguration.load()
    ae = AE(ae_title=config.ae_title)
    ae.supported_contexts = AllStoragePresentationContexts
    ae.add_supported_context(Verification)
    ae.add_supported_context(PatientRootQueryRetrieveInformationModelFind)
    ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
    ae.maximum_pdu_size = config.max_pdu
    return ae


def run_server():
    """Run the SCP until SIGTERM/SIGINT. Blocks the calling thread."""
    config = DICOMServerConfiguration.load()
    ae = build_ae()
    scp = ae.start_server(
        (config.bind_address, config.port),
        block=False,
        evt_handlers=HANDLERS,
    )
    logger.info(
        "DICOM SCP '%s' listening on %s:%s",
        config.ae_title, config.bind_address, config.port,
    )

    stop = threading.Event()

    def _shutdown(signum, frame):
        logger.info("Received signal %s — shutting down DICOM SCP", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while not stop.wait(1):
            pass
    finally:
        scp.shutdown()
        logger.info("DICOM SCP stopped")

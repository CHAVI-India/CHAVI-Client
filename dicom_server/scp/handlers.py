"""DIMSE event handlers for the DICOM SCP.

Handlers run in pynetdicom association threads — no request lifecycle closes
their thread-local DB connections, so each handler closes them on entry and
exit (CONN_MAX_AGE=0 makes close_old_connections() an immediate close).
"""
import functools
import inspect
import logging

from django.db import close_old_connections
from pydicom.dataset import Dataset

from dicom_server.models import DICOMServerConfiguration
from dicom_server.services import ingest, query

logger = logging.getLogger(__name__)


def _db_cleanup(fn):
    """Close the handler thread's DB connection before and after the event."""
    if inspect.isgeneratorfunction(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            close_old_connections()
            try:
                yield from fn(*args, **kwargs)
            finally:
                close_old_connections()
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            close_old_connections()
            try:
                return fn(*args, **kwargs)
            finally:
                close_old_connections()
    return wrapper


@_db_cleanup
def handle_echo(event):
    """C-ECHO — always succeed."""
    return 0x0000


@_db_cleanup
def handle_store(event):
    """C-STORE — validate + store via the ingest service."""
    config = DICOMServerConfiguration.load()

    ds = event.dataset
    ds.file_meta = event.file_meta

    status = Dataset()
    if not config.is_enabled:
        logger.warning("C-STORE rejected: server is disabled")
        status.Status = ingest.STATUS_SERVER_DISABLED
        status.ErrorComment = 'Storage disabled by server configuration'
        return status

    requestor = event.assoc.requestor
    result = ingest.ingest_dataset(
        ds,
        calling_ae=getattr(requestor, 'ae_title', ''),
        called_ae=getattr(event.assoc.acceptor, 'ae_title', ''),
        remote_addr=getattr(requestor, 'address', ''),
    )
    status.Status = result.status
    if result.reason:
        status.ErrorComment = result.reason[:64]
    return status


@_db_cleanup
def handle_find(event):
    """C-FIND — answer PATIENT and STUDY level queries from our models.

    SERIES/IMAGE levels return success with no matches: series/instance
    metadata is populated by the deidentification pipeline, not at ingest.
    """
    identifier = event.identifier
    level = getattr(identifier, 'QueryRetrieveLevel', None)
    if not level:
        yield 0xC000, None
        return

    level = str(level).upper()
    if level not in ('PATIENT', 'STUDY'):
        logger.info("C-FIND level %r not supported — returning success/no matches", level)
        return

    for response in query.iter_find_responses(identifier, level):
        if event.is_cancelled:
            yield 0xFE00, None
            return
        yield 0xFF00, response

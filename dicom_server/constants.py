"""Shared constants for dicom_server services.

Kept free of Django model imports so any service module can import it:
scp/handlers -> ingest -> qr_client -> scp/handlers would be a cycle if a
shared constant lived in qr_client instead.
"""

# Modalities whose instances carry RT attributes worth enumerating via
# IMAGE-level C-FIND (labels, approval status, reference sequences).
RT_DETAIL_MODALITIES = frozenset(
    {'RTSTRUCT', 'RTPLAN', 'RTDOSE', 'RTREG', 'RTIMAGE'})

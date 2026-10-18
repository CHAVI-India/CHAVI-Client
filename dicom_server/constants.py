"""Shared constants for dicom_server services.

Kept free of Django model imports so any service module can import it:
scp/handlers -> ingest -> qr_client -> scp/handlers would be a cycle if a
shared constant lived in qr_client instead.
"""

# Modalities whose instances carry RT attributes worth enumerating via
# IMAGE-level C-FIND (labels, approval status, reference sequences).
RT_DETAIL_MODALITIES = frozenset(
    {'RTSTRUCT', 'RTPLAN', 'RTDOSE', 'RTREG', 'RTIMAGE'})

# Subset of RT_DETAIL_MODALITIES the selection UI presents as per-instance
# rows (mirrors RT_DETAIL_MODS in templates/dicom_server/batch_select.html).
# The ingest selection filter applies its strict per-SOP drop only to these;
# RTREG/RTIMAGE are selectable at series level in the UI, so at ingest they
# are kept or dropped by series membership, exactly like any other modality.
RT_INSTANCE_SELECTABLE_MODALITIES = frozenset(
    {'RTSTRUCT', 'RTPLAN', 'RTDOSE'})

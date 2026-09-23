"""Test helpers for dicom_server — synthetic datasets and loopback fixtures."""
import tempfile

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (
    generate_uid, ExplicitVRLittleEndian, CTImageStorage,
)


def make_test_dataset(
    patient_id='TEST001', patient_name='Test^Patient',
    study_uid=None, series_uid=None, sop_uid=None,
    modality='CT', study_date='20240101',
    study_description='Test Study', series_description='Test Series',
):
    """Build a minimal valid CT Image Storage dataset (synthetic, anonymised)."""
    study_uid = study_uid or generate_uid()
    series_uid = series_uid or generate_uid()
    sop_uid = sop_uid or generate_uid()

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    ds = Dataset()
    ds.file_meta = file_meta
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = modality
    ds.PatientID = patient_id
    ds.PatientName = patient_name
    ds.StudyDate = study_date
    ds.StudyDescription = study_description
    ds.SeriesDescription = series_description
    ds.AccessionNumber = 'ACC001'
    ds.ReferringPhysicianName = 'Test^Physician'
    ds.SeriesNumber = 1
    ds.InstanceNumber = 1
    # Image plane / pixel attributes (Type 1 for CT Image Storage)
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = 'MONOCHROME2'
    ds.Rows = 4
    ds.Columns = 4
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = b'\x00' * 4 * 4 * 2
    return ds


def push_dataset(host, port, called_aet, ds, calling_aet='TESTSCU', timeout=20):
    """Test-only storage SCU helper — pushes one dataset to a peer.

    Lives in tests only; the shipped product never sends instances out.
    Returns the C-STORE response status dataset (or None on failure).
    """
    from pynetdicom import AE
    from pynetdicom.sop_class import CTImageStorage

    ae = AE(ae_title=calling_aet)
    ae.add_requested_context(CTImageStorage)
    ae.network_timeout = timeout
    ae.dimse_timeout = timeout
    assoc = ae.associate(host, port, ae_title=called_aet)
    if not assoc.is_established:
        return None
    try:
        return assoc.send_c_store(ds)
    finally:
        assoc.release()


def find_free_port():
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

DICOM Data Import (Admin)
============================

.. note::
   The easiest way to add scans is the upload page described in :doc:`handling_dicom_data`, or fetching them straight from the imaging system — see :doc:`dicom_retrieval`. This page is kept for staff who import through the Django admin area.

The admin area offers two ways to import DICOM studies:

1. **Patient DICOM Files** — for studies of a single patient
2. **Bulk DICOM File Upload** — for studies of many patients at once

Both take a ZIP file. After saving the upload, select it in the list and run the matching action ("Extract and Process DICOM File and extract metadata" for single-patient, "Process Bulk DICOM Files" for bulk).

How files are stored
---------------------

For processed files::

    media/
    ├── Patient_ID_1/
    │   └── Study_Instance_UID/
    │       └── SOP_Instance_UID.dcm
    ├── Patient_ID_2/
    │   └── Study_Instance_UID/
    │       └── SOP_Instance_UID.dcm
    └── Unprocessed_DICOM/
        └── Unknown_Patient_ID/
            └── Study_Instance_UID/
                └── SOP_Instance_UID.dcm

Important Notes
----------------

* Always verify that DICOM files are properly anonymized before upload
* For single patient uploads, ensure all DICOM files belong to the correct patient
* The system will maintain the original DICOM structure while organizing files
* Unprocessed files (no matching patient) can be found in the Unprocessed_DICOM directory
* Processing large DICOM datasets may take some time
* Regular backups of the DICOM data are recommended

.. tip::
   When uploading multiple studies for a single patient, it's recommended to use the Single Patient Upload method as it ensures proper patient ID matching.

.. warning::
   Do not modify the DICOM files or directory structure manually after upload. This may cause inconsistencies in the database.

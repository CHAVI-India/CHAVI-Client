DICOM Data Import
================

The CHAVI application supports two methods for importing DICOM studies:

1. Single Patient DICOM Upload
2. Bulk DICOM Upload for Multiple Patients

Single Patient DICOM Upload
--------------------------

This method is used when you have DICOM studies for a single patient.

Steps:
^^^^^^

1. Navigate to "Patient DICOM Files" in the Django Admin interface
2. Click "Add Patient DICOM File"
3. Select the patient from the dropdown menu
4. Upload a ZIP file containing the DICOM studies
   
   * Only ZIP files are accepted
   * All DICOM studies in the ZIP must belong to the same patient
   * Multiple studies for the same patient can be included

5. Save the upload
6. Select the uploaded file from the list
7. Use the "Extract and Process DICOM File and extract metadata" action

Processing Details:
^^^^^^^^^^^^^^^^^

The system will:

* Extract all DICOM files from the ZIP
* Verify and standardize the Patient ID in DICOM metadata
* Create a directory structure: ``Patient_ID/Study_Instance_UID/SOP_Instance_UID.dcm``
* Extract and store study information in the database:
   
   * Study Instance UID
   * Study Date
   * Study Description
   * Series Descriptions

After that the folder will be zipped. The zipped file is ready for de-identification.

Bulk DICOM Upload
----------------

This method allows uploading DICOM studies for multiple patients simultaneously.

Steps:
^^^^^^

1. Navigate to "Bulk DICOM Upload" in the Django Admin interface
2. Click "Add Bulk DICOM Upload"
3. Upload a ZIP file containing DICOM studies from multiple patients
4. Save the upload
5. Select the uploaded file from the list
6. Use the "Process Bulk DICOM Files" action

Processing Details:
^^^^^^^^^^^^^^^^^

The system will:

* Extract all DICOM files from the ZIP
* For each DICOM file:
   
   * Read the Patient ID from DICOM metadata
   * Check if the patient exists in the system
   * If patient exists:
      
      * Save to patient's directory
      * Update DICOM study information in database
   
   * If patient doesn't exist:
      
      * Move files to "Unprocessed_DICOM" directory
      * Log as unprocessed

Directory Structure:
^^^^^^^^^^^^^^^^^^

For processed files:
::

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
-------------

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

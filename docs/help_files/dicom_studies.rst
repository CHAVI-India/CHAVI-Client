DICOM Studies
============

The DICOM Studies module manages medical imaging studies associated with patients.

Study Management
--------------

View Studies:
^^^^^^^^^^^
1. Navigate to "DICOM Studies" in the Django Admin interface
2. Search by patient ID or study details
3. View study information:
   
   * Study Instance UID
   * Study Date
   * Study Description
   * Series Descriptions

Study Association
---------------

Studies can be associated with:
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* Diagnoses
* Lesions
* Treatment responses
* Outcomes
* Projects

To associate a study:
^^^^^^^^^^^^^^^^^^^

1. Navigate to the relevant record (e.g., Diagnosis, Lesion)
2. Use the "DICOM Studies" selection field
3. Choose applicable studies from the list
4. Save the record

Project Association
-----------------

To associate studies with research projects:

1. Navigate to "Projects"
2. Select or create a project
3. Use the DICOM Study Project inline form
4. Select studies to include
5. Save the project

Study Information
---------------

Each DICOM study record includes:

* Patient reference
* Study date
* Study description
* Series descriptions
* Study Instance UID (unique identifier)

.. tip::
   Use the search functionality to quickly find studies by patient ID or date.

.. note::
   DICOM studies are automatically populated when processing DICOM files through the import features. 
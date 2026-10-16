Suggested Data Entry Workflow
===============================

We suggest that you use the following workflow when entering patient data.

#. First enter the patient data. A basic set of clinical data especially the patient ID is required. 

   * Rather than typing it all in, you can also bring data in from a spreadsheet (see :doc:`csv_import_wizard`) or let the system read documents such as reports and summaries (see :doc:`automatic_data_extraction`).

#. After completing clinical data entry, add the patient's scans — either upload a ZIP file or fetch them from the imaging system (see :doc:`handling_dicom_data` and :doc:`dicom_retrieval`).
#. Associate the patient and DICOM data to the project.
#. Check that the DICOM study types are right — most are set automatically, but you can correct any by hand.
#. Associate the DICOM studies to specific diagnoses / treatments as required.
#. When the data is complete, de-identify it ready for upload to the CHAVI databank (see :doc:`deidentification`).

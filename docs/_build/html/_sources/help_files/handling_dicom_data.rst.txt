Handling DICOM Data
====================

The CHAVI client allows users to handle DICOM data in the following ways:

1. Importing DICOM data for a specific Patient
2. Importing DICOM data for multiple patients at once

Single Patient Import
---------------------

When to use: This method is to be used when single / multiple studies are to be uploaded for a single patient but the patient ID in these studies are not necessarily same. For example, your institute may have different ID conventions used. Or patients may have had imaging done at different centers. In these situations it is important to ensure that the patient ID is properly matched. The single patient upload system ensures that patient ID in all uploaded DICOM studies matches the patient ID against which the DICOM data is being uploaded.

Caution: Do ensure that the data being uploaded belongs to a single patient.

Steps:
^^^^^^

#. Navigate to the link titled - DICOM file uploade (Patient wise) in the Django Admin interface
#. Click the purple add button at the top right corner to add a new instance. 
#. Select the patient from the dropdown menu
#. Upload a ZIP file containing the DICOM studies
   
   * Only ZIP files are accepted
   * All DICOM studies in the ZIP must belong to the same patient
   * Multiple studies for the same patient can be included

#. Save the upload. Once the upload is completed the page will bring you back to the list page.
#. Select the uploaded file from the list. Processing status will be shown in the table. 
#. In the bar that appears at the bottom, select the "Extract and Process DICOM File and extract metadata" action.

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
   * Folder path

After that the folder will be zipped. The zipped file is ready for de-identification.

Bulk DICOM Upload
----------------

This method allows uploading DICOM studies for multiple patients simultaneously. This method should be used when you have patient ID in the proper format and can be used to upload imaging data for multiple patients at once. 

Caution: This method does not check for the patient ID and therefore if a patient ID is not matched it will not be processed. 

Steps:
^^^^^^

#. Navigate to the link titled - Bulk DICOM File Upload in the Django Admin interface.
#. Click the purple add button at the top right corner to add a new instance. 
#. Upload a ZIP file containing the DICOM studies
   
   * Only ZIP files are accepted
   * Multiple studies for the same patient can be included
   * Multiple studies can be included for multiple patients
   * Keep the uploaded file size to 1 GB or less to ensure that the system does not give a timeout.

#. Save the upload. Once the upload is completed the page will bring you back to the list page.
#. Select the uploaded file from the list. Processing status will be shown in the table. 
#. In the bar that appears at the bottom, select the "Process Bulk DICOM Files" action.

Processing Details:
^^^^^^^^^^^^^^^^^

The system will:

* Extract all DICOM files from the ZIP
* Match the patient ID to existing patient IDs in the system. Please note that this will be an exact match and if the match is not found the dicom data will be moved to an unprocessed dicom folder.
* Create a directory structure: ``Patient_ID/Study_Instance_UID/SOP_Instance_UID.dcm``
* Extract and store study information in the database:
   
   * Study Instance UID
   * Study Date
   * Study Description
   * Series Descriptions
   * Folder path

After that the folder will be zipped. The zipped file is ready for de-identification.   


Associate DICOM studies with Project
---------------------------------------

This functionality is provided to allow you to associate a batch of DICOM studies with a project. Note that the same DICOM studies may be part of multiple projects. 

Steps:
^^^^^^

#. Navigate to the link title DICOM Study Data in the Django Admin interface.
#. Select the DICOM studies which you wish to associate with a given project.
#. Select the action "Associate selected DICOM studies with a Project" from the dropdown menu. Click on the Run button to run the action.
#. Select the project from the dropdown menu in the popup page.
#. Click the "Associate DICOM Studies with Project" button to complete the process.

The DICOM studies associated with a project will now appear in the page titled "DICOM Studies Associated with Projects". This would allow you to see all the studies that have been associated with a specfic project and delete the association if required. 

Adding Study Type information
-----------------------------

DICOM study may be done for various reasons. This feature allows you to manually specify this for each individual DICOM study. 
The following study types are avaialble:

#. Pre-treatment Diagnostic image: These will diagnostic images acquired before the start of the treatment.
#. Planning image: These will be images acquired for the plannning process including simulation CT, simuation x-rays and planning MR or PET.
#. On treatment verification image: These will be images acquired during the treatment to verify the delivery of the treatment. Examples include portal films, CBCT, EPID, Cine images etc
#. Planning image for adaptive treatment: These will be images acquired for planning adaptive treatment. Note that in some situations, a image may be an On treatment verification image as well as a planning image for adaptive treatment.
#. Post-treatment Therapy response image: These will be images acquired after the treatment to evaluate the response to the treatment.
#. Therapy delivery image: These will be images acquired during the treatment to evaluate the delivery of the treatment. Examples are images acquired after radionuclide treatment or transit dosimetry images.
#. Therapy QA image: These will be images acquired during the treatment to evaluate the quality of the treatment. These would include images like QA films, portal dosimetry images, 3D array dosimetry images etc.
#. Post-treatment Diagnostic image: These will be images acquired after the treatment to evaluate the final state of the treatment.
#. Other: These will be images acquired for other purposes.

You can select the study type from the dropdown and then click on the Save button that appears at the bottom right to save this information. 






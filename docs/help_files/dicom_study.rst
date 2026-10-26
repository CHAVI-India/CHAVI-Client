DICOM Study Data
====================

The DICOM study pages show each patient's imaging studies and their details,
and are where scans get their study type and their link to a project.

Where the studies come from
---------------------------

Studies are not entered by hand — they arrive one of three ways:

* A ZIP file you upload — see :doc:`handling_dicom_data`.
* A fetch from your hospital's imaging system — see :doc:`dicom_retrieval`.
* Scans the imaging system pushes to the DICOM server on its own — see :doc:`dicom_server_setup`.

Study type
----------

Each study has a **study type** recording why it was done (pre-treatment
diagnostic, planning, on-treatment verification, post-treatment response,
and so on). Most studies get their type automatically from the scan details;
you can always correct it from the dropdown on the study. A type set by hand
is never overwritten by the automatic rules. The full list of study types and
what they mean is on the :doc:`handling_dicom_data` page ("Adding Study
Type information").

Data shown for a study
----------------------

Study Information
^^^^^^^^^^^^^^^^^^^^
* **Patient Link**: The patient whose imaging is being recorded
* **Study Instance UID**: Unique identifier for the imaging study
* **Study Date**: When imaging was performed
* **Study Description**: Type/purpose of imaging study

Series Information
^^^^^^^^^^^^^^^^^^^^
* **Series Descriptions**: Details of image series within study

Project Association
^^^^^^^^^^^^^^^^^^^^^
* **Project Assignment**: CHAVI projects associated with these images. A study
  may belong to more than one project. Batch association of many studies
  with a project is done from the admin area — see :doc:`handling_dicom_data`. 
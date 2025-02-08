Diagnosis
=========

The Diagnosis module captures essential information about a patient's cancer diagnosis. Each patient can have multiple diagnoses, and each diagnosis serves as a reference point for related treatments and outcomes.

Data Collection Fields
--------------------

Basic Diagnosis Information
^^^^^^^^^^^^^^^^^^^^^^^^^
* **Cancer System**: The major category of cancer (e.g., Breast, Lung, etc.)
* **Diagnosis (ICD Code)**: The specific diagnosis using ICD-11 classification
* **Diagnosis Date**: When the diagnosis was first made or confirmed
* **Presentation Type**: How the disease presented (e.g., New diagnosis, Recurrence)

Anatomical Information
^^^^^^^^^^^^^^^^^^^^
* **Cancer Site**: The anatomical location using Foundational Model of Anatomy (FMA) codes
* **Cancer Side**: The laterality of the cancer (Left, Right, Bilateral)

Diagnostic Details
^^^^^^^^^^^^^^^
* **Diagnostic Modality**: The method used to confirm the diagnosis (e.g., Biopsy, Imaging)
* **Associated DICOM Studies**: Any imaging studies related to this diagnosis
* **Project Assignment**: CHAVI projects associated with this diagnosis

Special Considerations
--------------------

1. Multiple Diagnoses:

   #. A patient can have multiple diagnoses  
   #. Each diagnosis should be entered separately  
   #. Ensure correct linking of treatments and outcomes to specific diagnoses  

2. Diagnostic Dates:

   #. Use the date of pathological confirmation when available  
   #. For clinical diagnoses, use the date of definitive clinical assessment  
   #. Document the basis for the diagnosis date  

3. Project Linkage:

   #. Each diagnosis can be linked to specific CHAVI projects  
   #. Different projects may have varying data requirements  
   #. Ensure all required project-specific data is collected  

4. Imaging Studies:

   #. Link relevant DICOM studies to the diagnosis  
   #. Multiple imaging studies can be associated with one diagnosis  
   #. Include both diagnostic and follow-up imaging as appropriate 
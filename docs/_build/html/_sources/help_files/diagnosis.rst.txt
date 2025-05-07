Diagnosis
=================

The Diagnosis module captures essential information about a patient's cancer diagnosis. Each patient can have multiple diagnoses, and each diagnosis serves as a reference point for related treatments and outcomes.

.. note::

   Diagnosis is linked to a patient ID.

   Diagnosis -> Patient
..   

Data Collection Fields
-----------------------

.. list-table:: Diagnosis Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Patient
     - patient
     - The patient for whom the diagnosis is being recorded
   * - Cancer System
     - cancer_system
     - The major category of cancer (e.g., Breast, Lung, etc.)
   * - Diagnosis (ICD Code)
     - diagnosis
     - The specific diagnosis using ICD-11 classification. If the patient has multiple diagnoses, each should be entered separately
   * - Diagnosis Date
     - diagnosis_date
     - When the diagnosis was first made or confirmed. This can be a date when the patient came to the hospital for the first time or when pathological proof was obtained
   * - Presentation Type
     - presentation_type
     - How the disease presented (e.g., New diagnosis, Recurrence, Metastasis)
   * - Cancer Site
     - cancer_site
     - The anatomical location using Foundational Model of Anatomy (FMA) codes. This can be the site where the cancer was first diagnosed or where it recurred/metastasized
   * - Cancer Side
     - cancer_side
     - The laterality of the cancer (Left, Right, Bilateral)
   * - Diagnostic Modality
     - diagnostic_modality
     - The method used to confirm the diagnosis (e.g., Biopsy, Imaging, Cytology)
   * - Associated DICOM Studies
     - study_instance_uid
     - Any imaging studies related to this diagnosis. Multiple studies can be selected
   * - Project Assignment
     - diagnosis_project
     - CHAVI projects associated with this diagnosis. Multiple projects can be selected

Special Considerations
------------------------

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
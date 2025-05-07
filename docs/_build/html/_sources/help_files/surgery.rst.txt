Surgery
=================

The Surgery module captures information about surgical procedures performed as part of cancer treatment. As the patient can have multiple surgeries for a given diagnosis, this allows the user to record all surgeries. If the patient has multiple surgical procedures at the same time then this can also be recorded in the form in the Surgery Type field which allow users to select multiple types of surgery. 

For example, if the patient undergoes a mastectomy, implant reconstruction and axillary dissection then all these can be recorded in the form in seperate sections. 

We recommend that the user should not record surgeries performed for other diagnoses in the same form. For example, if the the patient has a bilateral breast cancer, then the diagnosis of the left and right breast should be recorded in seperate forms. Surgeries for the same should also be recorded in seperate forms.

.. note::

   Surgeries are linked to a diagnosis and there can be multiple surgeries for a single diagnosis. Diagnosis is in turn linked to a patient ID.

   Surgery -> Diagnosis -> Patient
..
      

Data Collection Fields
-----------------------

.. list-table:: Surgery Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Diagnosis
     - diagnosis
     - The diagnosis this surgery is associated with
   * - Surgery Date
     - surgery_date
     - The date when the surgery was performed (format: DD/MM/YYYY)
   * - Surgery Side
     - surgery_side
     - Which side of the body the surgery was performed on (e.g., Left, Right, Bilateral)
   * - Surgery Type
     - surgery_type
     - The type of surgery performed (e.g., Mastectomy, Lumpectomy, Whole Breast Irradiation). Note that multiple types of surgeries can be selected for a single diagnosis if performed at the same sitting.
   * - Surgery Intent
     - surgery_intent
     - The intent of the surgery (e.g., Curative, Palliative)
   * - Nodal Assessment
     - nodal_assessment
     - Indicates whether nodal assessment was performed (check for Yes, leave unchecked for No)
   * - Nodal Assessment Type
     - nodal_assessment_type
     - The type of nodal assessment performed (e.g., Sentinel Node Biopsy, Axillary Dissection)
   * - Reconstruction
     - reconstruction
     - Indicates whether reconstructive surgery was performed (check for Yes, leave unchecked for No)
   * - Type of Reconstruction
     - type_reconstruction
     - If reconstruction was performed, specifies the type (e.g., Implant-Based, Autologous Tissue, DIEP Flap)
   * - Associated DICOM Studies
     - study_instance_uid
     - The DICOM studies associated with this surgical procedure


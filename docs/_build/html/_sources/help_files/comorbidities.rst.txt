Comorbidities
=====================

The Comorbidities module captures other medical conditions that may affect cancer treatment or outcomes.

.. note::

   Comorbidities are linked to a patient ID.

   Patient -> Comorbidities
..   


Data Collection Fields
------------------------

.. list-table:: Comorbidity Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Patient
     - patient
     - The patient who has this comorbidity
   * - Comorbidity Type
     - comorbidity_type
     - Nature of the medical condition (selected from standardized lookup)
   * - Date of Comorbidity Assessment
     - date_of_comorbidity_assessment
     - Date when this comorbidity was last assessed
   * - Duration of Comorbidity
     - duration_of_comorbidity
     - Duration of the comorbidity in months
   * - Date of Comorbidity Diagnosis
     - date_of_comorbidity_diagnosis
     - When the comorbidity was first diagnosed (automatically calculated based on assessment date and duration)
   * - Comorbidity Resolved
     - comorbidity_resolved
     - Indicates if the comorbidity has been resolved
   * - Medication for Comorbidity
     - medication_for_comorbidity
     - Indicates if the patient is currently taking medication for the comorbidity


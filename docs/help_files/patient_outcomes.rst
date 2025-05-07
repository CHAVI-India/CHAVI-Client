Patient Outcomes
===================

The Patient Outcomes module tracks the overall status and outcomes of patients throughout their cancer journey. This includes their last known status, survival information, and whether any death was related to cancer progression. This is also used to record the patient's last known follow-up date. This can be used to record multiple outcomes for a single patient but it would be best to record one outcome per patient and update the record with new information as it becomes available prospectively.

.. note::

   Patient Outcomes are linked directly to a patient and there can be multiple outcome records for a single patient over time.

   Patient Outcome -> Patient

Data Collection Fields
--------------------------

.. list-table:: Patient Outcome Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Patient
     - patient
     - The patient whose outcome is being recorded
   * - Patient Status
     - patient_status
     - The patient's last known status from standardized list
   * - Date of Death
     - date_of_death
     - The date when the patient died, if applicable (format: DD/MM/YYYY)
   * - Last Date of Follow-up
     - last_date_of_follow_up
     - The date of most recent contact or information (format: DD/MM/YYYY)
   * - Death Related to Cancer Progression
     - death_related_to_cancer_progression
     - Indicates if the death was related to cancer progression (Yes/No)


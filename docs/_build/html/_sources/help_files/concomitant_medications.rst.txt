Concomitant Medications
=============================

The Concomitant Medications module tracks medications given alongside primary cancer treatments. This can be used to track medications like steroids, antiemetics or any other class of supportive medicines. 

.. note::

   Concomitant medications are linked to a diagnosis and there can be multiple concomitant medications for a single diagnosis. Diagnosis is in turn linked to a patient ID.

   Concomitant Medications -> Diagnosis -> Patient

Data Collection Fields
--------------------------

.. list-table:: Concomitant Medications Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Diagnosis
     - diagnosis
     - The diagnosis this medication is associated with
   * - Medication Name
     - medication_name
     - The name of the medication as it appears in the medical record
   * - Medication Dose
     - medication_dose
     - The prescribed dose of the medication (can be left blank if unknown)
   * - Dose Units
     - medication_dose_units
     - The units for the medication dose (e.g., mg, mL, etc.)
   * - Start Date
     - date_medication_start_date
     - The date when the medication was started (format: DD/MM/YYYY)
   * - End Date
     - date_medication_end_date
     - The date when the medication was stopped, if applicable (format: DD/MM/YYYY)
   * - Route
     - medication_route
     - How the medication was administered (e.g., oral, intravenous, etc.)


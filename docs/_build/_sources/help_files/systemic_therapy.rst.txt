Systemic Therapy
==================

The Systemic Therapy module captures information about medication-based cancer treatments. This includes chemotherapy, targeted therapy, immunotherapy, and hormone therapy regimens. Multiple systemic therapy courses can be recorded for a single diagnosis.
To record details of cycles of chemotherapy, please use the Systemic Therapy Drug Schedule module.

.. note::

   Systemic Therapy is linked to a diagnosis and there can be multiple systemic therapy courses for a single diagnosis. Each course can have multiple drug schedules.

   Systemic Therapy -> Diagnosis -> Patient

Data Collection Fields
------------------------

.. list-table:: Systemic Therapy Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Diagnosis
     - diagnosis
     - The diagnosis that this treatment is associated with
   * - Therapy Type
     - systemic_therapy_type
     - The type of systemic therapy
   * - Treatment Intent
     - systemic_therapy_intent
     - The intent of the systemic therapy
   * - Treatment Sequence
     - systemic_therapy_sequence
     - The sequence for the systemic therapy
   * - Treatment Regimen
     - systemic_therapy_regimen
     - The regimen for the systemic therapy
   * - Start Date
     - systemic_therapy_start_date
     - The date when the treatment was started (format: DD/MM/YYYY)
   * - End Date
     - systemic_therapy_end_date
     - The date when the treatment was completed (format: DD/MM/YYYY)
   * - Cycles Delivered
     - cycles_delivered
     - Total number of cycles delivered if applicable

Other Treatment
=================

The Other Treatment module captures information about treatments that don't fall into standard categories like surgery, radiation, or systemic therapy. This includes complementary therapies, experimental treatments, or other non-standard interventions.

.. note::

   Other Treatment is linked to a diagnosis and there can be multiple other treatments for a single diagnosis.

   Other Treatment -> Diagnosis -> Patient

Data Collection Fields
--------------------------

.. list-table:: Other Treatment Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Diagnosis
     - diagnosis
     - The diagnosis that this treatment is associated with
   * - Treatment Intent
     - treatment_intent
     - The intent of the treatment (e.g., curative, palliative)
   * - Treatment
     - treatment
     - The name or description of the treatment
   * - Start Date
     - treatment_start_date
     - The date when the treatment was started (format: DD/MM/YYYY)
   * - End Date
     - treatment_end_date
     - The date when the treatment was completed (format: DD/MM/YYYY)


Cancer Outcomes
==================

The Cancer Outcomes module tracks disease-specific outcomes related to a particular diagnosis. This includes recording the type of outcome, when it was assessed, and any associated imaging studies that confirm the outcome.

.. note::

   Cancer Outcomes are linked to a diagnosis and there can be multiple outcome records for a single diagnosis.

   Cancer Outcome -> Diagnosis -> Patient

Data Collection Fields
-------------------------

.. list-table:: Cancer Outcome Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Diagnosis
     - diagnosis
     - The diagnosis that this outcome is associated with
   * - Date Outcome Assessed
     - date_outcome_assessed
     - The date when this outcome was assessed or documented (format: DD/MM/YYYY)
   * - Outcome Type
     - outcome_type
     - The type of outcome (e.g., Local Recurrence, Nodal Recurrence)
   * - Associated DICOM Studies
     - study_instance_uid
     - The DICOM studies associated with this outcome


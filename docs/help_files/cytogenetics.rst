Cytogenetics
===============================

The Cytogenetics module captures information about genetic alterations detected through cytogenetic testing. This includes chromosomal abnormalities and gene rearrangements that may influence diagnosis, prognosis, and treatment decisions. Multiple cytogenetic test results can be entered for a pathology depending on the data collection requirements.

.. note::

   Cytogenetics is linked to a pathology report and there can be multiple cytogenetic tests for a single pathology report. Pathology is in turn linked to a diagnosis.

   Cytogenetics -> Pathology -> Diagnosis -> Patient

Data Collection Fields
------------------------

.. list-table:: Cytogenetics Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Pathology
     - pathology
     - The pathology report this cytogenetic test is associated with
   * - Date of Test
     - date_cytogenetics
     - The date when the cytogenetic test was performed (format: DD/MM/YYYY)
   * - Gene
     - gene
     - The specific gene tested (from standardized gene list)
   * - Cytogenetic Abnormality
     - cytogenetic_abnormality
     - The specific cytogenetic abnormality if applicable
   * - Cytogenetic Result
     - cytogenetic_result
     - The result of the cytogenetic test (Positive/Negative/Not Evaluable)


Epigenetic Modifications
===============================

The Epigenetic Modifications module captures data about epigenetic changes identified in pathology specimens. This information helps understand regulatory modifications that affect gene expression. Multiple epigenetic test results can be entered for a pathology depending on the data collection requirements.

.. note::

   Epigenetic Modifications are linked to a pathology report and there can be multiple epigenetic tests for a single pathology report. Pathology is in turn linked to a diagnosis.

   Epigenetic Modifications -> Pathology -> Diagnosis -> Patient

Data Collection Fields
------------------------

.. list-table:: Epigenetic Modifications Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Pathology
     - pathology
     - The pathology report this epigenetic data is associated with
   * - Date of Test
     - date_test
     - The date when the epigenetic test was performed (format: DD/MM/YYYY)
   * - Gene
     - gene
     - The gene that was tested for in this epigenetic data
   * - Epigenetic Abnormality Type
     - epigenetic_abnormality_type
     - The type of epigenetic abnormality if applicable
   * - Epigenetic Result
     - epigenetic_result
     - The result of the epigenetic test



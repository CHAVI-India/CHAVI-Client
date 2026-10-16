Stage Information
==========================

The Stage Information module records the cancer staging details for each diagnosis. This information is crucial for determining the extent of disease and treatment planning. Multiple staging records can be maintained for a single diagnosis to track changes over time.

.. note::

   Stage Information is linked to a diagnosis and there can be multiple staging records for a single diagnosis. This allows tracking of stage changes over time.

   Stage Information -> Diagnosis -> Patient

Data Collection Fields
------------------------

.. list-table:: Stage Information Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Diagnosis
     - diagnosis
     - The diagnosis this staging information is associated with
   * - Staging System
     - staging_system
     - The staging system used (e.g., 'TNM 8th Edition', 'FIGO')
   * - Stage Type
     - stage_type
     - The type of staging information
   * - T Stage Prefix
     - t_stage_prefix
     - The prefix modifiers for the T stage (e.g., 'c' for clinical, 'p' for pathological)
   * - T Stage
     - t_stage
     - The T stage describing the primary tumor (e.g., 'T1', 'T2', 'T3', 'T4')
   * - T Stage Suffix
     - t_stage_suffix
     - Any suffix modifiers for the T stage (e.g., 'a', 'b', 'c')
   * - N Stage Prefix
     - n_stage_prefix
     - Any prefix modifiers for the N stage (e.g., 'c' for clinical, 'p' for pathological)
   * - N Stage
     - n_stage
     - The N stage describing lymph node involvement (e.g., 'N0', 'N1', 'N2', 'N3')
   * - N Stage Suffix
     - n_stage_suffix
     - Any suffix modifiers for the N stage (e.g., 'a', 'b', 'c')
   * - M Stage Prefix
     - m_stage_prefix
     - Any prefix modifiers for the M stage (e.g., 'c' for clinical, 'p' for pathological)
   * - M Stage
     - m_stage
     - The M stage describing distant metastasis (e.g., 'M0', 'M1', 'M1a', 'M1b')
   * - M Stage Suffix
     - m_stage_suffix
     - Any suffix modifiers for the M stage (e.g., 'a', 'b', 'c')
   * - Overall Stage
     - overall_stage
     - The overall stage grouping (e.g., 'Stage I', 'Stage II', 'Stage III', 'Stage IV')



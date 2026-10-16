Immunohistochemistry
====================

The Immunohistochemistry (IHC) module captures protein expression data from pathology specimens. This information is crucial for diagnosis, prognosis, and treatment planning.

.. note::

   Immunohistochemistry is linked to a pathology report and there can be multiple immunohistochemistry reports for a single pathology report. Pathology is in turn linked to a diagnosis.

   Immunohistochemistry -> Pathology -> Diagnosis -> Patient

Data Collection Fields
------------------------

.. list-table:: Immunohistochemistry Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Pathology
     - pathology
     - The pathology report this immunohistochemistry test is associated with
   * - Date of IHC
     - date_ihc
     - The date when the immunohistochemistry test was performed (format: DD/MM/YYYY)
   * - Protein Name
     - protein_name
     - The antibody that was tested for in this immunohistochemistry test
   * - IHC Result
     - ihc_result
     - The result of the IHC staining test overall
   * - Percentage Positive Tumor Cells
     - percentage_positive_tumor_cells
     - The percentage of positive cells for IHC staining (0-100%)
   * - Percentage Positive Immune Cells
     - percentage_positive_immune_cells
     - The percentage of positive immune cells for IHC staining (0-100%)
   * - Tumor Cell Staining Intensity
     - tumor_cell_staining_intensity
     - The staining intensity of the cells for IHC staining
   * - Allred Score
     - allred_score
     - The Allred score for IHC staining
   * - CPS Score
     - cps_score
     - Number of Tumor and Immune Cells with Staining per 100 Tumor Cells (CPS)
   * - TPS Score
     - tps_score
     - The Tumor Proportion Score for IHC staining in percentage (0-100%)


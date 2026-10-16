Gene Expression Data
======================

The Gene Expression Data module collects information about gene expression testing performed on pathology specimens. This data helps understand the molecular characteristics of tumors. Multiple gene expression tests can be recorded for a single pathology report.

.. note::

   Gene Expression Data is linked to a pathology report and there can be multiple gene expression tests for a single pathology report. Pathology is in turn linked to a diagnosis.

   Gene Expression Data -> Pathology -> Diagnosis -> Patient

Data Collection Fields
------------------------

.. list-table:: Gene Expression Data Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Pathology
     - pathology
     - The pathology report this gene expression data is associated with
   * - Date of Test
     - date_test
     - The date when the gene expression test was performed (format: DD/MM/YYYY)
   * - Gene
     - gene
     - The gene that was tested for in this gene expression data
   * - Expression Value
     - expression_value
     - The expression value of the gene
   * - Expression Units
     - expression_units
     - The units of expression



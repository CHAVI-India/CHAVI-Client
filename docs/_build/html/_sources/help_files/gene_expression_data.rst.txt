Gene Expression Data
===================

The Gene Expression Data module collects information about gene expression testing performed on pathology specimens. This data helps understand the molecular characteristics of tumors.

Data Collection Fields
--------------------

Test Information
^^^^^^^^^^^^^^
* **Date of Test**: The date when the gene expression test was performed
* **Pathology Reference**: Link to the pathology report this gene expression data is associated with

Gene Expression Details
^^^^^^^^^^^^^^^^^^^^
* **Gene**: The specific gene tested for expression levels, selected from standardized gene list
* **Expression Value**: The quantitative measurement of gene expression
* **Expression Units**: The units used to measure gene expression (e.g., FPKM, TPM, counts)

Special Considerations
--------------------

1. Expression values:

   #. Must be positive numbers
   #. Should be recorded with appropriate precision
   #. Units should be consistent within testing methods

2. Gene selection:

   #. Use standardized gene names from the lookup list
   #. Multiple genes can be tested from the same specimen
   #. Document any specific testing platform or methodology used

3. Data quality:

   #. Ensure values are properly normalized if required
   #. Document any quality control metrics if available
   #. Note any technical limitations or concerns

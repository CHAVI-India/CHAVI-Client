Somatic Genomic Alterations
==========================

The Somatic Genomic Alterations module captures detailed information about genetic changes found in tumor tissue. This data is crucial for understanding tumor biology, determining prognosis, and selecting targeted therapies.

Data Collection Fields
--------------------

Test Information
^^^^^^^^^^^^^
* **Pathology Link**: The pathology report this genomic testing is associated with
* **Date of Test**: When the genomic testing was performed
* **Gene Name**: The specific gene analyzed (using COSMIC gene names)

Variant Details
^^^^^^^^^^^^
* **Reference Sequence**: Standard sequence identifier (e.g., NM_007294.3)
* **Protein Modification**: Description of protein-level change
* **Variant Type**: Classification of the genetic change (e.g., Missense, Frameshift)

Technical Information
^^^^^^^^^^^^^^^^^
* **Allele Frequency**: Percentage of DNA reads showing the variant (0-100%)
* **Read Depth**: Number of sequencing reads at the variant position
* **Clinical Significance**: Interpretation of the variant's clinical impact

Special Considerations
--------------------

1. Variant Documentation:

   #. Use standard nomenclature for variants  
   #. Record accurate allele frequencies  
   #. Note read depth for quality assessment  

2. Gene Information:

   #. Use official COSMIC gene names  
   #. Include complete reference sequences  
   #. Document all detected variants  

3. Clinical Interpretation:

   #. Record clinical significance  
   #. Document evidence level  
   #. Note any treatment implications 
Germline Genomic Alterations
=============================

The Germline Genomic Alterations module records information about inherited genetic mutations that may affect cancer risk, treatment response, or prognosis.

.. note::

   Patient assessments are done for a patient and hence they are linked to the Patient ID.

   Patient -> Germline Genomic Alterations
..   

Data Collection Fields
------------------------

.. list-table:: Germline Genomic Alterations Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Patient
     - patient
     - The patient for whom the genetic testing was performed
   * - Date Test
     - date_test
     - Date when the germline genetic testing was performed
   * - Cosmic Gene Name
     - cosmic_gene_name
     - The gene where the alteration was found, using COSMIC database nomenclature
   * - Reference Sequence
     - reference_sequence
     - The reference sequence identifier (e.g., 'NM_007294.3' for BRCA1)
   * - Protein Modification
     - protein_modification
     - The protein-level change using standard nomenclature (e.g., 'p.Val600Glu' for BRAF V600E mutation)
   * - Variant Type
     - variant_type
     - Type of variant (e.g., 'Missense', 'Frameshift', 'Deletion', 'Insertion')
   * - Allele Frequency
     - allele_frequency
     - The variant allele frequency as a decimal (e.g., 0.45 for 45%)
   * - Read Depth
     - read_depth
     - The sequencing read depth at this position
   * - Clinical Significance
     - clinical_significance
     - The clinical significance of the variant (e.g., 'Pathogenic', 'Likely Pathogenic', 'Benign', 'Variant of Unknown Significance')

Somatic Genomic Alterations
==============================

The Somatic Genomic Alterations module captures detailed information about genetic changes found in tumor tissue. This data is crucial for understanding tumor biology, determining prognosis, and selecting targeted therapies. Multiple genomic alterations can be recorded for a single pathology report.

.. note::

   Somatic Genomic Alterations are linked to a pathology report and there can be multiple genomic alterations for a single pathology report. Pathology is in turn linked to a diagnosis.

   Somatic Genomic Alterations -> Pathology -> Diagnosis -> Patient

Data Collection Fields
------------------------

.. list-table:: Somatic Genomic Alterations Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Pathology
     - pathology
     - The pathology report this genomic alteration is associated with
   * - Date of Test
     - date_test
     - The date when the genomic testing was performed (format: DD/MM/YYYY)
   * - Gene Name
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
     - The type of variant (e.g., 'Missense', 'Frameshift', 'Deletion', 'Insertion')
   * - Allele Frequency
     - allele_frequency
     - The variant allele frequency as a decimal (e.g., 0.45 for 45%)
   * - Read Depth
     - read_depth
     - The sequencing read depth at this position (e.g., 500)
   * - Clinical Significance
     - clinical_significance
     - The clinical significance of the variant


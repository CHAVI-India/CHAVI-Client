.. CHAVI Client documentation master file, created by
   sphinx-quickstart on Sat Feb  8 08:36:38 2025.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to CHAVI Client Documentation
=========================================
The CHAVI Client is a web application that allows you to enter clinical data for patients to be enrolled in the CHAVI databank. The system allows entry of clinical data and linkage to DICOM and Project information. This information is then deidentified and uploaded into the CHAVI databank.

This documentation is intended to provide a guide to the CHAVI Client and the data that can be entered into the system. You will find information on the different forms available for entering the data in the application.

Please note that the organization of the data may be different from the usual way clinical data is captured for projects. For example, there is a key form called Diagnosis which may be implicit in your clinical data collection forms. For example, if you are collecting data for patients with breast cancer, the diagnosis may not be recorded in your case record forms simply because the diagnosis is assumed to be breast cancer. In case of the CHAVI client however for each patient we need to ensure that the diagnosis of Breast cancer is recorded. 



.. toctree::
   :maxdepth: 2
   :caption: Getting started

   help_files/about
   help_files/installation
   help_files/docker_installation
   help_files/configuration
   help_files/tfa
   help_files/getting_around

.. toctree::
   :maxdepth: 2
   :caption: Entering patient data

   help_files/example_data_entry_scenarios
   help_files/suggested_data_entry_flow
   help_files/patient_demographics
   help_files/diagnosis
   help_files/lesion
   help_files/lesion_response
   help_files/pathology
   help_files/immunohistochemistry
   help_files/cytogenetics
   help_files/somatic_genomic_alterations
   help_files/germline_mutation_data
   help_files/adverse_effects
   help_files/systemic_therapy
   help_files/systemic_therapy_drug_schedule
   help_files/radiation_therapy
   help_files/radiation_volume
   help_files/radiation_dose_volume
   help_files/surgery
   help_files/concomitant_medications
   help_files/other_treatment
   help_files/cancer_outcomes
   help_files/laboratory_results
   help_files/symptoms
   help_files/stage_information
   help_files/comorbidities
   help_files/patient_outcomes
   help_files/patient_reported_outcomes
   help_files/dicom_study
   help_files/epigenetic_modifications
   help_files/gene_expression_data
   help_files/patient_assessment

.. toctree::
   :maxdepth: 2
   :caption: Bringing data in

   help_files/csv_import_wizard
   help_files/import_data
   help_files/clinical_data_import
   help_files/handling_dicom_data
   help_files/dicom_data_import
   help_files/dicom_retrieval
   help_files/automatic_data_extraction
   help_files/lookup_data
   help_files/lookup_tables

.. toctree::
   :maxdepth: 2
   :caption: For administrators

   help_files/dicom_server_setup
   help_files/deidentification
   help_files/legacy_mapping_import
   help_files/extraction_setup
   help_files/database_backup

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

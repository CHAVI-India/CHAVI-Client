Symptoms
==========

The Symptoms module records patient symptoms throughout their disease course and treatment.

.. note::

   Symptoms are linked to a patient ID.

   Symptoms -> Patient
..   

Data Collection Fields
------------------------

.. list-table:: Symptom Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Patient
     - patient
     - The patient experiencing symptoms
   * - Symptom
     - symptom
     - Type of symptom (from standardized list). This list is taken from the symptom ontology available at https://bioportal.bioontology.org/ontologies/SYMP
   * - Severity
     - severity
     - Level of symptom severity
   * - Date Symptom Assessment
     - date_symptom_assessment
     - Date when the symptom was assessed
   * - Duration of Symptom
     - duration_of_symptom
     - Duration of the symptom. Should be provided in months
   * - Date Resolution
     - date_resolution
     - When symptom resolved (if applicable). Leave blank if the symptom is still present
   * - Date Onset
     - date_onset
     - When the symptom first appeared. This will be automatically calculated from the date of the Symptom Assessment and the Duration of Symptom



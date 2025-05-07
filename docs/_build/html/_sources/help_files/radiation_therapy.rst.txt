Radiation Therapy
====================

The Radiation Therapy module captures information about radiation treatment courses. This includes details about treatment planning, delivery, and monitoring of radiation therapy courses. Multiple radiation therapy courses can be recorded for a single diagnosis. For each course, separate forms are provided to record the volumes where the treatment was delivered and the dose volume data obtained from DVH if it is desired to be stored. 

.. note::

   Radiation Therapy is linked to a diagnosis and there can be multiple radiation therapy courses for a single diagnosis. Each course can have multiple volumes and dose volume data.

   Radiation Therapy -> Diagnosis -> Patient
..

.. note::

   The Radiation Therapy module is linked to the Radiation Volume module and the Dose Volume Data module.

   Radiation Volume -> Radiation Therapy -> Diagnosis -> Patient  
   
   Dose Volume Data -> Radiation Therapy -> Diagnosis -> Patient

..

Data Collection Fields
------------------------

.. list-table:: Radiation Therapy Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Diagnosis
     - diagnosis
     - The diagnosis that this treatment is associated with
   * - Course Type
     - radiotherapy_course_type
     - The type of radiotherapy course (Primary or Boost)
   * - Modality
     - radiotherapy_modality
     - The modality of the radiotherapy
   * - Reirradiation
     - reirradiation
     - Indicate if this is a reirradiation course
   * - Total Dose
     - total_dose
     - The total radiation dose delivered during the entire course of treatment
   * - Total Fractions
     - total_fractions
     - The total number of fractions delivered for the complete course
   * - Simultaneous Integrated Boost
     - simultaneous_integrated_boost
     - Indicate if this course had a simultaneous integrated boost
   * - Boost Dose
     - simultaneous_integrated_boost_dose
     - The dose of the simultaneous integrated boost
   * - Radiation Dose Units
     - radiation_dose_units
     - The units used to measure the radiation dose (e.g., 'Gy', 'cGy')
   * - Treatment Intent
     - radiotherapy_intent
     - The intent of the radiotherapy treatment (e.g., 'Curative', 'Palliative')
   * - Treatment Type
     - radiotherapy_type
     - The type of radiotherapy treatment
   * - Treatment Technique
     - radiotherapy_technique
     - The technique used to deliver the radiation
   * - Fractions per Day
     - fractions_per_day
     - The number of treatment sessions delivered per day
   * - Treatment Side
     - radiotherapy_side
     - Which side of the body is being treated
   * - Treatment Machine
     - radiotherapy_machine
     - The name or model of the radiation therapy machine used
   * - Start Date
     - radiotherapy_start_date
     - The date when the treatment was started (format: DD/MM/YYYY)
   * - End Date
     - radiotherapy_end_date
     - The date when the treatment was completed (format: DD/MM/YYYY)



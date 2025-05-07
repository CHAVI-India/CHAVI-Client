Radiation Volume
===================

The Radiation Volume module captures information about specific anatomical volumes targeted during radiation therapy. Each radiation course can have multiple volumes which were treated. This allows for recording heterogenous dose prescriptions like sequential boost, simultaneous boost etc. Addtionally brachytherapy volumes can be recorded. 

.. note::

   Radiation Volume is linked to a radiation course and there can be multiple volumes for a single course.

   Radiation Volume -> Radiation Therapy -> Diagnosis -> Patient

Data Collection Fields
------------------------

.. list-table:: Radiation Therapy Volume Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Volume Name
     - volume_name
     - A name or description for this volume
   * - Volume Type
     - volume_type
     - The type of volume (e.g., PTV, CTV, OAR)
   * - Prescribed Dose
     - volume_dose_prescribed
     - The prescribed dose for this volume
   * - Volume Fractions
     - volume_fractions
     - The number of fractions for this volume
   * - Volume Start Date
     - volume_radiotherapy_start_date
     - The start date for this volume (format: DD/MM/YYYY)
   * - Volume End Date
     - volume_radiotherapy_end_date
     - The end date for this volume (format: DD/MM/YYYY)
   * - Anatomical Locations
     - anatomical_locations
     - The anatomical locations included in this volume
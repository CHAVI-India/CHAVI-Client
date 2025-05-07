Radiation Dose Volume Data
=============================

The Radiation Dose Volume Data module records detailed dosimetric information for radiation treatment volumes. This data is typically obtained from the dose volume histogram data  of the radiotherapy plan. 

.. note::

   The Radiation Dose Volume Data module is linked to a radiation volume and there can be multiple dose volume data for a single volume.

   Radiation Dose Volume Data -> Radiation Volume -> Radiation Therapy -> Diagnosis -> Patient

.. note::

   It would be very tedious to enter this data manually. It would be best to import this data from a CSV file.


Note that as multiple anatomical locations may be included in a single volume, please select as many anatomical locations as are required for the volume. 

Data Collection Fields
-------------------------

.. list-table:: Radiation Therapy Dose Volume Data Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Volume Name
     - volume_name
     - A name for this dose volume data
   * - Volume Type
     - volume_type
     - The type of volume (e.g., 'CTV', 'PTV')
   * - Absolute Volume
     - absolute_volume
     - The absolute volume in cubic centimeters (cc)
   * - Relative Volume
     - relative_volume
     - The relative volume as a percentage (%)
   * - Volume Units
     - volume_units
     - The units for the volume (e.g., 'cc', '%')
   * - Absolute Dose
     - absolute_dose
     - The absolute dose in Gray (Gy) or cGy
   * - Relative Dose
     - relative_dose
     - The relative dose as a percentage (%)
   * - Prescribed Dose
     - volume_dose_prescribed
     - The dose prescribed to this volume
   * - Dose Units
     - radiation_dose_units
     - The units for the dose (e.g., 'Gy', 'cGy', '%')
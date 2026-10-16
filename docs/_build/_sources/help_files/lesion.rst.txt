Lesion Characteristics
==========================

The Lesion module tracks information about individual tumors or disease sites associated with a diagnosis. This module allows detailed documentation of each lesion's characteristics and their changes over time. This form is meant to collect data about lesions visualized various imaging modalities. Addtionally it allows the user to record the imaging dataset which is related to the detection of the lesion. Patients can have one or multiple lesions and if needed each lesion data can be recorded separately.


.. note::

    Lesions are linked to a diagnosis and there can be multiple lesions for a single diagnosis. Diagnosis is in turn linked to a patient. 

    Patient -> Diagnosis -> Lesion
..   


Data Collection Fields
-------------------------

.. list-table:: Lesion Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Diagnosis
     - diagnosis
     - The diagnosis this lesion is associated with
   * - Date Lesion Assessed
     - date_lesion_assessed
     - The date when this lesion was first identified or assessed by a medical professional
   * - Lesion Site
     - lesion_site
     - The anatomical location where the lesion is found (e.g., "Left Breast", "Right Lung")
   * - Lesion Type
     - lesion_type
     - The type or category of the lesion (e.g., "Primary Tumor", "Metastatic Lesion")
   * - Lesion Laterality
     - lesion_laterality
     - Indicates which side of the body the lesion is on (e.g., "Left", "Right", "Bilateral")
   * - Lesion Size X-Axis
     - lesion_size_x_axis
     - First dimension of the lesion as reported (when a report gives 'a × b × c' or 'L × W × H', take the first value). In the unit from the Lesion Size Unit field (usually mm). Blank if no size given.
   * - Lesion Size Y-Axis
     - lesion_size_y_axis
     - Second reported dimension (middle value of 'a × b × c'). Blank if the report gives fewer than two dimensions.
   * - Lesion Size Z-Axis
     - lesion_size_z_axis
     - Third reported dimension (last value of 'a × b × c'). Blank if not reported.
   * - Lesion Size Unit
     - lesion_size_unit
     - Unit of the three size fields (mm, cm). Reports usually use mm.
   * - Lesion Volume
     - lesion_volume
     - Volume of the lesion if stated in the report (e.g. 'volume 12.3 cc'). In the unit from the Lesion Volume Unit field. Blank if not stated.
   * - Lesion Volume Unit
     - lesion_volume_unit
     - Unit of the lesion volume (e.g. mm³, cm³/cc).
   * - Lesion Detection Modality
     - lesion_detection_modality
     - The imaging modality used to detect the lesion (e.g., "CT", "MRI", "PET", "US")
   * - Lesion SUV Max
     - lesion_suv_max
     - The maximum Standardized Uptake Value (SUV) of the lesion (for PET scans)
   * - Associated DICOM Studies
     - study_instance_uid
     - Imaging studies showing this lesion



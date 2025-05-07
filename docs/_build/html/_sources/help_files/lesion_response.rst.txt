Lesion Response
==================

The Lesion Response module tracks changes in lesions over time in response to treatment. These are linked to specific lesion. Multiple lesion response assessments  can be done for each lesion. The modality of assessment for the response can be selected in the modality. If the lesion has been assessed for response using multiple modalities at the same time, then it can also be recorded as a seperate instance - in this case the modality and the date help in understanding the sequence of assessments. 

The form also allows users to associate DICOM studies which were used for the response assessment. 

Note that lesion response is not meant for recording response noted using other modalities like serum tumor markers. These assessments should be recorded in the Laboratory Assesments form. 

.. note::

   Lesion response assessments are done for a lesion and hence they are linked to the Lesion ID. Note the Lesion is itself linked to pathology which in turn is linked to a diagnosis and the diagnosis is further linked to a patient. 

   Patient -> Diagnosis -> Pathology -> Lesion -> Lesion Response
..   




Data Collection Fields
------------------------

.. list-table:: Lesion Response Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Lesion
     - lesion
     - The specific lesion (abnormal tissue) that is being monitored for response to treatment
   * - Lesion Response Date
     - lesion_response_date
     - The date when the lesion's response to treatment was evaluated
   * - Lesion Response
     - lesion_response
     - How the lesion has responded to treatment (e.g., Complete Response, Partial Response, Stable Disease, Progressive Disease)
   * - Residual Lesion Size X-Axis
     - residual_lesion_size_x_axis
     - The width (left to right measurement) of any remaining lesion after treatment
   * - Residual Lesion Size Y-Axis
     - residual_lesion_size_y_axis
     - The length (front to back measurement) of any remaining lesion after treatment
   * - Residual Lesion Size Z-Axis
     - residual_lesion_size_z_axis
     - The height (top to bottom measurement) of any remaining lesion after treatment
   * - Residual Lesion Size Unit
     - residual_lesion_size_unit
     - The unit of measurement used for the residual lesion size
   * - Residual Lesion Volume
     - residual_lesion_volume
     - The total volume (size in three dimensions) of any remaining lesion after treatment
   * - Residual Lesion Volume Unit
     - residual_lesion_volume_unit
     - The unit of measurement used for the residual lesion volume
   * - Lesion Response SUV Max
     - lesion_response_suv_max
     - The maximum SUV value of the lesion after treatment
   * - Lesion Response Modality
     - lesion_response_modality
     - The imaging modality used to evaluate the lesion's response
   * - Associated DICOM Studies
     - study_instance_uid
     - The DICOM study associated with the lesion response

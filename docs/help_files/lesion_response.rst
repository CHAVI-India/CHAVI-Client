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
     - The date when the lesion's response to treatment was evaluated. (DD/MM/YYYY)
   * - Lesion Response
     - lesion_response
     - Response category at this assessment (e.g. complete response, partial response, stable disease, progression).
   * - Residual Lesion Size X-Axis
     - residual_lesion_size_x_axis
     - First dimension of the REMAINING disease at this assessment (first value of 'a × b × c'). In the unit from the Residual Lesion Size Unit field. Blank if no residual disease or no size given.
   * - Residual Lesion Size Y-Axis
     - residual_lesion_size_y_axis
     - Second dimension of the remaining disease at this assessment (middle value of 'a × b × c'). In the unit from the Residual Lesion Size Unit field. Blank if the report gives fewer than two dimensions.
   * - Residual Lesion Size Z-Axis
     - residual_lesion_size_z_axis
     - Third dimension of the remaining disease at this assessment (last value of 'a × b × c'). In the unit from the Residual Lesion Size Unit field. Blank if not reported.
   * - Residual Lesion Size Unit
     - residual_lesion_size_unit
     - The unit of measurement used for the residual lesion size
   * - Residual Lesion Volume
     - residual_lesion_volume
     - Volume of remaining disease at this assessment, in the unit from the Residual Lesion Volume Unit field. Blank if none.
   * - Residual Lesion Volume Unit
     - residual_lesion_volume_unit
     - Unit of the residual volume (mm³, cm³/cc).
   * - Lesion Response SUV Max
     - lesion_response_suv_max
     - The maximum SUV value of the lesion after treatment
   * - Lesion Response Modality
     - lesion_response_modality
     - The imaging modality used to evaluate the lesion's response
   * - Associated DICOM Studies
     - study_instance_uid
     - The DICOM study associated with the lesion response

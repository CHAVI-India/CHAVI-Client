Patient Assessment
=====================

The Patient Assessment module records physical measurements and clinical assessments of patients during their care. This information helps track patient status and condition over time.

.. note::

   Patient assessments are done for a patient and hence they are linked to the Patient ID.

   Patient -> Patient Assessment
..    




Data Collection Fields
------------------------

.. list-table:: Patient Assessment Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Patient
     - patient
     - The patient for whom the assessment was performed
   * - Date Assessment
     - date_assessment
     - Date when the assessment was performed
   * - Height
     - height
     - Patient's height in centimeters
   * - Weight
     - weight
     - Patient's weight in kilograms
   * - Systolic Blood Pressure
     - systolic_blood_pressure
     - Systolic blood pressure in millimeters of mercury (mmHg)
   * - Diastolic Blood Pressure
     - diastolic_blood_pressure
     - Diastolic blood pressure in millimeters of mercury (mmHg)
   * - Temperature
     - temperature
     - Body temperature in degrees Celsius
   * - Pulse
     - pulse
     - Heart rate in beats per minute
   * - Respiratory Rate
     - respiratory_rate
     - Breathing rate in breaths per minute
   * - Performance Status
     - performance_status
     - Patient's functional status using standardized scales. This is a lookup field from the LookupPerformanceStatus table with both ECOG and Karnofsky Performance Status options.


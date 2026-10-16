Laboratory Results
=====================

The Laboratory Results module tracks various clinical laboratory test results for patients throughout their treatment course.

.. note::

   Laboratory results are done for a patient and hence they are linked to the Patient ID.

   Patient -> Laboratory Results
..   

Data Collection Fields
------------------------

.. list-table:: Laboratory Results Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Patient
     - patient
     - The patient for whom the laboratory result was obtained
   * - Laboratory Test
     - laboratory_test
     - Type of test performed (from standardized list). This is a lookup field derived from the LOINC data of chemistry, hematology and microbiology tests
   * - Result Date
     - result_date
     - Date when the test was performed
   * - Quantitative Result Value
     - quantitative_result_value
     - Numerical test result if applicable
   * - Quantitative Result Unit
     - quantitative_result_unit
     - Units of measurement for the quantitative result
   * - Qualitative Result Value
     - qualitative_laboratory_result
     - Qualitative test result if applicable (e.g., Positive, Negative, Present, Absent, etc.)


Lesion
======

The Lesion module tracks information about individual tumors or disease sites associated with a diagnosis. This module allows detailed documentation of each lesion's characteristics and their changes over time.

Data Collection Fields
--------------------

Lesion Identification
^^^^^^^^^^^^^^^^^^^
* **Diagnosis Link**: The diagnosis this lesion is associated with
* **Date Assessed**: When the lesion was identified or measured
* **Lesion Type**: Classification of the lesion (e.g., Local, Nodal, Distant)

Anatomical Location
^^^^^^^^^^^^^^^^^
* **Lesion Site**: The specific anatomical location using FMA codes
* **Lesion Laterality**: Which side of the body (Left, Right, Bilateral)

Measurement Information
^^^^^^^^^^^^^^^^^^^^
* **Size Measurements**:
    * X-axis (width)
    * Y-axis (length)
    * Z-axis (depth)
    * Units of measurement (mm, cm)
* **Volume**:
    * Total volume measurement
    * Volume units (cc, ml)

Imaging Documentation
^^^^^^^^^^^^^^^^^^
* **Associated DICOM Studies**: Imaging studies showing this lesion

Lesion Response
^^^^^^^^^^^^^
* **Response Type**: How the lesion has responded to treatment
    * Complete Response
    * Partial Response
    * Stable Disease
    * Progressive Disease
* **Response Date**: When the response was assessed
* **Residual Measurements**: 
    * Size measurements after treatment
    * Volume measurements after treatment

Special Considerations
--------------------

1. Measurement Standards:
   * Use consistent measurement techniques
   * Record measurements in standard units
   * Document the imaging modality used for measurements

2. Multiple Timepoints:
   * Track lesion changes over time
   * Link measurements to specific imaging studies
   * Document response to treatments

3. Response Assessment:
   * Follow standard response criteria
   * Include all required measurements
   * Document the basis for response classification

4. Documentation Requirements:
   * Each lesion should be uniquely identifiable
   * Track the same lesion consistently across time points
   * Link lesions to appropriate treatment responses 
Radiation Therapy
===============

The Radiation Therapy module captures information about radiation treatments. This includes details about treatment planning, delivery, and monitoring of radiation therapy courses.

Data Collection Fields
--------------------

Course Information
^^^^^^^^^^^^^^^
* **Diagnosis Link**: The diagnosis this treatment is associated with
* **Course Type**: Primary or Boost treatment
* **Modality**: Type of radiation therapy (e.g., External Beam, Brachytherapy)
* **Reirradiation**: Whether this is a repeat treatment to a previously irradiated area

Treatment Details
^^^^^^^^^^^^^
* **Total Dose**: Total radiation dose for the course
* **Total Fractions**: Number of treatment sessions
* **Dose Units**: Units for radiation measurement
* **Fractions per Day**: Number of daily treatments
* **Treatment Side**: Laterality of treatment

Technical Information
^^^^^^^^^^^^^^^^^
* **Type**: Treatment type (e.g., Definitive, Palliative)
* **Technique**: Delivery method (e.g., IMRT, VMAT)
* **Machine**: Treatment delivery system
* **Timeline**:
    * Start date
    * End date
* **Associated DICOM Studies**: Related imaging studies

Volume Information
^^^^^^^^^^^^^^^
* **Volume Details**:
    * Volume name
    * Volume type (e.g., PTV, CTV, OAR)
    * Prescribed dose
    * Number of fractions
    * Anatomical locations
* **Dose Volume Data**:
    * Volume measurements
    * Dose measurements
    * Relative and absolute values

Special Considerations
--------------------

1. Treatment Planning:

   #. Record all treated volumes  
   #. Document dose constraints  
   #. Track treatment completion  

2. Course Tracking:

   #. Note any treatment breaks  
   #. Document dose modifications  
   #. Record treatment completion status 
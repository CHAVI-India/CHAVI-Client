Pathology
=========

The Pathology module captures detailed information from pathological examination of tissue specimens. This includes histological characteristics, tumor measurements, and various pathological features that help determine diagnosis, staging, and treatment planning.

Data Collection Fields
--------------------

Specimen Information
^^^^^^^^^^^^^^^^^
* **Diagnosis Link**: The diagnosis this pathology report is associated with
* **Date of Pathology**: When the specimen was collected or report issued
* **Specimen Type**: Type of specimen (e.g., Core Biopsy, Surgical Resection, Fine Needle Aspiration)

Tumor Characteristics
^^^^^^^^^^^^^^^^^^
* **Tumor Site**: Anatomical location using FMA codes
* **Tumor Side**: Laterality (Left, Right, Bilateral)
* **Histological Type**: Primary classification of the tumor
* **Histological Grade**: Degree of differentiation
* **Tumor Measurements**:
    * Greatest dimension
    * Additional dimensions
    * Measurement units
* **Tumor Focality**: Whether unifocal or multifocal

Pathological Features
^^^^^^^^^^^^^^^^^^
* **Lymphatic/Vascular Invasion**: Present/Absent/Not Reported
* **Perineural Invasion**: Present/Absent/Not Reported
* **Dermal Lymphatic Invasion**: Present/Absent/Not Reported
* **Necrosis**: 
    * Present/Absent/Not Reported
    * Percentage if present
* **Mitotic Count**: Number per 10 high power fields

Surgical Margins
^^^^^^^^^^^^^
* **Margin Status**: Positive/Negative/Close
* **Closest Margin Distance**: Distance to nearest margin
* **Distance Units**: Units of measurement

Treatment Effect
^^^^^^^^^^^^^
* **Treatment Response**: Degree of response to prior therapy
* **Gleason Scores** (if applicable):
    * Primary grade
    * Secondary grade

Lymph Node Assessment
^^^^^^^^^^^^^^^^^^
* **Nodes Examined**: Total number of lymph nodes in specimen
* **Node Status**:
    * Number of uninvolved nodes
    * Number with macrometastases
    * Number with micrometastases
    * Number with isolated tumor cells

Special Considerations
--------------------

1. Specimen Handling:

   #. Document specimen type accurately  
   #. Note any limitations in specimen quality  

2. Measurements:

   #. Use standard units consistently  
   #. Record all dimensions when available  

3. Lymph Node Assessment:

   #. Document total nodes examined  
   #. Classify metastases appropriately  
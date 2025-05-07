Pathology
=================

The Pathology module captures detailed information from pathological examination of tissue specimens. This includes histological characteristics, tumor measurements, and various pathological features that help determine diagnosis, staging, and treatment planning.

As the pathology form can collect report from various types of specimen, all fields except the tumor site and tumor side are optional. Fields have been arranged in tabs inside the form to ensure that the user can enter the data easily. 

.. note::

   Pathology is linked to a diagnosis and there can be multiple pathologies for a single diagnosis. Diagnosis is in turn linked to a patient ID.

   Pathology -> Diagnosis -> Patient
..   

.. note::

   The immunohistochemistry, cytogenetics, gene expression and somatic genomic alterations modules are linked to the pathology report and are available as tabs in the pathology form. This allows the data to be easily linked to the main pathology. You can enter multiple data for these related tables.

   Immunohistochemistry -> Pathology -> Diagnosis -> Patient
   Cytogenetics -> Pathology -> Diagnosis -> Patient
   Gene Expression -> Pathology -> Diagnosis -> Patient
   Somatic Genomic Alterations -> Pathology -> Diagnosis -> Patient
..   

Data Collection Fields
-----------------------

.. list-table:: Pathology Fields
   :header-rows: 1
   :widths: auto

   * - Form Field Name
     - Database Field Name
     - Description
   * - Diagnosis
     - diagnosis
     - The diagnosis this pathology report is associated with
   * - Date of Pathology
     - date_pathology
     - The date when the pathology specimen was collected or the pathology report was issued
   * - Specimen Type
     - specimen_type
     - Type of specimen (e.g., Core Biopsy, Surgical Resection, Fine Needle Aspiration, Excision Biopsy)
   * - Tumor Site
     - tumor_site
     - Anatomical location of the tumor as defined by the Foundational Model of Anatomy (FMA)
   * - Tumor Side
     - tumor_side
     - The side of the body where the tumor is located (e.g., Left, Right, Bilateral)
   * - Histological Type
     - histological_type
     - Primary histological classification of the tumor (e.g., Adenocarcinoma, Squamous Cell Carcinoma)
   * - Histological Grade
     - histological_grade
     - Degree of differentiation of the tumor cells (e.g., Grade 1, Grade 2, Grade 3)
   * - Greatest Dimension of Tumor
     - greatest_dimension_of_tumor
     - The primary dimension of the tumor measured in the specified units
   * - Additional Tumor Dimension 1
     - additional_tumor_dimension_1
     - The second dimension of the tumor measured in the specified units
   * - Additional Tumor Dimension 2
     - additional_tumor_dimension_2
     - The third dimension of the tumor measured in the specified units
   * - Tumor Dimension Unit
     - tumor_dimesion_unit
     - Unit of measurement for the tumor dimensions
   * - Tumor Focality
     - tumor_focality
     - Whether the tumor is unifocal (single focus), multifocal (multiple foci), or multicentric
   * - Lymphatic/Vascular Invasion
     - lymphatic_vascular_invasion
     - Presence or absence of lymphatic/vascular invasion (Present/Absent/Not Reported)
   * - Perineural Invasion
     - perineural_invasion
     - Presence or absence of perineural invasion (Present/Absent/Not Reported)
   * - Dermal Lymphatic Invasion
     - dermal_lymphatic_vascular_invasion
     - Presence or absence of dermal lymphatic invasion (Present/Absent/Not Reported)
   * - Necrosis
     - necrosis
     - Presence or absence of necrosis (Present/Absent/Not Reported)
   * - Necrosis Percentage
     - necrosis_percentage
     - Percentage of necrosis in the specimen (0-100%)
   * - Mitotic Count
     - mitotic_count
     - Number of mitoses per 10 high power field or 2 square mm
   * - Margin Status
     - margin_status
     - Status of the surgical margins (Positive/Negative/Close)
   * - Closest Margin Distance
     - closest_margin_distance
     - Distance to the closest margin of the specimen
   * - Closest Margin Distance Unit
     - closest_margin_distance_unit
     - Unit of measurement for the closest margin distance
   * - Treatment Effect
     - treatment_effect
     - Degree of response to prior therapy
   * - Primary Gleason Grade
     - primary_gleason_grade
     - Primary Gleason grade of the specimen (for prostate cancer)
   * - Secondary Gleason Grade
     - secondary_gleason_grade
     - Secondary Gleason grade of the specimen (for prostate cancer)
   * - Lymph Nodes Removed
     - lymph_nodes_removed
     - Whether lymph nodes were removed in the specimen
   * - Lymph Nodes in Specimen
     - lymph_nodes_in_specimen
     - Total number of lymph nodes found in the specimen
   * - Lymph Node Extracapsular Extension
     - lymph_node_extracapsular_extension
     - Whether the lymph node had extracapsular extension
   * - Number of Uninvolved Nodes
     - number_of_uninvolved_nodes
     - Number of lymph nodes without any tumor involvement
   * - Number of Nodes with Macrometastases
     - number_of_nodes_with_macrometastases
     - Number of lymph nodes with visible tumor deposits
   * - Number of Nodes with Micrometastases
     - number_of_nodes_with_micrometastases
     - Number of lymph nodes with microscopic tumor deposits (0.2-2.0mm)
   * - Number of Nodes with Isolated Tumor Cells
     - number_of_nodes_with_isolated_tumor_cells
     - Number of lymph nodes with isolated tumor cells (<0.2mm)
   * - Number of Nodes with Extracapsular Extension
     - number_of_nodes_with_extracapsular_extension
     - Number of lymph nodes with extracapsular extension

Special Considerations
------------------------

The following tabs are available in the pathology form:

* **Pathological Features** : This section has fields liuke lymphatic vascular invasion, perineural invasion, dermal lymphatic vascular invasion, necrosis, necrosis percentage and mitotic count. It is expected that these will be available in the specimen has been resected.
* **Tumor Size** : This section, has fields like greatest dimension of the tumor, additional tumor dimension 1, additional tumor dimension 2, tumor dimension unit, and tumor focality. Like the other sections, it is expected that these will be available in the specimen has been resected.
* **Margin & Margin Status**: This section has fields like margin status, closest margin distance and closest margin distance unit. This will be applicable to the specimen has been resected.
* **Treatment Effect**: This section has a single field called treatment effect. This will be applicable to the specimen has been resected after some neoadjuvant therapy.
* **Gleason Grade**: This section is applicable for prostate cancers only and will have fields for primary and secondary gleason grade.
* **Nodes**: This section will have fields for lymph nodes removed, lymph nodes in specimen, lymph node extracapsular extension, number of uninvolved nodes, number of nodes with macrometastases, number of nodes with micrometastases, number of nodes with isolated tumor cells and number of nodes with extracapsular extension. This data will be available if nodes have been resected.





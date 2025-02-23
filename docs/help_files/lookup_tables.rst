Lookup Tables in CHAVI client
===================================================================

The CHAVI client uses a number of lookup tables to store information that is used across multiple models. These lookup tables are used to ensure consistency and to reduce the amount of data that needs to be stored in the database. The lookup tables are also used to provide a standard set of options for users to select from when entering data.

The following are the sources for the major lookup tables:

Symptoms
---------------------
This table is derived from the Symptom Ontology available at https://bioportal.bioontology.org/ontologies/SYMP

Anatomical Sites
---------------------
This table is derived from the ICD-0-3.1 Topography ontology. This is available at https://data.bioontology.org/ontologies/OCD-O-3_TOPO/download?apikey=8b5b7825-538d-40e0-9e9e-5ab9274a9aeb&download_format=csv 

Histology Types
---------------------
This table is derived from the ICD-11 Histology types. The codes begin with the keyword "XH".

Diagnosis Types
---------------------
This table is derived from the ICD-11 Neoplasms section. The codes start with 2. We have excluded codes with a . in them to exclude diagnosis where an anatomical site is appended. 

Laterality
---------------------
This table is derived from the ICD-11 Laterality section. There are only 4 codes for this - XK9J, XK9K, XK8G and XK70.

Grades
---------------------
This table is derived from the ICD-11 Grades section. However codes are manually created. 

Pathology Descriptors
---------------------
This table has  key terms in pathology like lvsi, necrosis, etc. These are usually, "Present", "Absent", "Indeterminate", "Not Specified", "Not Applicable", "Not Identified".

Major Cancer Sites
-------------------------------

These are manually created and coded. There are 16 categories as follows:
#. Hematological Neoplasms
#. Central Nervous System (CNS) Neoplasms
#. Head Neck Neoplasms
#. Thoracic Neoplasms
#. Breast Neoplasms
#. Male Genital System Neoplasms
#. Female Genital System Neoplasms
#. Endocrine Gland Neoplasms
#. Soft Tissue & Bone Neoplasms
#. Skin Neoplasms
#. Gastrointestinal Neoplasms
#. Urological Neoplasms
#. Hepatobiliary System Neoplasms
#. Exocrine Gland Neoplasms
#. Neoplasms of Unknown Origin (Unknown Primary)


Radiotherapy Modalities
----------------------------------
This section is also manually defined and has the following components:

#. Photon EBRT
#. Brachytherapy
#. Proton EBRT
#. Carbon Ion EBRT
#. Electron Beam EBRT
#. Neutron EBRT


Radiotherapy Treatment Type
------------------------------------------
This section has the types of radiotherapy. Again this list has been manually created. The following are the components in the list:   
#. Definitive
#. Adjuvant
#. Neoadjuvant
#. Palliative
#. Induction
#. Reinduction
#. Postoperative
#. Preoperative
#. Chemosensitizing

Radiotherapy Technqiues
-------------------------------------------

This table has also been manually created and has the following components:  
#. Conventional
#. Intensity Modulated Radiation Therapy
#. Volumetric Modulated Arc Therapy
#. Image Guided Radiation Therapy
#. Stereotactic Radiation Therapy
#. Intensity Modulated Brachytherapy
#. Electron Beam Therapy
#. Spatially Fractionated Radiation Therapy
#. Microbeam Radiation Therapy
#. 3D Conformal Radiation Therapy
#. Total Body Irradiation
#. Total Marrow Irradiation
#. Total Skin Electron Therapy
#. Hemibody Irradiation
#. Spot scanning Intensity Modulated Particle Therapy
#. Filter based Intensity Modulated Particle Therapy
#. Stereotactic Radiosurgery
#. Stereotactic Body Radiation Therapy
#. Intracavitary Brachytherapy
#. Interstitial Brachytherapy
#. Intraoperative Radiation Therapy
#. Intraoperative Brachytherapy
#. Intraluminal Brachytherapy
#. Surface Mould Brachytherapy


Adverse Effect
---------------------------------------

The adverse effects lookup is from the CTCAE 5.0 grading system. There is one modification that in addition to the MedDRA code which defines the type of toxicity we concatenate the grade of toxicity for uniqueness. This data comes in a excel format. The URL from which the file is obtained is https://ctep.cancer.gov/protocoldevelopment/electronic_applications/docs/CTCAE_v5.0.xlsx

IHC Protein list
---------------------------------------
This is a manually curated list of antibodies commonly used for IHC derived from the catalog of different vendors. The lookup table is available at : https://docs.google.com/spreadsheets/d/1n04ABIRFHlzdKMqhRef5CepD7ws60d_GCYt3gZSa2as/edit?usp=sharing

Comorbidity
----------------
For Comorbidity we have used the list of diseases in ACE 27 and CCI to get a modified list of comorbidities. This is available at the sheet : https://docs.google.com/spreadsheets/d/1QBsTNgZBWdORteiOKpK9q_ZND89UOI2sTCwF4fUBrdY/edit?usp=sharing

Gene Names
-----------------
Gene names will be downloaded from the following URL:
https://www.genenames.org/cgi-bin/download/custom?col=gd_hgnc_id&col=gd_app_sym&col=gd_app_name&col=gd_prev_sym&col=gd_name_aliases&status=Approved&hgnc_dbtag=on&order_by=gd_app_sym_sort&format=text&submit=submit This is a website that has gene names and corresponding HGNC IDs for more than 40,000 genes which include coding and non-coding genes.

Gene Expression Units
-----------------------------------------

Gene expression units lookup will be created  next. This is derived from the following URL: https://www.reneshbedre.com/blog/expression_units.html: 

#. CPM = 'Counts per million'
#. RPKM = 'Reads per kilobase per million'
#. FPKM = 'Fragments per kilobase per million'
#. TPM = 'Transcripts per million'
#. RSEM = 'Relative log expression'
#.  DESEQ2 = 'DESeq2'
#.  TMM = 'Trimmed mean of M-values'
#. SCnorm = 'Scale-invariant normalization'
#. GeTMM = 'Gene length correct TMM'
#. ComBat_Seq = 'ComBat-Seq Batch effect adjustment method'


Presentation
------------------------------------
This is a manually created table with the following components:  

#. Primary
#. Recurrent
#. Metastatic
#. Second Primary

Codes are derived from the NCIT codes for the above terms.

Disease Outcomes 
--------------------------------------
Disease outcomes are collected from the Cancer Care: Treatment Outcome Ontology available from download at : https://bioportal.bioontology.org/ontologies/CCTOO/?p=summary


Lesion Response
--------------------------------------
Lesion response categories are collected from the Cancer Care: Treatment Outcome Ontology available from download at : https://bioportal.bioontology.org/ontologies/CCTOO/?p=summary

Lesion Type
--------------------------------------
Lesion type categories are created manually. The following categories are present:    
#. Local
#. Nodal
#. Metastatic

Corresponding NCIT codes are used.

Treatment Intent 
----------------------------------

The Treatment intent categories are created manually and have the following components:  
#. Curative
#. Palliative

Corresponding NCIT codes are used.

Treatment Sequencing
-------------------------------------
This data is from the NCIT https://bioportal.bioontology.org/ontologies/NCIT?p=classes&conceptid=http%3A%2F%2Fncicb.nci.nih.gov%2Fxml%2Fowl%2FEVS%2FThesaurus.owl%23C158877 under  Cancer Therapeutic Procedure 

Drug Route
-------------------------------------

Drug route is from the https://bioportal.bioontology.org/ontologies/NCIT?p=classes&conceptid=http%3A%2F%2Fncicb.nci.nih.gov%2Fxml%2Fowl%2FEVS%2FThesaurus.owl%23C45246 NCIT Dosage form by Route of Administration


Units of Measure
-------------------------------------
Various units of measure like units of volume, mass, length, radiation dose, drug dose and percentage have been created. These are manually created and codes correspond to the usual unit abbreviations used.

Patient Outcome
-------------------------------------
This is created manually and has the following categories:  

#. Alive
#. Dead
#. Unknown

Codes are taken from the corresponding NCIT codes. 


Staging
-------------------------------------
Staging related lookup tables have been created manually. These codes for these categories are accepted abbreviations for the categories. 


Staging System
---------------------------------------

In addition to the usual staging systems like AJCC and FIGO staging systems we have also incorporated specialized staging systems for pediatric tumors taken from https://cancerqld.blob.core.windows.net/content/docs/childhood-cancer-staging-for-population-registries.pdf


Systemic Therapy Type
-------------------------------------
This is created manually and has the following categories:  

#. Chemotherapy
#. Immunotherapy
#. Targeted Therapy
#. Hormone Therapy
#. Bone Marrow Transplant
#. CART Therapy
#. Monoclonal Antibody

The codes are obtained from the corresponding NCIT codes. 


Anticancer Drugs
-----------------------------------

The list of anticancer drugs from the https://www.anticancerfund.org/en/database-cancer-drugs has been used for this lookup table. This database   is a curated listing of licensed cancer drugs produced by the Anticancer Fund. Source data comes from the NCI, FDA, EMA and other data sources. The intention is to provide researchers, clinicians and regulators with an easily filtered database of licensed drugs used in the treatment of cancer. Drugs which are used in cancer treatments to alleviate symptoms or other supportive care uses or which are used for diagnostic purposes are not included. Investigational agents and experimental treatments being used in clinical trials are also not included.

Clinical Significance 
--------------------------------
Clinical significance of the genetic alterations have been classified manually as follows:  

#. Pathogenic
#. Likely Pathogenic
#. Benign
#. Likely Benign
#. Variant of Unknown Significance
#. Not reported


IHC and Cytogenetics Results M-values
------------------------------------------------------------

These are also created manually as follows:  

#. Positive 
#. Negative
#. Equivocal
#. Indeterminate
#. Not Reported
#. Intact
#. Loss
#. Null

Codes are generated manually.


IHC Staining Intensity
------------------------------------------

IHC staining intensity are categorized into the following categories:
#. Strong  
#. Moderate  
#. Weak  
#. Indeterminate

Codes are generated manually.

Resection Margin Status 
-----------------------------------------------

The resection margin status codes are also created manually and have the following categories: 


#. R0 
#. R1 
#. R2  
#. Indeterminate


Treatment Effect
--------------------------------------------------

Treatment effect codes are also created manually. These have the following categories:

#. Present
#. Absent
#. Not Applicable

Severity 
----------------------------------------------------

Severity lookup codes are created manually and have the following values:  

#. Mild
#. Moderate
#. Severe
#. Unknown

Performance status
-----------------------------------------------------

Performance status lookups are created manually with compontents of the ECOG and KPS systems. 

Surgery Procedures
-----------------------------------------------------

This is taken from the NCIT database under the semantic types "Therapeutic or Preventive Procedures" and filtering the definitions by the following terms:  

#. surgical
#. surgery
#. resection
#. excision
#. anastomosis
#. biopsy
#. adenectomy
#. reconstruction

This ensures that all surgical procedures are included. 

Nodal Assessment Type
----------------------------------------------------

This lookup table has manually created values:  
#. Sentinel Lymph Node biopsy
#. Lymph node biopsy
#. Lymphadenectomy
#. Complete Lymph node dissection
#. Radical Lymph node dissection
#. Regional Lymph node dissection
#. Lymph node sampling
#. Other type of lymph node assessment.


Note that for some codes the codes are created manually as there are no corresponding NCIT codes.


Systemic Therapy Regimen
------------------------------------------------------

This is also derived from the NCIT ontology. We have filtered the Preferred Label column for words which end with the word Regimen.


Radiotherapy Volumes
-------------------------------------------------------

Radiotherapy volumes are considered differently as they have overlapping anatomical sites which are usually treated. Download from here  https://docs.google.com/spreadsheets/d/16Lgk3kyeu3VoriD4zHaje3MZm04mfZ8O7UqHFNl3jMc/edit?usp=sharing


Laboratory Tests
------------------------------------------------------

Laboratory tests are obtained from the LOINC data. We have selected the chemistry, hematology, serology and microbiological test as they are not represented in pathology. The URL for the download is https://data.bioontology.org/ontologies/LOINC/download?apikey=8b5b7825-538d-40e0-9e9e-5ab9274a9aeb&download_format=csv

Cytogenetic Abnormality
--------------------------------------------------------

Cytogentic abnormalty data is obtained from the Mitelman database. This is available at https://mitelmandatabase.isb-cgc.org/result. The recurrent chromosome aberration table has been downloaded manually and de-duplicated. As the database does not have a unique ID for each chromosome aberration, a unique ID has been generated. The datasheet is avaialble at https://docs.google.com/spreadsheets/d/1pbUKWSRypNWnVFkYmlEkM8o-_ElwL11KH8JnPC4nq0w/edit?usp=sharing





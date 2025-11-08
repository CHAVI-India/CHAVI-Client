
This application is designed to allow data import to the CHAVI client from csv files.
The client_app model is the model where the data will be stored. 
The client_app model relations are to be respected starting from the Patient model which will be the starting point of each import. 

The following models from (client_app/models.py) will be excluded:
1. PatientDicomFile
2. DICOMStudy
3. DICOMStudyProject
4. BulkDICOMUpload
5. UnprocessedDICOMStudies
6. BulkDICOMUploadSession
7. BulkDICOMStudyMatch

Please note that field list to be used in the remaining steps from the client_app model should always be dynamically generated from the models themselves and models/fields should not be hard coded. A model / field introspection service will therefore be necessary. 

The import process will be designed in the following steps:

1. Step 1 will involve the upload of a csv file with the specification that the delimiters used should be a comma. 
2. Step 2 will involve asking the patient ID to tell which field in the uploaded CSV file corresponds to the patient_id field in the Patient model. The system will then check the unique patient_id values in the csv and inform the user about which patient_ids already exist and which do not. 
3. Step 3 will invovle asking the user about which model they wish to import data into. To help the user choose a display of the model names, the fields (including data of the help associated with the field names) will be displayed so that they can select the model(s) they wish to import the data into. The display will also highlight the relations between the models arranging the model display into a intuitive hierarchy correponding to their FK relationships. 
4. If the users select models which are not in the same level of relationship for example if they select the pathology model (FK relationship Patient -> Diagnosis -> Pathology) and the Symptom model (FK relationship Patient -> Symptom) they will be asked to change the csv to ensure that the model hiearchy is maintained. The system should ask the users to upload data for a given level of relationship level. For example if Pathology data is to be imported then Symptom data should not be imported. The system should automatically disable these models when the first model is selected. However the parent relationship for the selected models in a hieararchy should be made available for mapping and import even if they are not selected actively. For example in the case of the Pathology model, the Diagnosis model should be available for mapping and import even if it is not selected actively. Note that the top model (Patient) will always be available. 
5. Step 4 will involve mapping of the field names in the csv file to field names in the selected models. This step will enable the system to determine data of which fields is to be imported. As users may upload a csv file with a wide format data where the repeated instances are represented across multiple columns they should be able to select more than one csv file column to be mappted to a single field name. However if this is done then it would also be important to note down the date corresponding to the individual instance of the repeated data. Hence if a mapped date field is unavailable for the model, the system should stop the user from proceeding with the import and ask them to add this information to the csv file before proceeding with the import further. The system should also nudge the user here to generate a long form csv file with examples rather than a wide form csv file.
6. Step 5 will allow the users to map column names to field values. This is also a common way data is represented. For example 5 comorbidities may have been collected in the csv file like Hypertension, Diabetes, Asthma, etc. and each row will indicate if the patient had the comorbidity or not. In CHAVI, this data should ideally be represented as a repeating instance of the comorbidity model. Hence to allow users to map this, the user should be able to select field name and the corresponing field value from the client_app and lookup_models. This the Diabetes column will be mapping to the value in the comorbidity_type field in the comorbidity model. During this time the other fields for the given model will also be avaialble for the user (with the appropriate widgets) such that they can add additional information. For example for Laboratory tests the csv may have values of Hemoglobin, TLC and Platelet count in three columns which will need to be mapped to LaboratoryResult model to the test name and quantitative_test_result value fields in the model. It is important that fields mapped in step 4 are excluded from step 5
6. Step 6 will involve setting up the date formats in the selected fields. The system will allow the user to set up the date format so that the date can be imported into the system.
7. Step 7 will allow calculation of dates in the database from a given duration or interval field value and a given date. The date given can be a start date in which case the duration / interval will be added to it to derive the end date. Alternatively it can be an end date in which case the duration or interval will be subtracted to generate the start date. The derived date will be stored in a client_app date field which is not selected in the steps before this. The date provided can be an user selected date or a date field available in the csv file. Note here the user will also be able to select the date format if the csv file date field is chosen. Note that the chosen date field may NOT be a mapped field in step 4, 5 or 6. 
8. Step 8 will involve setting up the lookup values for the fields. For selected fields which have been mapped to the client_app model fields in the step 4 where the field has a FK relationship / M2M relationship to the lookup app models (lookup/models.py), the system will display the lookup values in a select2 widget allowing them to search and select the lookup value in the system. The system will display the unique values for the corresponding field(s) in the csv file and allow one to one mapping for the lookup values. 
9. Step 9 will allow the user to set values for the client_app model fields which are not handled in the previous steps. These will be values that will apply to all patients in the import sesssion. The field widget should ensure that the lookup / choice fields values are displayed for the selection if the field type is like that and date time widgets, boolean field widgets are properly done as per the previous step.
10. Step 10 will check if the relationships between the models are being covered by the fields selected. For example in the csv the patient has selected fields mapped to the Radiotherapy model (FK relationship Patient -> Diagnosis -> Radiotherapy) but no diagnosis related fields were selected or available in the csv, then the user will prompt the user to review the existing diagnoses available for the patient and see if the the data is to be linked to the exsiting diagnosis. Similiarly if data related to Immunohistochemistry is being imported where pathology and/or diagnosis fields are not avaialble or selected (FK relationship Patient -> Diagnosis -> Pathology -> Immunohistochemistry) then the system will prompt the user to review the existing diagnosis and pathology and decide which one the Immunohistochemistry data is to be linked to. If the data is not available in the system the user should be able to specify a value for the respective models (they should be shown the fields corresponding to them with the proper widgets based on the field type). When the data is being imported this data will be saved in the database along with the imported data. 
11. Step 11 will involve generation of UUID for the models (except the Patient model where Patient ID is the primary key) for the PK for the corresponding models. The entire data which will be imported will be displayed as a nested JSON representation to the user before import so that they can verify it
12. Finally they will be able to import the JSON using DRF serializers implemented for the client_app. Ensure that the JSON also has information on the project(s) which have been selected in the step 1.


# Answers to the doubts
1. The hiearchy is to be dynamically determined. Please see the line 15 in this file.
2. I have changed to a Character field. One row of the db table will have one patient ID. Additionally added a boolean field to check if the patient ID exists in the client_app database.
3. Store the model names as a array.
4. Yes but this is for the step 4 not step 5. We would like to map multiple csv columns to a single field type. The export JSON should have them in the required long format.
5. Yes your mapping structure is correct. 
6. Yes we should store in a database - I have added the FileMissingRelations model to store the missing relations for a file import session.
7. The format should be a DRF nested serializer format. Ensure proper nesting with hiearchy.
8. Date format needs to be handled but delimters should be handled with code. Not stored in database
9. Linkage to existing dicom studies need not be handled during the import stage
10. Regenerated only if user goes back and modifies the data. However once the data has been imported the UUIDs should not be generated again.





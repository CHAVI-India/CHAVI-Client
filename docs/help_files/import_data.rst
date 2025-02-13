Importing Data
=============

The CHAVI system supports data import functionality through the Django admin interface using CSV (Comma Separated Values) files. This feature allows bulk upload of data for various modules.

Using the Import Feature
----------------------

Access and Navigation
^^^^^^^^^^^^^^^^^
* Navigate to the Django admin interface
* Select the data type you wish to import (e.g., Patients, Diagnoses, etc.)
* Look for the "Import" button in the top right corner

File Requirements
^^^^^^^^^^^^^^^
* **Format**: CSV (Comma Separated Values)
* **Encoding**: UTF-8
* **Headers**: First row must contain field names
* **Date Format**: YYYY-MM-DD (e.g., 2023-12-31)
* **Boolean Values**: Use "True"/"False" or "1"/"0"

Import Process
^^^^^^^^^^^^
1. Prepare your CSV file:
   
   #. Ensure all required fields are included
   #. Match column headers to database field names
   #. Verify data formats match requirements

2. Import steps:

   #. Click the "Import" button
   #. Choose your CSV file
   #. Select import format (CSV)
   #. Preview the data
   #. Confirm and process import

Special Considerations
--------------------

1. Data validation:

   #. All required fields must be present
   #. Foreign key references must exist in the database
   #. Data types must match field specifications
   #. Dates must be in correct format

2. Error handling:

   #. Review error messages if import fails
   #. Fix issues in CSV file
   #. Re-attempt import with corrected data
   #. Keep record of failed imports

3. Best practices:

   #. Test with small dataset first
   #. Backup database before large imports
   #. Verify imported data after completion
   #. Document any special handling requirements

4. Foreign key relationships:

   #. Ensure referenced records exist
   #. Use correct identifier values
   #. Consider import order for related data

Example CSV Format
----------------

Patient import file example::

    patient_id,gender,date_of_birth,date_of_registration
    P001,Female,1980-01-01,2023-01-15
    P002,Male,1975-06-30,2023-01-16

Diagnosis import file example::

    patient_id,diagnosis_date,cancer_system,presentation_type
    P001,2023-01-15,BREAST,NEW
    P002,2023-01-16,LUNG,NEW

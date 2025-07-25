Clinical Data Import using the CHAVI Client
============================================

The CHAVI Client allows you to import data from a CSV file. In order to do this you need to ensure that the data you are importing is in the correct format. The order of the columns in the CSV file is important and must match the order of the columns in the CHAVI Client. Importing is done through the Django Admin interface. Each list page will have an Import button that will allow you to import data from a CSV file. Clicking the IMPORT button will bring up a page where you can see the fields that will be imported and the order of the columns in the CSV file. 

In order to import data it is also important to be congnizant of the following:
1. Importing is done through the Django Admin interface.
2. Importing is done per page. That is Patient data is imported per patient, Lesion data is imported per lesion, etc.
3. Several lookup tables have been created to assist with importing data. The csv should contain the label corresponding to the lookup table to successfully import data.
4. For some tables, you will have to provide a ID field e.g. Patient. For others the system automatically generates the UUID. For these tables you DO NOT need to provide a value for the ID field. Please do note that each row of the csv will be imported as a new record and will receive a new UUID. 


.. note::
    Please contact us to help you with bulk data import. We can help you write scripts in R to format your data correctly. 



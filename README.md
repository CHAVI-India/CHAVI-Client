## Welcome

The CHAVI Client Application is a companion application to the CHAVI de-identification system. This application allows users to enter patient data at their own premsises and this clinical data can then be de-identified in a reporducible fashion. While the application is primarily designed for data entry using the provided forms, it is possible to allow import of data from other sources like CSV and other databases in the future. 

## Database schema

The database schema in the client application mimics the central CHAVI server database with few exceptions related to the user authentication tables. This allows data to be faithfully migrated to the central CHAVI server while retaining the longitudinal temporal linkage. 

## How to Install

First of all ensure that you have the latest version of Python 3 installed in your computer. Please see the official documentation available at https://www.python.org/downloads/ for system specific instructions. If you are using a Linux based system then this may be available in your repository.

Please clone the git repository in your computer using the following command. If you have SSH keys installed then you can use the alternative SSH command.

```
git clone https://gitlab.com/drsantam/chavi_client.git
```

After that create a python virtual environment using a package of your choice. We have used venv in this project and you can use the same also by following the instructions available at the Virtualenv website - https://virtualenv.pypa.io/en/legacy/installation.html

After the virtual environment has been created you will be able to activate the virtual environment. From inside the virtual environment install the project requirements. 

```
pip install requirements.txt
```

This will pull and install all the required packages. Note you may need to have an IT administrator to help you with the package installs. Additionally you may find that in Windows system Folder Access Policies prevent the script from running. In these cases please contact your IT Administrator for appropriate privileges. 

After the installation is completed then you should perform the following steps:  

### Database Setup
Create the database. Note the application is developed using a SQLite database but can accept other database engines too. Note that we will be pulling in all the lookup table data also in the same command. 

```
python manage.py migrate
```

## Environment Setup

Create a .env file in the root directory and add the following variables.

``` 
DJANGO_SECRET_KEY=django-insecure-%zvbz3$uzi$kvpd$2@5+6-=@7&8%l4^-lp!$(s#ysd9w8)fe! # Add secret key of the project. Ensure this is changed before deployment.
DEBUG=True # Set to True for development, False for production
DJANGO_ALLOWED_HOSTS='127.0.0.1,localhost' # Add other hosts if needed seperated by commas

DJANGO_DB_ENGINE=django.db.backends.postgresql # Add engine of the database
DJANGO_DB_NAME=chaviclient # Add name of the database
DJANGO_DB_USER=postgres # Add username of the database  
DJANGO_DB_PASSWORD=26rishi1978 # Add password of the database
DJANGO_DB_HOST=localhost # Add host of the database
DJANGO_DB_PORT=5432 # Add port of the database
```
See the sampleenv file for reference.

### Create a Superuser
Create a superuser. This superuser can be a local administrator.

```
python manage.py  createsuperuser
```
This will take you through a wizard where you will be asked to setup an username, provide your email address and set a password. Please ensure that this password is a long and complex password for security.

### Start the server

Start the server to start the application. The server will allow users from the LAN to access the client application. By default the application will be available on port 8000.

```
python manage.py runserver
```

After the server starts at the designated port on the localhost please access the server using the appropriate localhost port. Enter your superuser username and password to access the admin site. The path to the admin site is http://localhost:8000/admin

## Post Installation

### Create Site
The first step after logging in is to create a new site configuration. To do so go the form titled "Site Configuration" and click on the "Add Site Configuration" button. This will allow you to enter the site details. Please remember to put the site ID as the one which has been provided to you by the CHAVI team.

### Create User Group
The next step is to create a user group. To do so go the form titled "User Group" and click on the "Add User Group" button. This will allow you to enter the user group details. Please remember to put the user group ID as the one which has been provided to you by the CHAVI team. Also ensure that they are marked as staff so that they can access the admin interface.

### Create User
The next step is to create a user. To do so go the form titled "User" and click on the "Add User" button. This will allow you to enter the user details. Please remember to put the user ID as the one which has been provided to you by the CHAVI team.

### Configure the admin index to show the forms properly. 

While this is an optional step, it is recommended to configure the admin index to show the forms properly. To do so go the form titled "Application Group" and click on the "Add Application Group" button. This will allow you to organize the forms into categories. While the exact organization is up to you, it is recommended to organize the forms into categories that make sense for your organization:
1. Patient Data: Patient and Comorbidity form
2. Disease Data: Diagnosis, Pathology, Lesions and Stage Information forms
3. Treatment Data: Surgery, Radiotherapy, Systemic therapy, Concomitant medication and other therapy forms
4. Outcome Data: Outcome, Disease outcome, Patient reported outcome, Lesion response and Adverse events forms
5. DICOM Data: DICOM Studies and Patient DICOM Files forms
6. Configuration: Site Configuration, Group, User, Theme, Application Groups and Projects forms
7. Lookup Tables: Lookup Tables

You can then ensure that the forms are accessed by specific groups only allowing your data entry operators to access only the forms they need.



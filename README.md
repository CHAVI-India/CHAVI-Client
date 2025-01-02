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

After the installation is completed then you should perform the following steps

A. Create the database. Note the application is developed using a SQLite database but can accept other database engines too. 
```
python manage.py migrate
```

B. Create a superuser. 

```
python manage.py  createsuperuser
```
This will take you through a wizard where you will be asked to setup an username, provide your email address and set a password. Please ensure that this password is a long and complex password for security.

C. Start the server 

```
python manage.py runserver
```

After the server starts at the designated port on the localhost please access the server using the appropriate localhost port. Enter your superuser username and password to access the admin site. 

## Post Installation

Please see the provided manual to understand how to use the system, create new users, enter patient data and export data from the client from de-identification. We would be happy to help you understand the specifics of the system.
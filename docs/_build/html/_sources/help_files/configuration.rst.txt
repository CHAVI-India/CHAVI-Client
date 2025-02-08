Configuration Guide
=================

This guide explains how to configure the application after installation. The configuration involves setting up your site information and configuring user permissions.

Initial Site Configuration
------------------------

1. Access the Django Admin Interface:
   
   #. Go to ``http://<your-server>/admin/``. Usually the <your-server> is the localhost (127.0.0.1) or the LAN IP address if you wish the server to be able to serve pages on the server.
   #. Log in with the superuser account created during installation

2. Configure Site Information:
   
   #. Navigate to "Site Configuration" under client_app
   #. Click "Add Site Configuration"
   #. Fill in:
     - CHAVI Center ID (provided by CHAVI team)
     - Center Name (your hospital/institution name)
   #. Click "Save"

   Note: Only one site configuration should exist. This is enforced by the system.

3. Project Configuration:

   #. Navigate to "Projects" under client_app
   #. Click "Add Projects"
   #. Fill in:
     - Project ID (provided by CHAVI team)
   #. Click "Save"

   Note: Several Projects can be added.


User Groups and Permissions
-------------------------

The system requires two main user groups with specific permissions:

1. Create Data Entry Operator Group:
   
   * In Django Admin, go to "Groups"
   * Click "Add Group"
   * Name: "Data Entry Operators"
   * Permissions: Add the following permissions:
     
     View/Add/Change permissions for:
     
     - Patients
     - Lesions
     - Lesion Responses
     - Diagnosis
     - Pathology
     - Immunohistochemistry
     - Cytogenetics
     - Somatic Genomic Alterations
     - Surgery
     - Radiotherapy
     - Systemic Therapy
     - Patient Outcomes
     - Laboratory Results
     - DICOM Studies
     - Symptoms
     - Comorbidities
     - Patient Reported Outcomes
     - Concomitant Medications
     - Other Treatment
     - Cancer Outcomes
     - Adverse Effects
     - Radiation Volume
     - Radiation Dose Volume Data
     
     Note: Do NOT grant delete permissions or access to lookup tables

     .. tip::
        You can search for the tables by searching for 'client_app' in the search bar. 
        Please DO NOT grant delete permissions or access to lookup tables.

     If you are unsure about the permissions, please ask the CHAVI team for help.

2. Create Clinical Staff Group:
   
   * Create another group named "Clinical Staff"
   * Grant the same permissions as Data Entry Operators
   * Add additional view permissions for lookup tables

3. Restricted Tables (Superuser Only):
   
   The following tables should only be accessible to superusers:
   
   * All Lookup tables
   * Site Configuration
   * Projects

Creating Users
-------------

1. Create New User:
   
   * Go to "Users" in Django Admin
   * Click "Add User"
   * Enter username and password
   * Fill in required user information

2. Assign Group:
   
   * In the user edit page
   * Under "Permissions"
   * Select appropriate group (Data Entry Operators or Clinical Staff)
   * Save the user

Security Recommendations
----------------------

1. Password Policy:
   
   * Require strong passwords
   * Set password expiration
   * Implement account lockout after failed attempts


2. Data Entry Guidelines:
   
   * Train users on data entry procedures
   * Implement data validation checks
   * Regular backup of database


For additional help please contact CHAVI support team. 

You can raise tickets for support at https://gitlab.com/chavi/chavi-2.0/-/issues


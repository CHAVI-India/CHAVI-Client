Configuration Guide
======================

This guide explains how to configure the application after installation. The configuration involves setting up your site information and configuring user permissions.

Initial Site Configuration
-----------------------------

1. Access the Django Admin Interface:
   
   #. Go to ``http://<your-server>/admin/``. Usually the <your-server> is the localhost (``127.0.0.1``) or the LAN IP address if you wish the server to be able to serve pages on the server.
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
------------------------------

You do not need to create permission groups by hand. The application ships
with ready-made roles — *Clinical Data Viewer*, *Clinical Data Entry*,
*Data Import Operator*, *LLM Extraction Operator*, *LLM Configuration*,
*Deidentification Operator* and *DICOM Administrator* — created
automatically by the database migration. The *DICOM Administrator* role
also covers the DICOM archive (configuration, locations, manual
archive/de-archive).

.. note::
   The full description of each role, how to assign roles to users, and the
   permission checked by every page is documented on the
   :doc:`roles_and_permissions` page — use that as the reference.

In short:

1. Create the users you need (below).
2. In Django Admin, open **Users → (user) → Groups** and move the wanted
   role(s) into *Chosen groups* — a user may hold several roles at once.

Restricted data (lookup tables, site configuration, projects) stays
superuser-only; there is no role that grants it.

Creating Users
--------------

1. Create New User:
   
   * Go to "Users" in Django Admin
   * Click "Add User"
   * Enter username and password
   * Fill in required user information

2. Assign a role:
   
   * In the user edit page
   * Under "Groups"
   * Select the appropriate shipped role (see :doc:`roles_and_permissions`)
   * Save the user

Security Recommendations
---------------------------

1. Password Policy:
   
   * Require strong passwords
   * Set password expiration
   * Implement account lockout after failed attempts


2. Data Entry Guidelines:
   
   * Train users on data entry procedures
   * Implement data validation checks
   * Regular backup of database


For additional help please contact CHAVI support team. 

You can raise tickets for support at https://github.com/CHAVI-India/CHAVI-Client/issues


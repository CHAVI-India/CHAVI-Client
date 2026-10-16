Getting Scans from the Hospital Imaging System
=================================================

Instead of uploading scan files yourself, the CHAVI client can fetch them directly from your hospital's imaging system (the PACS). This is done through the DICOM Server, which also accepts scans that your imaging system sends on its own.

Who can use this: you need permission to add DICOM studies. If you do not see the menu, ask your administrator.

The DICOM Server page
----------------------

Click **Data Import → DICOM Server** in the top menu. The page shows:

* **Local Server Configuration** — how this server is set up (its name, address and whether it is accepting scans).
* **Remote Nodes** — the outside imaging systems this server can talk to.
* **Recent Retrieval Jobs** — the latest fetches, with their progress.

Fetching scans for a patient
-----------------------------

#. On the DICOM Server page, click **Retrieve Studies**.
#. Pick the imaging system (remote node) to search.
#. Pick the patient. Only patients who are already registered and have given CHAVI consent appear in the list — scans are never fetched for unknown or unconsented patients.
#. Click **Start Retrieval**.

The job runs in the background. You will get a notification when it finishes.

Checking a retrieval job
-------------------------

Click **Retrieval Jobs** on the DICOM Server page to see all past and running jobs. Opening a job shows the studies that were found and each image that was received.

Scans that arrive for a patient ID the system does not know are turned away and recorded, so nothing is stored for the wrong patient.

Automatic fetching
-------------------

Two things can fetch scans without you doing anything:

* When a patient's consent is recorded for the first time, the system asks every imaging system with automatic fetching switched on for that patient's scans.
* Administrators can also set a schedule on each imaging system, so the server checks for new scans regularly (for example every night).

The schedule and other settings are covered in :doc:`dicom_server_setup`.

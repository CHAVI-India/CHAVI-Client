Handling DICOM Data
====================

The CHAVI client lets you get DICOM data (medical scans) into the system in these ways:

1. Uploading a ZIP file of scans for one or more patients
2. Fetching scans directly from your hospital's imaging system (see :doc:`dicom_retrieval`)
3. Receiving scans sent by the imaging system on its own

Uploading a ZIP file
---------------------

This is the usual way to add scans. The ZIP can hold studies for many patients at once.

Steps:
^^^^^^

#. Click **Data Import → DICOM Upload** in the top menu.
#. Select or drag in your ZIP file and click **Upload and Analyze**. The system reads every study inside and works out which patient each belongs to.
#. On the **Match Studies** page, review the automatic matches. For any study that could not be matched, pick the right patient from the list yourself. Studies that still have no match are set aside in an unprocessed area — nothing is filed under the wrong patient.
#. On the **Confirm** page, check everything once more and confirm.
#. The files are saved under each patient and their study details recorded. The **Complete** page sums up what was done.

You can revisit any past upload under **Data Import → DICOM Sessions**.

.. tip::
   For a large batch, keep the ZIP to a few GB at most so the upload does not time out.

Fetching and receiving scans
-----------------------------

If your site's DICOM server is set up, you do not need ZIP files at all — the system can pull a patient's scans from the imaging system, and the imaging system can send scans in on its own. See :doc:`dicom_retrieval` and :doc:`dicom_server_setup`.

Uploading through the admin area
---------------------------------

Staff can also upload through the Django admin interface, which works a little differently:

* **Patient DICOM Files** (single patient) — pick the patient, upload the ZIP, save, then run the "Extract and Process DICOM File and extract metadata" action from the list page. The patient's ID inside the scans is standardised to match the record you chose.
* **Bulk DICOM File Upload** (many patients) — upload the ZIP, save, then run the "Process Bulk DICOM Files" action. Studies whose patient ID does not match anyone in the system are moved to an unprocessed folder rather than rejected outright.

In both cases the system stores the files as ``Patient_ID/Study/Series`` and records the study details (date, description, series descriptions) in the database.

Associate DICOM studies with Project
---------------------------------------

This functionality is provided to allow you to associate a batch of DICOM studies with a project. Note that the same DICOM studies may be part of multiple projects. 

Steps:
^^^^^^

#. Navigate to the link title DICOM Study Data in the Django Admin interface.
#. Select the DICOM studies which you wish to associate with a given project.
#. Select the action "Associate selected DICOM studies with a Project" from the dropdown menu. Click on the Run button to run the action.
#. Select the project from the dropdown menu in the popup page.
#. Click the "Associate DICOM Studies with Project" button to complete the process.

The DICOM studies associated with a project will now appear in the page titled "DICOM Studies Associated with Projects". This would allow you to see all the studies that have been associated with a specfic project and delete the association if required. 

Adding Study Type information
-----------------------------

A DICOM study may be done for various reasons — before treatment, for planning, to check the treatment, and so on. Each study has a study type to record this.

Most studies get their type automatically: the system looks at the scan's details (its modality and descriptions, and when it was taken relative to treatment) and picks the best fit. Administrators manage these rules under "Study type rules" in the admin area — rules are tried in priority order and the first match wins.

You can always set the type yourself: pick it from the dropdown on the study and save. A type you set by hand is never overwritten by the automatic rules.

The following study types are available:

#. Pre-treatment Diagnostic image: diagnostic images acquired before the start of the treatment.
#. Planning image: images acquired for the planning process including simulation CT, simulation x-rays and planning MR or PET.
#. On treatment verification image: images acquired during the treatment to verify the delivery of the treatment. Examples include portal films, CBCT, EPID, Cine images etc.
#. Planning image for adaptive treatment: images acquired for planning adaptive treatment. Note that in some situations, an image may be an On treatment verification image as well as a planning image for adaptive treatment.
#. Post-treatment Therapy response image: images acquired after the treatment to evaluate the response to the treatment.
#. Therapy delivery image: images acquired during the treatment to evaluate the delivery of the treatment. Examples are images acquired after radionuclide treatment or transit dosimetry images.
#. Therapy QA image: images acquired during the treatment to evaluate the quality of the treatment. These would include images like QA films, portal dosimetry images, 3D array dosimetry images etc.
#. Post-treatment Diagnostic image: images acquired after the treatment to evaluate the final state of the treatment.
#. Other: images acquired for other purposes.

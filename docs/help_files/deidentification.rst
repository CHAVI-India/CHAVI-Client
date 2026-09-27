De-identifying Patient Data
=============================

Before data leaves your site for the CHAVI databank, everything that could identify the patient is removed — from the scans and from the clinical data. This page explains how to run de-identification.

.. note::
   These pages need staff access.

The patient list
-----------------

Click **Deidentification** in the top menu to open the patient list. Along the top are filters — by patient ID, whether they have been de-identified yet, gender, job status, or how many studies they have — so you can narrow down exactly who you want to work on.

To de-identify:

* **Selected patients** — tick patients, then click **Deidentify Selected**.
* **Everyone matching the filters** — set your filters, then click the de-identify button for the filtered set.
* **All patients** — use the button for all patients (you will be asked to confirm).

Each job runs in the background and appears under :doc:`Task Runs <getting_around>`.

One patient at a time
----------------------

Click a patient in the list to open their page. It shows each of their studies and the latest de-identification job for it, with the number of files done, failed, and any errors.

* Click **Deidentify All Studies** to process every study, or tick studies to process only some.
* Click **Download DICOM (ZIP)** to get the de-identified scans, or **Download Clinical (JSON)** to get the de-identified clinical data. Downloads can also be run for many patients at once from the list page.

What gets removed
------------------

De-identification cleans the scan files in two ways:

* The details stored inside each file — patient name, dates that could identify them, and similar — are replaced with safe values. Each patient keeps the same replacement ID every time, so their data still joins up.
* Text burnt into the images themselves is covered up.

The original files are never changed — the cleaned copies are stored separately, so you can always go back.

.. tip::
   If some files fail, open the patient page — the failed count and the reason are shown next to the job, and you can run de-identification again.

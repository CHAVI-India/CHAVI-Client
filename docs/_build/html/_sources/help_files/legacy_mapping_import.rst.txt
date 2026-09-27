Importing Old De-identification Records
==========================================

If your site used the older desktop tool to de-identify scans, the CHAVI client can import its records so the same patients keep the same replacement IDs. You only need to do this once, when moving to the client.

.. note::
   This page needs staff access.

What you need
--------------

Two files from the old tool:

* the database file (``app.db``)
* the key file (``encryption.key``)

Running the import
-------------------

#. Click **Deidentification → Legacy Mapping Import** in the top menu.
#. Choose both files and start the import.
#. The job runs in the background — watch it under Task Runs, then open **Legacy Import Results** when it finishes.

Fixing what did not match
--------------------------

The results page shows everything from the old files, split into what matched the records in the system and what did not. Rows that did not match — a patient the system does not know, a study not yet uploaded, and so on — need to be created before their mappings can be used.

* To create one missing item, open its section and fill in the short form (for a patient, just the patient ID).
* To create everything at once, use the bulk-create button — the system makes all the missing patients, studies, series and instances in one pass.

When nothing is left unmatched, the import is complete and the old mappings will be used for any future de-identification.

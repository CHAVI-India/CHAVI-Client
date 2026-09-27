Pulling Data Out of Documents
=================================

The CHAVI client can read documents for you — pathology reports, discharge summaries, spreadsheets — and pull out the clinical details, ready for you to check and save. You stay in control: nothing reaches the patient's record until you have reviewed and approved it.

Who can use this: you need the extraction permissions. If you do not see the **LLM Extraction** menu, ask your administrator.

Uploading a file
-----------------

#. Click **LLM Extraction → Upload Files**, then **Upload New File**.
#. Choose your file. PDF, CSV and Excel files are accepted. Excel files with several sheets are split into one file per sheet.
#. Optionally link the file to a patient now — you can also do it later.
#. Click **Upload**.

On the file's page, click **Process File**. This turns the document into plain text the system can read.

.. note::
   If a PDF is a scan (a photo of a document), processing finds little or no text. In that case a **Run OCR** button appears — click it and the system will read the text from the image.

Removing personal details
--------------------------

Before a document is read, the system can hide patient-identifying details (names, phone numbers, addresses and so on) so they are never sent to the reading service.

#. On the file's page, click **Run deid** next to the processed text.
#. Open **Review deid** to check the result. Personal details appear as tags like ``PERSON_1``.
#. If something was missed, select the text and click **Redact selection**. If too much was hidden, use **restore** next to a tag to put it back.
#. Click **Mark as reviewed** when you are happy.

.. note::
   Depending on how your server is set up, this review may be required before extraction can run.

Running the extraction
-----------------------

#. Click **LLM Extraction → Data Extraction** to open the dashboard. It lists every patient who has uploaded files.
#. Open a patient, tick the files to read, and click **Start extraction**.
#. The job runs in the background. Watch it under **Extraction Results**.

Reviewing and saving
---------------------

When the job finishes, open it from **Extraction Results**. You will see the records the system found, with the field values it proposes. Each record shows the piece of text it came from, so you can check it against the document.

* Read through the records and fix anything that is wrong.
* Click **Review & Save**, then approve, to write the records into the patient's data.
* A record of every review is kept in the job's history, including who approved it.

.. warning::
   Deleting an uploaded file also deletes its processed text, extraction jobs and extracted results. A warning shows what will be removed before you confirm.

Setting it up
--------------

Extraction needs to be configured first — which service to use, what to pull out, and the instructions it follows. This is covered in :doc:`extraction_setup`.

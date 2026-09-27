Importing Data with the CSV Wizard
=====================================

The CSV import wizard helps you bring in patient data from a spreadsheet. It walks you through a series of steps, checks the data as you go, and lets you review everything before anything is saved.

To start, click **Data Import → CSV Data Import** in the top menu. This opens the list of your import sessions. Click the button to start a new import. You can leave a half-finished import and come back later — it will be waiting for you in this list.

Before you start
-----------------

* The file must be a CSV file (spreadsheet saved as "Comma Separated Values").
* The first row must contain column names.
* The file must include a column with the patient ID. This is how the system knows which patient each row belongs to.

The steps
---------

The wizard has twelve steps. Most take only a minute or two.

#. **Upload CSV File** — choose your file and the project this data belongs to.
#. **Map Patient ID Column** — tell the system which column holds the patient ID. It then shows you which IDs already exist in the system and which are new.
#. **Select Models** — choose the kind of data you are importing (for example Symptoms or Pathology). The system shows the choices as a family tree, because some kinds of data sit inside others — Pathology, for example, always belongs to a Diagnosis. Picking one option may switch off others that do not fit.
#. **Map Fields** — match each spreadsheet column to the field it should fill. If the same information is spread over several columns (for example BP_1, BP_2, BP_3), you can join them to one field. If you do this, the file must also have a column with the date for each of them.
#. **Map Column Values** — used when a column's *name* is itself the data. For example, if you have one column per symptom (Diabetes, Hypertension...) and the cell says yes or no, this step turns each column into a record.
#. **Set Date Formats** — tell the system how dates look in your file (for example day-month-year), so they are read correctly.
#. **Calculate Dates from Duration** — if your file has a length of time instead of a second date (for example "90 days of treatment"), the system can work out the missing start or end date for you.
#. **Map Lookup Values** — for fields with fixed choices (dropdown lists), match each value in your file to the matching value in the system.
#. **Set Default Values** — fill in required fields that are not in your file. The value you pick here applies to every row.
#. **Handle Missing Relationships** — if you are importing something that must sit inside another record (like Pathology inside a Diagnosis) but the file does not say which one, the system asks you to link it to an existing record or create the missing piece.
#. **Review & Confirm** — see everything that will be saved, laid out patient by patient. Read it carefully — this is your last check.
#. **Execute Import** — run the import. You will see a success message or a list of the errors that stopped it.

Tips
----

.. tip::
   Try the wizard with a small file first — a handful of rows — to check your format before importing everything.

.. note::
   You can go back to an earlier step at any time to fix a choice. Once the import has run, it cannot be run again from the same session.

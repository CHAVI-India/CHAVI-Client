Clinical Data Import using the CHAVI Client
============================================

The CHAVI Client lets you bring in clinical data from a CSV file (a spreadsheet saved as "Comma Separated Values"). The recommended way is the import wizard, which checks your data step by step — see :doc:`csv_import_wizard`.

A few things to know whichever way you import:

1. The file must contain a patient ID column, so the system knows which patient each row belongs to.
2. Several lookup tables are built in to help you — for fields with fixed choices, your file should contain the label as it appears in the lookup table.
3. For some tables you provide an ID yourself (like the patient ID); for others the system creates one automatically.

There is also a simpler import built into the admin area — see :doc:`import_data`. It does less checking, so the wizard is usually the better choice.

.. note::
    Please contact us to help you with bulk data import. We can help you write scripts in R to format your data correctly.

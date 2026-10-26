Setting Up Automatic Data Extraction
======================================

Before the system can read documents (see :doc:`automatic_data_extraction`), an administrator needs to tell it which reading service to use, what to pull out, and how to ask. Everything on this page lives under the **LLM Extraction** menu and needs the right permissions.

The easiest way: the wizard
----------------------------

Click **LLM Extraction → Start Wizard**. It walks you through four steps:

#. **Response model configuration** — give the setup a name and pick the reading service.
#. **Select database tables** — choose the kinds of data to look for (Diagnosis, Pathology, Symptoms and so on).
#. **Select fields** — tick exactly which fields to fill in each one.
#. **Review & build** — check the summary and finish. The setup is then ready to use on the extraction dashboard.

The pages below do the same things by hand, and let you adjust them later.

LLM Clients
------------

An LLM Client is the connection to the reading service — the program that does the reading. Each one needs a name, the model to use, its address, and an access key (which the system stores encrypted). If the key expires, record the expiry date and refresh key so you are warned before it stops working.

Two settings matter if jobs fail or are cut short:

* **Request timeout** — how long to wait for an answer. Slow "reasoning" models need this raised (the form explains the suggested values).
* **Context size / max tokens** — how much text the service can take in, and how much it may write back. Raise the second one if results get cut off mid-answer.

Use the **test connection** button on a client's page to check the details before running anything.

Response Models
----------------

A Response Model is the shopping list of what to pull out of a document — which tables and which fields. The wizard builds one for you; this page lists them all and lets you edit them later.

Instructor Prompts
-------------------

These are the instructions sent to the reading service — for example, "only take values you can see in the text". They are sent in order, lowest number first. The defaults work well; change them only if results are coming back wrong.

Lookup Embeddings
-----------------

Some fields have fixed lists of allowed answers (dropdowns). This setting teaches the system to match what a document says to the closest allowed answer — useful when wording differs, like "high blood pressure" versus "hypertension".

Pick or create a configuration, make it active, then click the button to build the matching index. Building takes a while the first time and runs in the background — a progress bar shows it working. If the build fails, the old index keeps working.

Text de-identification pipelines
--------------------------------

The deidentification pass applied to documents before extraction (see
:doc:`automatic_data_extraction`) is driven by named **pipelines** — each
pipeline fixes which machine detects personal details, and which optional
extra passes run on top. The building blocks are always on: the built-in
rule-based detectors and the date-shifting algorithm (dates are shifted by a
random amount so relative timing survives but the real date is gone).
Per pipeline you configure:

* **NER engine** — the main detector. The bundled spaCy model needs no
  setup; or a HuggingFace NER model that runs locally (patient text never
  leaves the machine). The model downloads itself on first use.
* **Optional second pass** — a locally-cleared large language model that
  catches details the main detector misses.
* **Optional third check** — a fast decision model that reviews each flagged
  item and decides redact-or-keep, reducing over-redaction.
* **Confidence threshold and date-shift range** — how sure the detector must
  be before redacting, and how far dates may be shifted.

Pipelines are managed under **LLM Extraction → Deid Pipelines**; the
extraction operator picks one per file when running deid by hand. Note that
managing pipelines is not part of the shipped *LLM Configuration* role — it
needs the ``extractor`` permissions on ``textdeidentificationpipelineconfig``
granted directly to a user (see :doc:`roles_and_permissions`).

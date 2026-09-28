Roles and Permissions
=====================

CHAVI uses Django's built-in permission system. Every page and action in the
application checks a *model permission* (``view``, ``add``, ``change`` or
``delete`` on a specific model), and users receive those permissions through
**groups** — the groups act as ready-made roles.

If a user does not hold the permission a page needs, the link to it is hidden
from the navigation menu, the homepage and the patient summary. Should they
still reach the address directly, they get a "permission denied" page rather
than data.

The roles
---------

Seven groups are created automatically by the database migration
``client_app.0029_rbac_roles``. Assign users to them in the Django admin under
**Users → Groups**.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Role
     - What members can do
   * - **Clinical Data Viewer**
     - Read-only access to all clinical data: patient search, patient summary,
       every clinical list view (diagnosis, pathology, lesions, treatment,
       outcomes…), DICOM study records, patient data and DICOM exports, and the
       Task Runs page.
   * - **Clinical Data Entry**
     - Everything in *Clinical Data Viewer*, plus add and edit rights on every
       clinical record (patients, comorbidities, symptoms, laboratory results,
       diagnoses, pathology, stage information, lesions, surgery, radiotherapy,
       systemic therapy, other treatment, concomitant medications, outcomes,
       adverse effects, genomic data, patient DICOM files).
       **Deletion stays administrator-only** — there are no delete views in the
       frontend.
   * - **Data Import Operator**
     - Runs the CSV import wizard (create, view and work through import
       sessions), bulk DICOM uploads with study matching, the patient search
       needed for matching, and DICOM query/retrieve jobs against remote
       nodes.
   * - **LLM Extraction Operator**
     - Uploads files for extraction, reviews deidentified text, runs and
       monitors extraction jobs, reviews results and approves record creation.
       Cannot change LLM settings.
   * - **LLM Configuration**
     - Full management of LLM client configurations, response models, database
       table/field mappings, instructor prompts and semantic-search embedding
       configurations. Read-only view of uploads, extraction jobs and results.
   * - **Deidentification Operator**
     - Views the deidentification patient list, triggers deidentification
       jobs, downloads deidentified DICOM and clinical exports, imports legacy
       patient-ID mappings, and follows deidentification job/task status on the
       Task Runs page.
   * - **DICOM Administrator**
     - Manages the DICOM server configuration, remote nodes (add, edit,
       delete, echo test), patient ID aliases and auto-retrieval settings, and
       monitors retrieval jobs. Cannot itself trigger retrievals or see patient
       clinical data.

A user may belong to several groups at once — the permissions add up.
Superusers (``is_superuser``) bypass all checks, and the **Admin** link only
appears for users with ``is_staff``.

Assigning a role to a user
--------------------------

1. Open the Django admin at ``/admin/``.
2. Open **Users**, pick the user, and scroll to **Groups**.
3. Move the wanted role(s) into *Chosen groups* and save.

You can also do this in a shell::

   python manage.py shell -c "
   from django.contrib.auth.models import Group, User
   user = User.objects.get(username='jane')
   user.groups.add(Group.objects.get(name='Deidentification Operator'))
   "

Creating or changing a role
---------------------------

The groups and their permission sets are defined in the ``ROLES`` dict in
``client_app/migrations/0029_rbac_roles.py``. To change what a role covers,
edit the user's groups in the admin, or adjust permissions on a group
directly under **Admin → Groups** — no redeploy needed. The migration's
assignments are the shipped default; changes made in the admin are not
overwritten unless you deliberately re-run that migration.

Common permission checks
------------------------

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Action in the UI
     - Permission checked
   * - Patient search / patient summary / patient data export
     - ``client_app.view_patient``
   * - Add a clinical record (any "Add" form)
     - ``client_app.add_<model>``
   * - Edit a clinical record
     - ``client_app.change_<model>``
   * - View a clinical list page
     - ``client_app.view_<model>``
   * - CSV import wizard
     - ``data_import.add/view/change_fileimportsession``
   * - Bulk DICOM upload / sessions / matching
     - ``client_app.add/view/change_bulkdicomuploadsession``
   * - DICOM server config, nodes, echo
     - ``dicom_server.change_dicomserverconfiguration``, ``*_remotedicomnode``
   * - Query/retrieve from a remote node
     - ``dicom_server.add_retrievaljob``
   * - LLM extraction (files, jobs, review)
     - ``extractor.*_fileupload``, ``*_extractionjob``, ``*_extractionresult``
   * - LLM configuration (clients, models, prompts, embeddings)
     - ``extractor.*_clientconfiguration``, ``*_responsemodel``, ``*_instructormessage``, ``*_embeddingconfiguration``
   * - Deidentification list, jobs and exports
     - ``deidentification.view_deidpatient``, ``add/view_deidentificationjob``
   * - Task Runs page
     - ``client_app.view_taskrun``
   * - Django admin site
     - ``is_staff`` flag (plus per-model admin permissions)

DICOM Archive
=================

The DICOM Archive moves local DICOM study folders off the app's media volume into a configurable location — another local folder or a NAS/LAN share mounted on the machine — and restores them on demand. It frees up local disk for incoming studies without losing any data, and deidentification always gets the files it needs: archived studies are restored automatically before a deidentification run touches them.

No DICOM network transfer is involved: archiving is plain file move/copy of the study folders, so the archive location just needs to be a directory the app (and the Celery worker) can read and write.

Everything on this page needs the matching user permissions (see :ref:`dicom-archive-permissions` at the end).

Archive locations
-----------------

Locations are managed under **Data Import → DICOM Archive → Locations**. Each location has:

* **Name** — a friendly label, e.g. "NAS archive".
* **Type** — *Local folder* or *Mounted share (NAS/LAN)*. A local folder may be an absolute path or a path relative to the media root; a mounted share must be an absolute path to the mounted point.
* **Path** — checked for write access when you save (the directory is created if needed). A path the app cannot write to is rejected with an error.
* **Default** — one location is the default target for the scheduled sweep (below). New locations are not the default until you say so.
* **Active** — untick to stop using a location without deleting it.

*Test* button (🔌 per row on the Locations page, and a **Test path** button on
the add/edit form that probes the values you are typing before you save):
checks that the path is **reachable**, **writable**, and that a real **write
succeeds** — it writes a small persistent file,
``chavi_archive_write_test.txt``, into the location. Open that file on the
share (Windows Explorer, or ``ls`` it from the host) to confirm the write
really landed where you think it did; the file is safe to delete. If the
directory does not exist yet it is created by the test (the app does the
same when the location is saved or an archive runs).

A location that still holds archived studies cannot be deleted — de-archive (or delete) its studies first.

Archiving a study
-----------------

Under **Browse Studies** you see every study that has a local folder, with its archive status:

* **Local** — files are on the media volume, nothing archived.
* **Archiving… / Restoring…** — a task is currently moving the files.
* **Archived** — the files live in the archive location; the row is not selectable (de-archive it from the Archived list first).
* **De-archived** — was archived, has been restored locally; it can be archived again.

Tick the studies you want and pick the target location, then click **Archive Selected**. The work runs in the background as a Celery task — the page shows a progress box while it runs and links to the task run list. One bad study (for example a folder that disappeared mid-run) is reported as a failure and never stops the rest of the batch.

By default archiving **moves** the study folder (the local copy is gone afterwards). If you keep the "local copy is kept" option in the configuration, archiving copies instead and the local folder stays.

Either way, when a patient's last study folder is moved away, the now-empty per-patient folder under ``processed_dicom`` is cleaned up. The same tidy-up happens on the archive side when a patient's last study there is de-archived.

Scheduled archival
------------------

The **Configuration** page holds the scheduled-sweep policy:

* **Enabled** — turn the sweep on.
* **Archive studies older than** — a study is a candidate once it is this many days old (counted from its study date).
* **After archiving** — delete the local copy, or keep it.
* **Schedule** — five cron fields (minute, hour, day of week, day of month, month); an asterisk means "every".
* **Batch limit** — how many studies one sweep may archive; the oldest eligible ones are taken first.

Saving the configuration updates the Celery beat schedule automatically. The sweep archives into the default active location; if there is none it falls back to the first active location. With the sweep disabled, or nothing eligible, it does nothing.

Archived studies and de-archival
--------------------------------

The **Archived Studies** page lists the studies that currently live in an archive location (studies that have been de-archived are hidden by default but can be shown with the status filter). Each row shows the location, size and instance count.

Tick archived studies and click **De-archive Selected** to restore them to their original local paths. If the patient was re-ingested in the meantime, the restored files are merged into the existing local folder without overwriting anything. If a restore cannot complete (for example the archive folder is missing), the record stays *Archived* so you can retry.

Deidentification of archived studies
------------------------------------

You never have to de-archive a study by hand before deidentifying it. When a deidentification run starts, any archived studies in the roster are restored first; if one of them cannot be restored, the run fails with a message naming the study and nothing is deidentified. As a safety net, each study is also checked again right before it is processed — so a study that gets archived between the start of the run and its turn is restored on the spot (or the run skips it with a recorded error instead of touching missing files).

Deleting studies and patients
-----------------------------

Deleting a study (or a patient, which cascades to all of their studies) also deletes the DICOM files on disk: the local folder and, when the study was archived, the archived copy. The database row and the files stay consistent either way.

.. _dicom-archive-permissions:

Permissions and roles
---------------------

The archive uses the standard Django model permissions on the *Dicom Archive*
models (Archive Configuration, Archive Location, Archived Study). The full
permission set is part of the shipped **DICOM Administrator** role — that
group manages the archive configuration, locations, and can archive and
de-archive studies (added by migration ``client_app.0031``). See
:doc:`roles_and_permissions` for how roles work and how to assign them.

If a user needs only part of the feature (for example: may archive but not
reconfigure, or view-only), grant individual permissions directly under
*Users → (user) → user permissions* — the *Dicom Archive* section offers
view/change/add/delete on each of the three models. The page-to-permission
table and a smoke-test checklist live in ``dicom_archive/PERMISSIONS.md`` in
the source tree.

Running under Docker
--------------------

Inside the containers the app's media root is ``/app/media`` and study folders live at ``/app/media/processed_dicom/<patient ID>/<study UID>``, so **a location path is always a path inside the containers**. Three common setups:

* **Another folder in the media volume** — no compose change; use a relative path like ``dicom_archive`` (resolves to ``/app/media/dicom_archive``). Caveat: same physical disk as the source data.
* **NAS/LAN share mounted on the Docker host** — mount it on the host (for example at ``/mnt/nas/chavi-archive``) and add the bind mount ``/mnt/nas/chavi-archive:/archive/dicom`` to **both** the ``chaviclient-celery-worker`` and ``chaviclient-django`` services; create the location with type *Mounted share* and path ``/archive/dicom``.
* **Windows host with an SMB share** — bind the UNC path directly (``//NAS_HOST/chavi-archive:/archive/dicom``), again in both services.

The django (web) container needs the mount too because the location form probes the path for write access when it is saved — a path mounted only in the worker fails that validation. The full section with all three scenarios and the verification commands is on the :doc:`docker_installation` page ("DICOM Archive Storage (NAS/LAN)").

Setting Up the DICOM Server
==============================

The DICOM server lets the CHAVI client receive scans from other imaging systems and fetch scans from them. Everything on this page needs staff access.

What the server does
---------------------

* Accepts scans sent to it by imaging systems — but only for patients who are already registered. Scans for anyone else are turned away.
* Lets staff pull a patient's scans in from a remote imaging system (see :doc:`dicom_retrieval`).
* Can check remote systems for new scans on a schedule.

Server settings
----------------

On the DICOM Server page, click **Edit configuration** (staff only). You can change:

* **AE Title** — the name this server calls itself when talking to other systems (up to 16 characters, letters and numbers)
* **Port** and **Bind address** — where the server listens for incoming scans
* **Max PDU** — the largest message size it will accept (usually leave as-is)
* **Query/retrieve timeout** — how long to wait for a remote system to answer
* **Storage** — switch accepting scans on or off

.. warning::
   Changes to the name, address or port only take effect after the DICOM server is restarted. The port here must match the port the server actually runs on — ask whoever manages the server before changing it.

Remote nodes
-------------

A remote node is an outside imaging system, for example your hospital's PACS. Staff manage these under **Manage nodes** on the DICOM Server page.

For each node you set:

* **Name** — a friendly label, like "Hospital PACS"
* **AE Title**, **Host** and **Port** — how to reach it
* **Active** — untick to pause a node without deleting it
* **Prefer C-GET** — tick this when the remote system cannot open a connection back to this server, for example when this server is behind a firewall or NAT. C-MOVE (the default) needs two things on the remote side: this server's AE title registered as a destination, and a network path back to this server's port. When in doubt, tick it.

The **Echo** button next to each node tests the connection — use it after adding a node to check the details are right. The **Test Q/R capabilities** button (checklist icon) goes further: it reports which of C-FIND, C-MOVE and C-GET the remote system actually supports, so you can set **Prefer C-GET** correctly. Some systems — treatment machines and data-management systems in particular — are storage-only: they can receive scans sent to them but cannot be queried or fetched from. The capability test reports these as "negotiated but aborts queries"; for those, arrange for the system to *push* scans to this server's AE title instead.

Fetching scans automatically
-----------------------------

Each node can be told to check for new scans on its own:

* Tick **automatic retrieval** on the node.
* Set the schedule using the five time fields (minute, hour, day of week, day of month, month). The default, ``0 22 * * *``, means "every night at 10pm". An asterisk means "every".
* **Minimum interval** stops the same patient being checked too often.
* **Batch size** controls how many patients are handled in one go — leave it unless the system feels slow.

When a patient's consent is first recorded, the system also fetches their scans right away from every active, automatic node.

Patient ID aliases
-------------------

Hospitals sometimes use a different ID for the same patient on their imaging system. An **alias** tells this server "patient X here is patient Y over there". Aliases are managed in the admin area, on the remote node or the patient record — the fetch will then also look for the other ID.

Received scans
---------------

Every scan that arrives is recorded and can be seen in the admin area, including ones that were turned away. This is the place to check if a scan you expected never showed up.

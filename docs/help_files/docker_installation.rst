Docker Installation Method
=============================

This method will install the Chavi application using Docker containers.

Prerequisites
----------------
Docker Desktop:

- Docker Desktop is a platform for building, shipping, and running applications using containers.
- It provides a container runtime, a command line interface, and a platform for building and shipping containerized applications.
- It is available for Windows and macOS.

Please refere to the official Docker documentation for installation instructions:

- `Docker Desktop for Windows <https://docs.docker.com/desktop/install/windows-install/>`_
- `Docker Desktop for macOS <https://docs.docker.com/desktop/install/mac-install/>`_


After Docker Desktop is installed, you can start the Docker application. Please ensure that proxy settings are configured correctly in the Docker Desktop settings. Without this Docker Desktop will not be able to access the internet.

Installation
---------------

Create a folder in a location where the CHAVI client application will be installed.
Inside this folder, create the following three files:

- .env
- docker-compose.yml
- ngnix.conf

The contents of the files are as follows:

.. literalinclude:: ../../docker_install/example_docker-compose.yml
   :language: yaml
..
.. literalinclude:: ../../docker_install/example_nginx.conf
   :language: bash
..
.. literalinclude:: ../../docker_install/example_.env
   :language: bash
..

After these files have been created you can start editing the .env file. Ensure that the password fields are properly set. If a proxy is used for network access, please ensure that the proxy settings are configured correctly in the .env file.

After the .env file has been edited, you can start the Docker containers by running the following command:

.. code-block:: bash

   docker-compose up -d
..

Updating the Software
----------------------

Before any update, please take a backup of the database. To do so please refer to the :doc:`database_backup` page.

Stop all running containers in the Docker Desktop application.

After the backup has been taken, you will have to delete the old image and pull the new image. 

In Docker desktop, please go to the images section and delete the old image for the CHAVI client. After this is deleted, we would suggest also that you delete the volume created for the chaviclient. However DO NOT delete the volume created for the database. 

Once this is done you can pull the new image by running the following command:

.. code-block:: bash

   docker-compose pull
..

After the image has been pulled, you can start the containers by running the following command:

.. code-block:: bash

   docker-compose up -d
..

DICOM Query/Retrieve Networking
--------------------------------

The ``chaviclient-dicom`` container only runs the **inbound** DICOM service
(C-ECHO / C-STORE / C-FIND) on published port ``11112``. All **outbound**
Query/Retrieve connections to remote DICOM nodes are opened by the
``chaviclient-celery-worker`` container (retrieval jobs) and the
``chaviclient-django`` container (the C-ECHO test button on the Remote nodes
page).

* Outbound connections need no compose changes — the worker only needs to
  reach each remote node's ``host:port`` (LAN IP or public hostname).
* **C-MOVE** additionally requires the remote PACS to connect back to the
  Docker host on port ``11112`` — the host firewall must allow it and the
  PACS-side destination for our AE title must point at the host IP.
* **C-GET** (``prefer C-GET`` on the remote node) receives instances over the
  same outbound association, so use it when the Docker host is behind NAT or
  the remote cannot connect back.
* The published port must match the listen port configured at
  ``/dicom-server/config/`` and ``bind_address`` must remain ``0.0.0.0``.

See ``docker_install/README.md`` in the repository for the full networking
table and verification commands.

DICOM Archive Storage (NAS/LAN)
---------------------------------

If you use the DICOM Archive (see :doc:`dicom_archive`), remember that the
app's media root inside the containers is ``/app/media`` and study folders
live at ``/app/media/processed_dicom/<patient ID>/<study UID>``. A location's
path is therefore always a path **inside the containers** — the host path you
mount determines what it points at on disk. Three common setups:

* **Another folder in the app's media volume** — no compose change. Create the
  location with a relative path, for example ``dicom_archive``; it resolves to
  ``/app/media/dicom_archive`` (host: ``<compose dir>/media/dicom_archive``).
  Caveat: the archive then lives on the same physical disk as the source data.

* **NAS/LAN share mounted on the Docker host** — mount the share on the host
  first (NFS or SMB, for example at ``/mnt/nas/chavi-archive``), then add the
  bind mount to the ``volumes:`` of **both** ``chaviclient-celery-worker`` and
  ``chaviclient-django``::

    volumes:
      - chaviclient_app_data:/app
      - ./media:/app/media
      - /mnt/nas/chavi-archive:/archive/dicom

  Create the location with type *Mounted share* and path ``/archive/dicom``.

  .. warning::
     ``/archive/dicom`` inside the containers does **not** need to be created
     beforehand — the app creates it (with a write probe) when the location
     is saved, and again at the start of every archive run. But the *host*
     side needs a check: if ``/mnt/nas/chavi-archive`` does not exist on the
     Docker host, Docker silently creates it as an empty directory and mounts
     **that** — archiving then succeeds, but the data lands on the host disk
     instead of the NAS. Before starting the containers, confirm the share is
     really mounted on the host (``df -h /mnt/nas/chavi-archive`` should show
     the NAS, and on Windows the SMB share must be reachable); after start,
     ``docker-compose exec chaviclient-celery-worker ls -ld /archive/dicom``
     should show the share, not an empty fresh directory.

* **Windows host with an SMB share (Docker Desktop)** — bind the UNC path
  directly, no host-side mount needed, again in **both** services::

    volumes:
      - //NAS_HOST/chavi-archive:/archive/dicom

  Create the location with type *Mounted share* and path ``/archive/dicom``.

The ``chaviclient-django`` (web) container needs the mount too: when a location
is saved, the form probes the path for write access in the web container — a
path mounted only in the worker fails that validation with "location path is
not writable". The actual archiving and de-archiving run in
``chaviclient-celery-worker``; ``chaviclient-celery-beat`` only dispatches the
scheduled sweep and ``chaviclient-dicom`` never touches the archive path, so
neither of them needs the mount.

Verification after a change::

   docker-compose exec chaviclient-celery-worker ls /archive/dicom

then create the mounted location in the UI (it must pass validation), archive
one study, and confirm the files under the share::

   docker-compose exec chaviclient-celery-worker find /archive/dicom -name '*.dcm' | head

When the "delete local copy after archiving" option is on, the study's folder
under ``/app/media/processed_dicom`` disappears after the archive succeeds; de-
archiving restores it to the original path.



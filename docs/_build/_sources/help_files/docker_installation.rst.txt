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

Background Task Workers
-----------------------

Two Celery workers process background jobs:

* ``chaviclient-celery-worker`` — general tasks (DICOM retrieval, ZIP and
  clinical data downloads, archive sweeps, scheduled jobs). Runs with two
  slots (``--concurrency=2``) on the ``default`` queue.
* ``chaviclient-celery-deid-worker`` — deidentification only. Runs with a
  single slot (``--concurrency=1``) on the dedicated ``deid`` queue, so
  deidentification batches are processed strictly one after another, even
  when several patients are de-identified at the same time. This keeps
  memory and CPU use in check: only one copy of the text-detection models
  is loaded at a time.

A de-identification job started while another is already running waits in
the queue; its task run shows no progress until the running batch
finishes. Upgrading the software replaces both workers at once, and any
interrupted de-identification run resumes from where it left off.

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
path is therefore always a path **inside the containers** — what it points
at on disk depends on how the storage is mounted. Four common setups:

* **Another folder in the app's media volume** — no compose change. Create the
  location with a relative path, for example ``dicom_archive``; it resolves to
  ``/app/media/dicom_archive`` (host: ``<compose dir>/media/dicom_archive``).
  Caveat: the archive then lives on the same physical disk as the source data.

* **NAS/LAN share mounted on the Docker host** — mount the share on the host
  first (NFS or SMB, for example at ``/mnt/nas/chavi-archive`` — when you put
  the mount in ``/etc/fstab``, use the ``_netdev`` option so the mount waits
  for the network), then add the bind mount to the ``volumes:`` of
  ``chaviclient-celery-worker``, ``chaviclient-celery-deid-worker`` and
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
  directly, no host-side mount needed, again in all three services::

    volumes:
      - //NAS_HOST/chavi-archive:/archive/dicom

  Create the location with type *Mounted share* and path ``/archive/dicom``.

* **Docker-managed share volume — no host-side mount at all** — Docker itself
  mounts the share as a named volume; the credentials and the share path come
  from ``.env``. ``example_docker-compose.yml`` contains this ready to
  uncomment. Mount the volume as ``chaviclient_archive:/archive/dicom`` in
  the main worker, the deid worker and the web service (commented lines
  are included in the example compose), then create the location with type
  *Mounted share* and path ``/archive/dicom``.

  **SMB/CIFS share** (works on Linux hosts and Docker Desktop on Windows)::

    volumes:
      chaviclient_archive:
        driver_opts:
          type: cifs
          o: "username=${NETWORK_USER},domain=${NETWORK_DOMAIN},password=${NETWORK_PASSWORD},rw,uid=0,gid=0,file_mode=0666,dir_mode=0777"
          device: ${NETWORK_PATH}        # e.g. //nas.example.com/chavi-archive

  with ``NETWORK_USER``, ``NETWORK_DOMAIN``, ``NETWORK_PASSWORD`` and
  ``NETWORK_PATH`` in ``.env`` (keep the ``.env`` at permissions ``600`` and
  never commit it). If the NAS only speaks SMB and the mount fails silently,
  add ``vers=3.0`` (or ``vers=2.1``) to the ``o:`` options and make sure the
  CIFS client is installed on a Linux host (``apt-get install cifs-utils``;
  Docker Desktop on Windows needs nothing extra).

  Hardening variant: instead of putting the username and password in the
  compose options, keep them in a credentials file on the Docker host —
  ``/etc/docker-smb-credentials`` containing ``username=``, ``password=`` and
  ``domain=``, set to ``chmod 600`` — and use
  ``o: "credentials=/etc/docker-smb-credentials,rw,uid=0,gid=0,file_mode=0666,dir_mode=0777"``.

  **NFS share** (Linux hosts; the host needs the NFS client —
  ``apt-get install nfs-common`` on Debian/Ubuntu, ``dnf install nfs-utils``
  on RHEL-based distros)::

    volumes:
      chaviclient_archive:
        driver: local
        driver_opts:
          type: nfs
          o: addr=192.168.1.100,nfsvers=4.1,hard,noatime
          device: ":/volume1/chavi-archive"

  ``hard`` (the default) retries I/O forever — data-integrity safe, but a
  dead NAS will stall archive operations; use ``soft`` instead if you would
  rather have the archive task fail per-study than block, which this
  application is built to record and recover from. ``noatime`` skips
  access-time updates and is a small performance win for large file copies.

  **A specific local folder** (e.g. the archive lives on ``D:\chavi-archive``
  with Docker Desktop on Windows, or a data disk on a Linux host)::

    volumes:
      chaviclient_archive:
        driver: local
        driver_opts:
          o: bind
          type: none
          device: "D:/chavi-archive"

  .. note::
     ``uid=0,gid=0`` with ``file_mode=0666,dir_mode=0777`` in the CIFS
     example is deliberate: this image runs the app as a non-root system user
     (``appuser``) whose uid is *not* pinned, so the share must be
     world-writable **inside the container** — check yours with
     ``docker compose exec chaviclient-django id``. Do not use
     ``uid=1000,gid=1000`` (a common copy-paste) unless the app really runs
     as uid 1000; with ``dir_mode=0770`` that user would not be able to
     write the share at all. Access to the share itself remains protected by
     the SMB/NFS credentials either way, and the only processes in these
     containers are Django and Celery.

  Caveats of Docker-managed shares:

  * ``driver_opts`` are fixed when the volume is *created*. To change the
    options, remove the volume first (``docker volume rm chaviclient_archive``)
    and start again — only Docker's mount metadata is removed, the data on
    the share itself is untouched.
  * If the share is unreachable when the containers start, the volume mount
    fails and the containers will not start. Start the stack with the NAS up;
    after a NAS reboot that happened while the stack was running, restart the
    containers (``docker compose down && docker compose up -d``) if mounts
    have gone stale ("Host is down").

The ``chaviclient-django`` (web) container needs the mount too: when a location
is saved, the form probes the path for write access in the web container — a
path mounted only in the workers fails that validation with "location path is
not writable". The actual archiving runs in ``chaviclient-celery-worker``,
while de-archival restore (before de-identification starts, and the
per-study safety net during a run) executes inside deidentification tasks on
``chaviclient-celery-deid-worker`` — so all three need the mount.
``chaviclient-celery-beat`` only dispatches the scheduled sweep and
``chaviclient-dicom`` never touches the archive path, so neither of them needs
the mount.

Verification after a change::

   docker-compose exec chaviclient-celery-worker ls /archive/dicom

then create the mounted location in the UI (it must pass validation) — or
better, press the **Test location** button, which writes a small
``chavi_archive_write_test.txt`` you can open on the share to prove the write
landed there — then archive one study, and confirm the files under the share::

   docker-compose exec chaviclient-celery-worker find /archive/dicom -name '*.dcm' | head

When the "delete local copy after archiving" option is on, the study's folder
under ``/app/media/processed_dicom`` disappears after the archive succeeds; de-
archiving restores it to the original path.



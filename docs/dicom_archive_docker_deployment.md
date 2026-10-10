# DICOM Archive — Docker deployment

CHAVI Client containers run with `BASE_DIR=/app` and `MEDIA_ROOT=/app/media`.
In `docker_install/example_docker-compose.yml`, `./media` (relative to the
compose project directory on the Docker host) is bind-mounted to
`/app/media` in every app container, so a study's `folder_path` is

    /app/media/processed_dicom/<patient_id>/<study_uid>

inside the container and `<compose-dir>/media/processed_dicom/...` on the
host. **`ArchiveLocation.path` is always a path inside the container.**

## Scenario 1 — another folder inside the app's media volume

No compose change. Create a location with a relative path:

    name: media-archive, storage_type: LOCAL, path: dicom_archive

→ resolves to `/app/media/dicom_archive` (host: `<compose-dir>/media/dicom_archive`).
Caveat: same physical disk as the source data.

## Scenario 2 — NAS/LAN drive mounted on the Docker host

Mount the share on the host first (NFS or SMB, e.g. `/mnt/nas/chavi-archive`),
then add the bind mount to the `volumes:` of BOTH `chaviclient-celery-worker`
and `chaviclient-django`:

    volumes:
      - chaviclient_app_data:/app
      - ./media:/app/media
      - /mnt/nas/chavi-archive:/archive/dicom

Create the location with: `name: nas-archive, storage_type: MOUNT,
path: /archive/dicom`.

**Gotcha — the container path is auto-created, the host mount is not.**
`/archive/dicom` does not need to exist beforehand: the app creates it (with
a write probe) when the location is saved and again at the start of every
archive run. The danger is on the host: if `/mnt/nas/chavi-archive` does not
exist when the container starts, Docker silently creates it as an empty
directory and mounts *that* — archiving then "works" but the data lands on
the host disk instead of the NAS. Before starting the containers, verify the
share is really mounted on the host (`df -h /mnt/nas/chavi-archive` shows the
NAS; on Windows the SMB share is reachable). After start, `docker compose exec
chaviclient-celery-worker ls -ld /archive/dicom` should show the share, not an
empty fresh directory.

## Scenario 3 — Windows host with an SMB share (Docker Desktop)

Bind the UNC path directly (no host-side mount needed), again in BOTH
`chaviclient-celery-worker` and `chaviclient-django`:

    volumes:
      - //NAS_HOST/chavi-archive:/archive/dicom

Create the location with: `name: nas-archive, storage_type: MOUNT,
path: /archive/dicom`.

## Scenario 4 — Docker-managed share volume (no host-side mount)

Docker itself mounts the share as a named volume; credentials and the share
path come from `.env`. `docker_install/example_docker-compose.yml` contains
these ready to uncomment — mount the volume as
`chaviclient_archive:/archive/dicom` in BOTH the worker and the web service
(commented lines are in the example compose), then create the location with
path `/archive/dicom`.

**SMB/CIFS** (Linux hosts and Docker Desktop on Windows):

    volumes:
      chaviclient_archive:
        driver_opts:
          type: cifs
          o: "username=${NETWORK_USER},domain=${NETWORK_DOMAIN},password=${NETWORK_PASSWORD},rw,uid=0,gid=0,file_mode=0666,dir_mode=0777"
          device: ${NETWORK_PATH}        # e.g. //nas.example.com/chavi-archive

`NETWORK_USER`, `NETWORK_DOMAIN`, `NETWORK_PASSWORD`, `NETWORK_PATH` live in
`.env` (permissions 600, never committed). If the mount fails silently,
add `vers=3.0` (or `vers=2.1`) to `o:` and ensure the CIFS client is
installed on Linux hosts (`apt-get install cifs-utils`; Docker Desktop on
Windows needs nothing extra). Hardening variant: keep the credentials in a
file on the host (`/etc/docker-smb-credentials` with `username=`,
`password=`, `domain=`, chmod 600) and use
`o: "credentials=/etc/docker-smb-credentials,rw,uid=0,gid=0,file_mode=0666,dir_mode=0777"`.

**NFS** (Linux hosts; `apt-get install nfs-common` / `dnf install nfs-utils`):

    volumes:
      chaviclient_archive:
        driver: local
        driver_opts:
          type: nfs
          o: addr=${NAS_IP},nfsvers=4.1,hard,noatime
          device: ":${NAS_PATH}"          # e.g. :/volume1/chavi-archive

`hard` (default) retries I/O forever — integrity-safe, but a dead NAS stalls
archive operations; `soft` makes I/O return errors so the archive task fails
per-study instead of blocking. `noatime` is a small performance win for
large file copies.

**A specific local folder** (e.g. `D:\chavi-archive` on a Windows host):

    volumes:
      chaviclient_archive:
        driver: local
        driver_opts:
          o: bind
          type: none
          device: "D:/chavi-archive"

**Why `uid=0,gid=0` + `0666/0777` (and not the common `uid=1000,gid=1000`).**
This image runs the app as a non-root system user (`appuser`) whose uid is
*not pinned* — check with `docker compose exec chaviclient-django id`. With
`uid=1000,gid=1000,dir_mode=0770` the app user would not be able to write the
share at all. `uid=0,gid=0` with world-rw modes inside the container is
harmless here (only Django/Celery run in these containers) and the share
itself stays protected by the SMB/NFS credentials. Do **not** pin
`appuser` to uid 1000 in the Dockerfile to "fix" the mapping: existing
deployments' `app_data` volume and `./media` bind are owned by the current
uid and would become unwritable after the rebuild.

Caveats:

- `driver_opts` are fixed when the volume is *created*. To change options:
  `docker volume rm chaviclient_archive` and start again (only Docker's mount
  metadata is removed; the data on the share is untouched).
- If the share is unreachable when the containers start, the mount fails and
  the containers will not start. After a NAS reboot, restart the stack
  (`docker compose down && docker compose up -d`) if mounts have gone stale
  ("Host is down").

## Why the django container needs the mount too

`ArchiveLocationForm.clean()` calls `prepare_location()`, which creates the
directory and probes it for write permission — that runs in the web
container (`chaviclient-django`) when the location form is submitted. If the
path is only mounted in the worker, location creation fails validation with
"location path is not writable".

`chaviclient-celery-beat` only dispatches `task_scheduled_archive` (no file
I/O) and `chaviclient-dicom` (SCP ingest) never touches the archive path —
neither needs the mount.

## Verification

1. `docker compose exec chaviclient-celery-worker ls /archive/dicom` lists the share.
2. In the UI, create the MOUNT location — the form validates without error.
3. Archive one study manually; `docker compose exec chaviclient-celery-worker find /archive/dicom -name '*.dcm' | head` shows the files, and the study's local folder under `/app/media/processed_dicom` is gone when `delete_local_after_archive` is on.
4. De-archive the study; files return under the original `folder_path`.

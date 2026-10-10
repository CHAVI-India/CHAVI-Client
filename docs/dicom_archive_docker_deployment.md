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

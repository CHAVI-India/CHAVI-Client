# Deid Dedicated Celery Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serialize all deidentification batches across the whole deployment by routing the deid chain tasks to a dedicated `deid` Celery queue consumed by a single-concurrency worker, so concurrent deid runs (e.g. two patients) no longer run in parallel fork-pool children loading duplicate EasyOCR + Stanford NER models.

**Architecture:** `CELERY_TASK_ROUTES` sends the three deid chain tasks (bulk dispatcher, per-study link, finalize) to queue `deid`. A new `chaviclient-celery-deid-worker` container consumes only that queue with `--concurrency=1`; the existing main worker is pinned to `-Q default` so it stops being able to consume `deid`. Strictly FIFO serial deid across batches; retrieval/zip/beat workloads keep their two main-worker slots. Sphinx help docs under `docs/help_files/` are updated to match (worker split, archive mount now needed on three services, user-visible queuing note).

**Tech Stack:** Django 5.1 settings, Celery 5 (prefork, RabbitMQ broker, django-db results), docker compose.

**Spec:** Conversation requirements — (1) deid chains must be globally serial, not just serial within one batch; (2) no new feature settings other than the routing entry; (3) the deployment target is `docker_install/example_docker-compose.yml`.

## Global Constraints

- Exactly two new settings entries in `chavi_client/settings.py`: `CELERY_TASK_QUEUES` (declared `default` + durable `deid` queues as real `kombu.Queue` objects — Celery 5.6.3's Django config loader copies the value verbatim and `app.amqp.queues` requires Queue objects; callable references are NOT evaluated) and `CELERY_TASK_ROUTES` (queue routing). No `DEID_*` or other new settings.
- `chavi_client/celery.py` is unchanged (the app already loads settings via `config_from_object` with the `CELERY` namespace).
- Only these three task names route to `deid`:
  `deidentification.tasks.deidentify_dicom_studies_bulk_task`,
  `deidentification.tasks.deidentify_dicom_study_task`,
  `deidentification.tasks.finalize_deidentification_batch_task`.
  All other `deidentification.tasks.*` (zip builds, legacy import, create_missing_records) stay on `default`.
- Main worker stays `--concurrency=2`; deid worker is `--concurrency=1`.
- `CELERY_TASK_DEFAULT_QUEUE = 'default'` is unchanged.
- No migrations, no model changes.
- Python for all commands: `venv/bin/python` from repo root `/mnt/share/CHAVI-Client`.

---

### Task 1: Route the deid chain tasks to the `deid` queue

**Files:**
- Modify: `chavi_client/settings.py` (insert after the `CELERY_TASK_DEFAULT_QUEUE = 'default'` line, ~line 930)
- Test: `deidentification/tests.py` (append a new `SimpleTestCase` class)

**Interfaces:**
- Consumes: existing Celery app `chavi_client.celery.app` (built via `config_from_object("django.conf:settings", namespace="CELERY")`), and the three shared tasks in `deidentification/tasks.py`.
- Produces: `settings.CELERY_TASK_ROUTES: dict[str, dict]` mapping the three task names to `{'queue': 'deid'}`. Task 2's compose file relies on the queue being named exactly `deid`.

- [ ] **Step 1: Write the failing test**

Append to `deidentification/tests.py`:

```python
class DeidQueueRoutingTests(SimpleTestCase):
    """Deid chain tasks route to the dedicated 'deid' queue so a
    single-concurrency worker serializes deidentification across batches."""

    def _route_queue(self, task_name):
        from celery.app.routes import Router, prepare

        from chavi_client.celery import app

        router = Router(prepare(app.conf.task_routes), dict(app.amqp.queues), app=app)
        route = router.route({}, task_name)
        queue = route.get('queue')
        return getattr(queue, 'name', queue)

    def test_deid_chain_tasks_route_to_deid_queue(self):
        for name in (
            'deidentification.tasks.deidentify_dicom_studies_bulk_task',
            'deidentification.tasks.deidentify_dicom_study_task',
            'deidentification.tasks.finalize_deidentification_batch_task',
        ):
            self.assertEqual(self._route_queue(name), 'deid', name)

    def test_other_deid_tasks_stay_on_default_queue(self):
        for name in (
            'deidentification.tasks.build_dicom_download_zip_task',
            'deidentification.tasks.import_legacy_mapping_task',
        ):
            self.assertEqual(self._route_queue(name), 'default', name)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python manage.py test deidentification.tests.DeidQueueRoutingTests --noinput`
Expected: FAIL — with the queues undeclared, Celery 5.6 raises `QueueNotFound: "Queue 'default' missing from task_queues"`; that failure confirms the test exercises real routing resolution.

- [ ] **Step 3: Add the queue and routing settings**

In `chavi_client/settings.py`, add `from kombu import Queue as _KombuQueue` to the imports at the top of the file, and insert immediately after `CELERY_TASK_DEFAULT_QUEUE = 'default'  # Default queue name`:

```python
# Declared queues. 'deid' is consumed by the dedicated single-slot worker
# (chaviclient-celery-deid-worker in docker_install/example_docker-compose.yml)
# so deidentification batches are strictly serial across the deployment —
# concurrent batches must not load duplicate EasyOCR + NER model stacks in
# parallel worker children. Durable so long deid links survive a broker
# restart. 'default' keeps the kombu default (durable), matching the queue
# the workers have always used. Must be actual kombu.Queue objects (the
# Django config loader copies the value verbatim — no callables).
CELERY_TASK_QUEUES = {
    'default': _KombuQueue('default'),
    'deid': _KombuQueue('deid', durable=True),
}
# Deid chain tasks run on the dedicated 'deid' queue (see above).
CELERY_TASK_ROUTES = {
    'deidentification.tasks.deidentify_dicom_studies_bulk_task': {'queue': 'deid'},
    'deidentification.tasks.deidentify_dicom_study_task': {'queue': 'deid'},
    'deidentification.tasks.finalize_deidentification_batch_task': {'queue': 'deid'},
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/bin/python manage.py test deidentification.tests.DeidQueueRoutingTests --noinput`
Expected: PASS (2 tests).

If the router call does not behave as expected on this Celery version (Celery 5.6.3 has no `app.router` attribute — build a `Router` from `app.conf.task_routes` as shown above), adjust the helper only; keep both test methods asserting the same queues.

- [ ] **Step 5: Run the full deidentification suite for regressions**

Run: `venv/bin/python manage.py test deidentification --noinput`

Expected: all tests OK.

Note: test-DB creation can fail with `HTTP Error 429` — the `lookup` migrations download 56 CSVs from GitLab which rate-limits this host. If that happens, rebuild the cache and use the redirect runner:

```bash
# one-time cache (55 unique URLs, ~10 min paced to avoid 429):
grep -h "gitlab.com" lookup/migrations/*.py | grep -o "https://gitlab.com/drsantam/chavi-lookup-data/[^'\" ]*" | sort -u > /tmp/lookup_urls.txt
venv/bin/python /tmp/fetch_lookup_cache.py   # fetcher script from the earlier session; re-create if lost
curl -sf "https://gitlab.com/drsantam/chavi-lookup-data/-/raw/d61d4f5519eb6924737bbb592195d3a82ee8710b/lookup_datasets/laterality.csv?inline=false" -o /tmp/lookup_csv_cache/laterality.csv
# run tests with pandas.read_csv redirected to the cache:
venv/bin/python /tmp/run_deid_tests.py deidentification
```

`/tmp/run_deid_tests.py` (re-create if lost):

```python
import os, sys
sys.path.insert(0, '/mnt/share/CHAVI-Client')
os.chdir('/mnt/share/CHAVI-Client')
import django, pandas as pd

def _cached_read_csv(filepath_or_buffer, *args, **kwargs):
    if isinstance(filepath_or_buffer, str) and 'gitlab.com/drsantam/chavi-lookup-data' in filepath_or_buffer:
        name = filepath_or_buffer.split('/')[-1].split('?')[0]
        return pd.read_csv(os.path.join('/tmp/lookup_csv_cache', name), *args, **kwargs)
    return _orig_read_csv(filepath_or_buffer, *args, **kwargs)
_orig_read_csv = pd.read_csv
pd.read_csv = _cached_read_csv

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')
django.setup()
from django.test.utils import get_runner
from django.conf import settings
runner = get_runner(settings)(verbosity=1, interactive=False)
sys.exit(bool(runner.run_tests(sys.argv[1:] or ['deidentification'])))
```

- [ ] **Step 6: Commit**

```bash
git add chavi_client/settings.py deidentification/tests.py
git commit -m "feat: route deid chain tasks to dedicated 'deid' celery queue"
```

---

### Task 2: Dedicated deid worker in the example compose file (+ README)

**Files:**
- Modify: `docker_install/example_docker-compose.yml`
- Modify: `docker_install/README.md`

**Interfaces:**
- Consumes: queue name `deid` produced by Task 1's `CELERY_TASK_ROUTES`; the existing `chaviapp/chaviclient:main` image (worker and app share it, so routing config and consumer appear in the same upgrade).
- Produces: services `chaviclient-celery-deid-worker` (consumes `deid`, `-c 1`) and main `chaviclient-celery-worker` pinned to `-Q default`.

- [ ] **Step 1: Pin the main worker to the default queue**

In `docker_install/example_docker-compose.yml`, in service `chaviclient-celery-worker`, change the command line:

```yaml
    command: ["celery", "-A", "chavi_client", "worker", "-l", "info", "--concurrency=2"]
```

to:

```yaml
    command: ["celery", "-A", "chavi_client", "worker", "-l", "info", "-Q", "default", "--concurrency=2"]
```

- [ ] **Step 2: Add the dedicated deid worker service**

Insert a new service directly after the `chaviclient-celery-worker` block (before `chaviclient-celery-beat`):

```yaml
  # Deidentification runs on its own queue with a single worker slot so all
  # deid batches are strictly serial across the deployment (see
  # CELERY_TASK_ROUTES in chavi_client/settings.py). Must be upgraded in the
  # same step as the app image: without it, deid tasks publish to the 'deid'
  # queue and are never consumed.
  chaviclient-celery-deid-worker:
    image: chaviapp/chaviclient:main
    container_name: chaviclient-celery-deid-worker
    restart: always
    depends_on:
      chaviclient-database:
        condition: service_healthy
      chaviclient-rabbitmq:
        condition: service_healthy
    env_file:
      - .env
    volumes:
      - chaviclient_app_data:/app
      - ./media:/app/media
      - ./static:/app/static
      - ./logs:/app/logs
      # DICOM archive (optional — same mount path as the other workers;
      # de-archival restore runs in-process inside deid tasks, so this
      # worker needs it too. Uncomment together with one of the
      # chaviclient_archive definitions in the top-level volumes: section):
      # - chaviclient_archive:/archive/dicom
    command: ["celery", "-A", "chavi_client", "worker", "-l", "info", "-Q", "deid", "--concurrency=1"]
```

(The optional-archive line mirrors the main worker's commented line; the archive is required by the de-archival restore that runs inside the dispatcher and per-study link tasks, which now live on this worker.)

- [ ] **Step 3: Validate the compose file**

Run: `venv/bin/python -c "import yaml; d = yaml.safe_load(open('docker_install/example_docker-compose.yml')); s = d['services']; assert s['chaviclient-celery-deid-worker']['command'][-3:] == ['-Q', 'deid', '--concurrency=1']; assert '-Q' in s['chaviclient-celery-worker']['command']; print('compose ok')"`

Expected: `compose ok`. (If `docker compose` is available on the host, additionally run `docker compose -f docker_install/example_docker-compose.yml config -q` — note the example file's relative `.env`/`nginx.conf` references may not exist in this checkout, so the YAML parse is the authoritative check.)

- [ ] **Step 4: Update the README service tables**

In `docker_install/README.md`:

1. In the first services table (row `| chaviclient-celery-worker | Celery worker for asynchronous task processing |`, ~line 27), add a row directly after it:

```markdown
| chaviclient-celery-deid-worker | Dedicated deidentification worker (queue `deid`, concurrency 1 — all deid batches run strictly serial) |
```

2. In the responsibilities table (the row about `chaviclient-celery-worker` opening TCP associations, ~line 118), add a row directly after it:

```markdown
| `chaviclient-celery-deid-worker` | **Deidentification.** Consumes only the `deid` queue at concurrency 1, so deid batches from different patients/runs are serialized and a single EasyOCR + NER model stack is loaded. Runs the de-archival restore in-process — needs the DICOM archive mount if archival is in use. |
```

- [ ] **Step 5: Re-run the deid test suite (routing still intact)**

Run: `venv/bin/python manage.py test deidentification --noinput` (or the cache-redirect runner from Task 1 Step 5 if the 429 recurs)
Expected: all tests OK.

- [ ] **Step 6: Commit**

```bash
git add docker_install/example_docker-compose.yml docker_install/README.md
git commit -m "feat: add dedicated single-slot deid celery worker to example compose"
```

---

### Task 3: Update the Sphinx docs (`docs/help_files/`)

**Files:**
- Modify: `docs/help_files/docker_installation.rst`
- Modify: `docs/help_files/dicom_archive.rst`
- Modify: `docs/help_files/deidentification.rst`

**Interfaces:**
- Consumes: the worker layout produced by Task 2 (main worker `-Q default -c 2`, deid worker `-Q deid -c 1`, archive mount needed on both workers + django).
- Produces: documentation consistent with the compose file; the compose file itself is embedded verbatim in `docker_installation.rst` via `literalinclude`, so no compose copy exists in the docs to keep in sync.

- [ ] **Step 1: Add a worker overview section to `docker_installation.rst`**

In `docs/help_files/docker_installation.rst`, insert a new section between the "Updating the Software" section and the "DICOM Query/Retrieve Networking" section:

```rst
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
```

- [ ] **Step 2: Fix the archive-mount statements in `docker_installation.rst`**

The archive is now touched by three containers, not two (de-archival restore runs in-process inside deid tasks on the deid worker). Make these edits:

1. The bullet "NAS/LAN share mounted on the Docker host" — change:

```rst
  first (NFS or SMB, for example at ``/mnt/nas/chavi-archive`` — when you put
  the mount in ``/etc/fstab``, use the ``_netdev`` option so the mount waits
  for the network), then add the bind mount to the ``volumes:`` of **both**
  ``chaviclient-celery-worker`` and ``chaviclient-django``::
```

to:

```rst
  first (NFS or SMB, for example at ``/mnt/nas/chavi-archive`` — when you put
  the mount in ``/etc/fstab``, use the ``_netdev`` option so the mount waits
  for the network), then add the bind mount to the ``volumes:`` of
  ``chaviclient-celery-worker``, ``chaviclient-celery-deid-worker`` and
  ``chaviclient-django``::
```

2. The bullet "Windows host with an SMB share (Docker Desktop)" — change "directly, no host-side mount needed, again in **both** services::" to:

```rst
  directly, no host-side mount needed, again in all three services::
```

3. The bullet "Docker-managed share volume — no host-side mount at all" — change:

```rst
  uncomment. Mount the volume as ``chaviclient_archive:/archive/dicom`` in
  **both** the worker and the web service (commented lines are included in
  the example compose), then create the location with type *Mounted share*
  and path ``/archive/dicom``.
```

to:

```rst
  uncomment. Mount the volume as ``chaviclient_archive:/archive/dicom`` in
  the main worker, the deid worker and the web service (commented lines
  are included in the example compose), then create the location with type
  *Mounted share* and path ``/archive/dicom``.
```

4. The paragraph after the share-volume bullets — change:

```rst
The ``chaviclient-django`` (web) container needs the mount too: when a location
is saved, the form probes the path for write access in the web container — a
path mounted only in the worker fails that validation with "location path is
not writable". The actual archiving and de-archiving run in
``chaviclient-celery-worker``; ``chaviclient-celery-beat`` only dispatches the
scheduled sweep and ``chaviclient-dicom`` never touches the archive path, so
neither of them needs the mount.
```

to:

```rst
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
```

5. The two verification commands (`docker-compose exec chaviclient-celery-worker ls /archive/dicom` and the `find ... -name '*.dcm'` one) stay as-is — the main worker is a valid place to check the share.

- [ ] **Step 3: Fix the "both services" statements in `dicom_archive.rst`**

In `docs/help_files/dicom_archive.rst`, in the "Running under Docker" section:

1. Change:

```rst
* **NAS/LAN share mounted on the Docker host** — mount it on the host (for example at ``/mnt/nas/chavi-archive``) and add the bind mount ``/mnt/nas/chavi-archive:/archive/dicom`` to **both** the ``chaviclient-celery-worker`` and ``chaviclient-django`` services; create the location with type *Mounted share* and path ``/archive/dicom``.
```

to:

```rst
* **NAS/LAN share mounted on the Docker host** — mount it on the host (for example at ``/mnt/nas/chavi-archive``) and add the bind mount ``/mnt/nas/chavi-archive:/archive/dicom`` to the ``chaviclient-celery-worker``, ``chaviclient-celery-deid-worker`` and ``chaviclient-django`` services; create the location with type *Mounted share* and path ``/archive/dicom``.
```

2. Change:

```rst
* **Windows host with an SMB share** — bind the UNC path directly (``//NAS_HOST/chavi-archive:/archive/dicom``), again in both services.
```

to:

```rst
* **Windows host with an SMB share** — bind the UNC path directly (``//NAS_HOST/chavi-archive:/archive/dicom``), again in all three services.
```

3. In the following paragraph, change "The django (web) container needs the mount too because the location form probes the path for write access when it is saved — a path mounted only in the worker fails that validation." to:

```rst
The django (web) container needs the mount too because the location form probes the path for write access when it is saved — a path mounted only in the workers fails that validation — and the deid worker needs it because de-archival restore runs inside deidentification tasks.
```

- [ ] **Step 4: Add the queuing note to `deidentification.rst`**

In `docs/help_files/deidentification.rst`, in the "The patient list" section, after the line "Each job runs in the background and appears under :doc:`Task Runs <getting_around>`." add:

```rst

De-identification runs on a dedicated single worker, so batches are always
processed one after another, in the order they were started. If you start
another batch while one is already running, the newer one waits in the
queue — its task run stays pending-looking until the running batch
finishes, then picks up automatically.
```

- [ ] **Step 5: Check the docs still build cleanly (or at least lint)**

If Sphinx is available in the venv:

Run: `venv/bin/python -m sphinx -b html docs docs/_build -q 2>&1 | tail -5`

Expected: no errors mentioning the three changed files (existing warnings may remain). If sphinx is not installed, do a manual re-read of the changed sections instead and confirm RST syntax (underline lengths match titles, literal blocks indented). Note the new section title underline must be exactly as long as "Background Task Workers" (23 characters) as written in Step 1.

- [ ] **Step 6: Commit**

```bash
git add docs/help_files/docker_installation.rst docs/help_files/dicom_archive.rst docs/help_files/deidentification.rst
git commit -m "docs: document dedicated deid worker and three-service archive mount"
```

---

## Deployment Notes (for the reviewer, not a task)

- **Docs:** `docker_installation.rst` embeds the example compose via `literalinclude`, so the new worker appears in the rendered docs automatically once Task 2 lands; Task 3 updates only the surrounding prose.
- **Upgrade order:** build/push the new `chaviapp/chaviclient:main` image, then `docker compose up -d` with the updated file. The new deid worker starts from the new image before any task is routed to `deid`; the old main worker only consumes `default`, so mixed-state windows are safe. The one unsafe state is new routing + no deid worker (deid tasks would queue forever) — avoided by the same-step upgrade.
- **Behavior:** starting deid for patient B while patient A is processing now waits in the `deid` queue (progress page for B shows no movement until A finishes). Batches 2+ FIFO.
- **In-flight tasks during upgrade:** `CELERY_TASK_ACKS_LATE` + `CELERY_TASK_REJECT_ON_WORKER_LOST` — a deid link killed mid-study is re-queued and the existing manifest/auto-continue machinery resumes it on the deid worker after restart.
- **Dev (non-Docker) mode:** two local workers are needed and each needs a distinct `-n` node name (e.g. `-n general@%h -Q default -c 2` and `-n deid@%h -Q deid -c 1`). Sharing a node name makes the second worker crash with `RESOURCE_LOCKED` on the exclusive pidbox queue. Documented in `docs/help_files/installation.rst` ("Running the Celery Workers").
- **GPU block** in the example compose stays on the main worker (deid OCR runs on CPU); if GPU OCR is ever enabled, move the `deploy.resources` block to the deid worker instead.

# DICOM Server Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the six fixes recommended in §7 of `docs/dicom_server_audit.md` (H1–H6, M1, M2, M3, M6).

**Architecture:** All outbound Q/R calls in `qr_client.py` funnel through `_connect()`, which gains a bare-TCP pre-flight (classifying DNS/refused/timeout vs DICOM reject) and a real `connection_timeout`. `echo()` returns `(ok, reason)` and every caller surfaces the reason. `find_studies_for_patient` re-raises when every PatientID fails so jobs land as FAILED. Ingest looks up studies by UID before creating and unlinks the `.dcm` on DB failure.

**Tech Stack:** Django 5.1, pynetdicom 3.0.4, Celery, unittest via `manage.py test`.

**Spec:** `docs/dicom_server_audit.md` (§5 findings, §7 fix order)

## Global Constraints

- pynetdicom 3.0.4 — `AE.connection_timeout` exists (verified) and caps the TCP connect phase.
- Test runner: `venv/bin/python manage.py test dicom_server` — loopback tests use stub pynetdicom SCPs on `127.0.0.1:0`; no external network needed.
- `echo()`'s new `tuple[bool, str]` signature ripples to `views.py`, `admin.py`, `tasks.py`, `tests/test_qr.py`, `tests/test_live.py`, and the `echo` mocks in `tests/test_frontend.py`.
- Out of scope (audit findings not in §7 — several need product decisions, e.g. M8 consent policy): M4, M5, M7–M12, L1–L8.

---

### Task 1: `echo()` returns `(ok, reason)`; `_connect()` TCP pre-flight + `connection_timeout`; move/get share `_connect()`

Audit items: §7.1 — H1, H2, M1, M2.

**Files:**
- Modify: `dicom_server/services/qr_client.py`
- Modify: `dicom_server/views.py` (`RemoteNodeEchoView.post`, ~line 117)
- Modify: `dicom_server/admin.py` (`test_echo`, ~line 59)
- Modify: `dicom_server/tasks.py` (echo gate, ~line 59)
- Test: `dicom_server/tests/test_qr.py`, `dicom_server/tests/test_frontend.py`, `dicom_server/tests/test_live.py`

**Interfaces:**
- Produces: `qr_client.echo(node) -> tuple[bool, str]` — `(True, '')` on success, `(False, '<human-readable reason>')` on failure. Callers unpack the tuple.
- Produces: `_connect(ae, node, **assoc_kwargs) -> assoc` — raises `ConnectionError` with classified cause; `assoc_kwargs` are forwarded to `ae.associate` (needed by `get_study` for `ext_neg`/`evt_handlers`).

- [ ] **Step 1: Update the failing/pending tests first**

In `dicom_server/tests/test_qr.py`, add `from unittest import mock` to imports and replace the two echo tests:

```python
    def test_echo_local(self):
        ok, reason = qr_client.echo(self._own_node())
        self.assertTrue(ok, reason)

    def test_echo_unreachable(self):
        node = self._node(port=1)  # nothing listening
        ok, reason = qr_client.echo(node)
        self.assertFalse(ok)
        self.assertTrue(reason)  # the failure reason is reported, not swallowed
```

Add a task-level test that a dead node fails the job with a reason in `error_log` (same file, end of `QRClientTests`):

```python
    def test_task_retrieve_studies_unreachable_node_fails_job(self):
        node = self._node(port=1)
        job = RetrievalJob.objects.create(node=node, patient=self.patient)
        with self.assertRaises(ConnectionError):
            task_retrieve_studies(node.pk, 'MR/25/004771', None, job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, 'FAILED')
        self.assertIn('C-ECHO', job.error_log)
```

In `dicom_server/tests/test_live.py`, update:

```python
    def test_live_echo(self):
        ok, reason = qr_client.echo(self.node)
        self.assertTrue(ok, reason)
```

In `dicom_server/tests/test_frontend.py`, update the three echo mocks:

- `test_echo_action_staff`: `@mock.patch('dicom_server.views.qr_client.echo', return_value=(True, ''))`
- `test_echo_failure_shows_error_message`: `return_value=(False, 'rejected by peer')` and add `self.assertContains(resp, 'rejected by peer')` after the existing `C-ECHO failed` assert.
- `test_echo_action_denied_for_perm_user`: `return_value=(True, '')` (mock is only asserted not-called, but keep it consistent).

- [ ] **Step 2: Run the updated tests to verify they fail**

Run: `venv/bin/python manage.py test dicom_server.tests.test_qr dicom_server.tests.test_frontend -v 1`
Expected: FAIL — `test_echo_local`/`test_echo_unreachable` raise `TypeError`/`ValueError` unpacking `bool`; frontend echo tests fail on unpacking mocks or old assertion.

- [ ] **Step 3: Implement the qr_client changes**

In `dicom_server/services/qr_client.py`:

```python
import logging
import socket
```

`_scu_ae` gains `connection_timeout` (M1 — a SYN to an unroutable IP no longer blocks ~2 min):

```python
def _scu_ae() -> AE:
    config = DICOMServerConfiguration.load()
    ae = AE(ae_title=config.ae_title)
    ae.connection_timeout = config.qr_timeout
    ae.network_timeout = config.qr_timeout
    ae.acse_timeout = config.qr_timeout
    ae.dimse_timeout = config.qr_timeout
    return ae
```

Replace `echo` and `_connect` (M2 pre-flight distinguishes DNS / refused / timeout from DICOM-layer reject):

```python
def echo(node: RemoteDICOMNode) -> tuple[bool, str]:
    """C-ECHO against a remote node.

    Returns (ok, reason): reason is '' on success, otherwise a short
    description of the failing stage (DNS, TCP connect, association
    reject/abort, or non-zero echo status).
    """
    ae = _scu_ae()
    ae.add_requested_context(Verification)
    try:
        assoc = _connect(ae, node)
    except ConnectionError as e:
        logger.warning('C-ECHO association to %s failed: %s', node, e)
        return False, str(e)
    try:
        status = assoc.send_c_echo()
        if status and status.Status == 0x0000:
            logger.info('C-ECHO %s: success', node)
            return True, ''
        reason = (
            f'C-ECHO returned status 0x{status.Status:04X}'
            if status is not None else 'C-ECHO timed out'
        )
        logger.info('C-ECHO %s: failed (%s)', node, reason)
        return False, reason
    finally:
        assoc.release()


def _connect(ae: AE, node: RemoteDICOMNode, **assoc_kwargs):
    """Open an association or raise ConnectionError with the actual cause.

    A bare TCP pre-flight runs first so DNS, refused and timeout failures are
    distinguished from DICOM-layer rejections (pynetdicom reports them all as
    'aborted'). assoc_kwargs are forwarded to AE.associate (e.g. ext_neg,
    evt_handlers for C-GET).
    """
    try:
        sock = socket.create_connection(
            (node.host, node.port), timeout=ae.connection_timeout or 30,
        )
    except socket.gaierror as e:
        raise ConnectionError(
            f'Association to {node} failed: cannot resolve {node.host!r} ({e})'
        ) from e
    except OSError as e:
        raise ConnectionError(
            f'Association to {node} failed: TCP connect to '
            f'{node.host}:{node.port} refused/timed out ({e})'
        ) from e
    else:
        sock.close()

    assoc = ae.associate(
        node.host, node.port, ae_title=node.ae_title, **assoc_kwargs,
    )
    if assoc.is_established:
        return assoc
    if assoc.is_rejected:
        detail = 'rejected by peer (check AE titles)'
    elif assoc.is_aborted:
        detail = 'aborted (connection failed or dropped)'
    elif getattr(assoc.acceptor, 'primitive', None) is not None:
        detail = 'no accepted presentation contexts (peer does not support this SOP class)'
    else:
        detail = 'rejected or timed out'
    raise ConnectionError(f'Association to {node} {detail}')
```

In `move_study`, replace the manual associate + weak check with:

```python
    assoc = _connect(ae, node)
```

In `get_study`, replace the manual associate + weak check with:

```python
    assoc = _connect(
        ae, node, ext_neg=roles,
        evt_handlers=[(evt.EVT_C_STORE, handle_store)],
    )
```

- [ ] **Step 4: Update the `echo()` callers**

`dicom_server/views.py` `RemoteNodeEchoView.post` — surface the reason:

```python
        try:
            ok, reason = qr_client.echo(node)
        except Exception as e:
            logger.exception('C-ECHO to %s failed', node)
            messages.error(request, f'{node}: C-ECHO failed — {e}')
        else:
            if ok:
                messages.success(request, f'{node}: C-ECHO succeeded')
            else:
                messages.error(request, f'{node}: C-ECHO failed — {reason}')
```

`dicom_server/admin.py` `test_echo` — unpack the tuple (reason already flows into `err`):

```python
        for node in queryset:
            try:
                ok, err = qr_client.echo(node)
            except Exception as e:
                ok, err = False, str(e)
            if ok:
                self.message_user(request, f"{node}: C-ECHO succeeded", messages.SUCCESS)
            else:
                self.message_user(request, f"{node}: C-ECHO failed {err}", messages.ERROR)
```

`dicom_server/tasks.py` echo gate — reason reaches the job `error_log` via the raise:

```python
        _update_task_run(task_run, None, 0, 100, description='Testing connectivity (C-ECHO)')
        ok, reason = qr_client.echo(node)
        if not ok:
            raise ConnectionError(f'C-ECHO to {node} failed — {reason}')
```

- [ ] **Step 5: Run the tests**

Run: `venv/bin/python manage.py test dicom_server -v 1`
Expected: PASS (all echo/find/move/get loopback tests, frontend tests).

- [ ] **Step 6: Commit**

```bash
git add dicom_server/services/qr_client.py dicom_server/views.py dicom_server/admin.py dicom_server/tasks.py dicom_server/tests/
git commit -m "fix: surface C-ECHO/association failure reasons and bound TCP connect"
```

---

### Task 2: `find_studies_for_patient` re-raises when every PatientID fails

Audit items: §7.2 — H3. Once the C-FIND that never connected raises, `task_retrieve_studies`' outer `except` already marks the job FAILED with `error_log=str(e)` — no task change needed.

**Files:**
- Modify: `dicom_server/services/qr_client.py` (`find_studies_for_patient`, ~line 117)
- Test: `dicom_server/tests/test_qr.py`

**Interfaces:**
- Consumes: `find_studies(node, pid)` from Task 1 (unchanged signature, raises `ConnectionError`).
- Produces: `find_studies_for_patient(node, patient, aliases=None) -> list[dict]` — now raises `ConnectionError` when *every* tried PatientID fails; partial failure still returns results.

- [ ] **Step 1: Write the failing tests**

In `dicom_server/tests/test_qr.py` (`mock` already imported in Task 1):

```python
    def test_find_studies_for_patient_raises_when_all_ids_fail(self):
        node = self._node(port=1)  # nothing listening
        with self.assertRaises(ConnectionError):
            qr_client.find_studies_for_patient(node, self.patient)

    @mock.patch('dicom_server.services.qr_client.find_studies')
    def test_find_studies_for_patient_partial_failure_returns_results(self, mock_find):
        def fake(node, pid):
            if pid == 'MR/25/004771':
                raise ConnectionError('dead')
            return [{'study_instance_uid': '1.2.3', 'study_date': '',
                     'study_description': '', 'modalities': 'CT', 'instances': 1}]
        mock_find.side_effect = fake
        results = qr_client.find_studies_for_patient(
            self._node(port=1), self.patient, aliases=['ALIAS'],
        )
        self.assertEqual(len(results), 1)
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python manage.py test dicom_server.tests.test_qr -v 1`
Expected: `test_find_studies_for_patient_raises_when_all_ids_fail` FAILS (no exception raised today).

- [ ] **Step 3: Implement**

```python
    seen = set()
    results = []
    errors = []
    for pid in patient_ids:
        try:
            for study in find_studies(node, pid):
                uid = study.get('study_instance_uid')
                if uid and uid not in seen:
                    seen.add(uid)
                    results.append(study)
        except Exception as e:
            logger.exception('C-FIND failed for patient ID %r on %s', pid, node)
            errors.append(f'{pid}: {e}')
    if errors and len(errors) == len(patient_ids):
        raise ConnectionError(
            f'C-FIND on {node} failed for every patient ID tried: '
            + '; '.join(errors)
        )
    return results
```

Update the docstring: `Raises ConnectionError if every patient ID tried failed (e.g. the node is unreachable) — callers must not treat that as "no studies".`

- [ ] **Step 4: Run tests**

Run: `venv/bin/python manage.py test dicom_server -v 1`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dicom_server/services/qr_client.py dicom_server/tests/test_qr.py
git commit -m "fix: fail retrieval job when C-FIND fails for every patient ID"
```

---

### Task 3: `task_auto_retrieve_patient` only targets auto-retrieval-enabled nodes

Audit items: §7.3 — H4. Consent currently opens associations to *every* active node.

**Files:**
- Modify: `dicom_server/tasks.py` (`task_auto_retrieve_patient`, ~line 243)
- Test: `dicom_server/tests/test_auto_retrieval.py`

**Interfaces:**
- Produces: unchanged signature; only the node queryset narrows to `auto_retrieve_enabled=True`.

- [ ] **Step 1: Write the failing test**

In `dicom_server/tests/test_auto_retrieval.py`, add `task_auto_retrieve_patient` to the import block and add:

```python
    @patch('dicom_server.tasks.task_auto_retrieve_patient_node.delay')
    def test_patient_event_skips_nodes_without_auto_retrieval(self, mock_dispatch):
        RemoteDICOMNode.objects.create(
            name='off', ae_title='OFF', host='localhost', port=104,
            is_active=True, auto_retrieve_enabled=False,
        )
        task_auto_retrieve_patient(self.patient.patient_id)
        dispatched = [c.args[0] for c in mock_dispatch.call_args_list]
        self.assertEqual(dispatched, [self.node.pk])
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python manage.py test dicom_server.tests.test_auto_retrieval -v 1`
Expected: FAIL — both nodes dispatched.

- [ ] **Step 3: Implement**

```python
    nodes = RemoteDICOMNode.objects.filter(is_active=True, auto_retrieve_enabled=True)
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/python manage.py test dicom_server.tests.test_auto_retrieval -v 1`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dicom_server/tasks.py dicom_server/tests/test_auto_retrieval.py
git commit -m "fix: consent-triggered retrieval only targets auto-retrieval-enabled nodes"
```

---

### Task 4: Fix stale `test_frontend.py` dispatch assertion

Audit items: §7.4 — H5. The view passes `patient_id_aliases=aliases`; the test never got updated.

**Files:**
- Modify: `dicom_server/tests/test_frontend.py` (`test_retrieve_creates_job_and_dispatches`, ~line 176)

- [ ] **Step 1: Fix the assertion**

```python
        mock_delay.assert_called_once_with(
            self.node.pk, self.patient.patient_id, self.perm_user.pk, job.pk,
            patient_id_aliases=[],
        )
```

- [ ] **Step 2: Run tests**

Run: `venv/bin/python manage.py test dicom_server.tests.test_frontend -v 1`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add dicom_server/tests/test_frontend.py
git commit -m "test: update retrieval dispatch assertion for patient_id_aliases kwarg"
```

---

### Task 5: `_upsert_study` UID-first lookup + orphan-file cleanup on DB failure

Audit items: §7.5 — M6. `study_instance_uid` is the PK; `get_or_create(patient=…, study_instance_uid=…)` raises `IntegrityError` when the UID exists under another patient, leaving an orphan `.dcm`.

**Files:**
- Modify: `dicom_server/services/ingest.py` (`ingest_dataset` ~line 100, `_upsert_study` ~line 132)
- Test: `dicom_server/tests/test_ingest.py`

**Interfaces:**
- Produces: `_upsert_study` now fetches by UID first and reassigns `study.patient` when the UID was previously stored under a different patient (alias/canonical mismatch — the freshly matched patient wins).
- `ingest_dataset` deletes the written `.dcm` when the DB phase fails.

- [ ] **Step 1: Write the failing tests**

In `dicom_server/tests/test_ingest.py`, add `from unittest import mock` and:

```python
    def test_study_uid_collision_reassigns_patient(self):
        other = Patient.objects.create(patient_id='OTHER/1', gender='Male')
        ds = make_test_dataset(patient_id='MR/25/004771')
        DICOMStudy.objects.create(patient=other, study_instance_uid=ds.StudyInstanceUID)
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0x0000)
        study = DICOMStudy.objects.get(study_instance_uid=ds.StudyInstanceUID)
        self.assertEqual(study.patient, self.patient)

    def test_db_failure_removes_orphan_file(self):
        ds = make_test_dataset(patient_id='MR/25/004771')
        with mock.patch(
            'dicom_server.services.ingest._upsert_study',
            side_effect=RuntimeError('db down'),
        ):
            result = ingest_dataset(ds)
        self.assertEqual(result.status, 0xC000)
        dest = (
            self.media / 'processed_dicom' / 'MR_25_004771'
            / sanitize(ds.StudyInstanceUID) / f"{sanitize(ds.SOPInstanceUID)}.dcm"
        )
        self.assertFalse(dest.exists())
        self.assertFalse(DICOMStudy.objects.exists())
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python manage.py test dicom_server.tests.test_ingest -v 1`
Expected: `test_study_uid_collision_reassigns_patient` returns `0xC000` today; `test_db_failure_removes_orphan_file` leaves the `.dcm` behind today.

- [ ] **Step 3: Implement**

In `ingest_dataset`, initialise `dest` before the `try` and unlink on failure:

```python
    dest = None
    try:
        # Align with existing import services: stored files carry the canonical ID.
        ds.PatientID = patient.patient_id
        study_dir = (
            Path(settings.MEDIA_ROOT) / 'processed_dicom'
            / sanitize(patient.patient_id) / sanitize(study_uid)
        )
        study_dir.mkdir(parents=True, exist_ok=True)
        dest = study_dir / f"{sanitize(sop_uid)}.dcm"
        ds.save_as(dest, enforce_file_format=True)
        ...
    except Exception:
        logger.exception("Failed to ingest instance %s", sop_uid)
        if dest is not None:
            try:
                dest.unlink(missing_ok=True)  # no orphan .dcm after a DB failure
            except OSError:
                logger.warning("Could not remove orphaned file %s", dest)
        InboundDICOMInstance.objects.create(...)
        return IngestResult(status=STATUS_INTERNAL_ERROR, reason='Internal storage error')
```

In `_upsert_study`:

```python
def _upsert_study(patient: Patient, ds: Dataset, study_dir: Path) -> None:
    """Merge this instance's metadata into the DICOMStudy row (comma-joined sets)."""
    uid = str(ds.StudyInstanceUID)
    study = DICOMStudy.objects.filter(study_instance_uid=uid).first()
    if study is None:
        study = DICOMStudy.objects.create(patient=patient, study_instance_uid=uid)
    elif study.patient_id != patient.patient_id:
        # Same StudyInstanceUID seen under a different patient (ID alias or
        # canonical mismatch) — the patient matched from this dataset wins.
        logger.warning(
            'Study %s was stored under patient %s; reassigning to %s',
            uid, study.patient_id, patient.patient_id,
        )
        study.patient = patient
    # ... merge block unchanged ...
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/python manage.py test dicom_server -v 1`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dicom_server/services/ingest.py dicom_server/tests/test_ingest.py
git commit -m "fix: resolve study UID collisions and delete orphan file on ingest failure"
```

---

### Task 6: README names the SCU containers + hostname in shared log format

Audit items: §7.6 — H6, M3. `docker compose restart` does not apply `extra_hosts` edits; the shared `dicom_server.log` needs an origin marker.

**Files:**
- Modify: `docker_install/README.md` (~line 115, "Outbound connections need no compose configuration" paragraph)
- Modify: `chavi_client/settings.py` (LOGGING `detailed` formatter + handlers)

**Interfaces:**
- Produces: `detailed` log format gains `{hostname}`; every handler using `detailed` gains the `hostname` filter (records would otherwise fail to format).

- [ ] **Step 1: settings.py — hostname on every detailed record**

Add `import socket` to the imports, and near `LOGGING`:

```python
_HOSTNAME = socket.gethostname()


def _add_hostname(record):
    """Stamp the container hostname on each record — django, celery-worker and
    dicom containers write to the same shared log files."""
    record.hostname = _HOSTNAME
    return True
```

In `LOGGING`, add a `filters` block and update the `detailed` formatter:

```python
    'filters': {
        'hostname': {
            '()': 'django.utils.log.CallbackFilter',
            'callback': _add_hostname,
        },
    },
```

```python
        'detailed': {
            'format': '{levelname} {asctime} {hostname} {module} {process:d} {thread:d} {message} [File: {pathname}:{lineno}]',
            'style': '{',
        },
```

Add `'filters': ['hostname']` to the four handlers using `detailed`: `file`, `dicom_import`, `deidentification`, `dicom_server`.

- [ ] **Step 2: Verify settings load**

Run: `venv/bin/python -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','chavi_client.settings'); django.setup(); import logging; logging.getLogger('dicom_server').info('hostname smoke test')" && tail -1 logs/dicom_server.log`
Expected: log line contains the container/hostname between timestamp and module.

- [ ] **Step 3: README — replace the wrong paragraph**

Replace this block in `docker_install/README.md`:

```
**Outbound connections need no compose configuration.** Docker NAT handles them;
the only requirements are that `node.host` resolves inside the container (a LAN
IP or public FQDN is fine) and that the remote accepts our calling AE title
(`CHAVI_CLIENT` by default).
```

with:

````
**Outbound SCU connections originate from `chaviclient-django` and
`chaviclient-celery-worker`** — `chaviclient-dicom` never dials out, so it needs
no name-resolution setup. Docker NAT handles outbound traffic, but `node.host`
must resolve *inside each SCU container*. A LAN IP or public FQDN works as-is;
a bare hostname that DNS cannot resolve must be pinned with `extra_hosts` on
**both** SCU services:

```yaml
services:
  chaviclient-django:
    extra_hosts:
      - "siemenspacs:192.168.1.50"
  chaviclient-celery-worker:
    extra_hosts:
      - "siemenspacs:192.168.1.50"
```

Apply with `docker compose up -d` — `docker compose restart` does **not**
recreate containers, so `extra_hosts` edits have no effect until the next
`up -d`. Verify resolution inside each SCU container:

```bash
docker exec chaviclient-django        getent hosts siemenspacs
docker exec chaviclient-celery-worker getent hosts siemenspacs
```

The remote must also accept our calling AE title (`CHAVI_CLIENT` by default) —
many PACS and workstations whitelist calling AETs, and the *called* AET must
match the peer's configured DICOM AE title (often not its machine hostname).
````

- [ ] **Step 4: Commit**

```bash
git add docker_install/README.md chavi_client/settings.py
git commit -m "docs: name Q/R SCU containers for extra_hosts; log container hostname"
```

---

## Self-review notes

- Spec coverage: §7 items 1–6 → Tasks 1–6 respectively. H1/H2/M1/M2 (Task 1), H3 (Task 2), H4 (Task 3), H5 (Task 4), M6 (Task 5), H6/M3 (Task 6).
- `get_study` passes `evt_handlers`/`ext_neg` through `_connect(**assoc_kwargs)` — signature consistent between Tasks 1 producer and callers.
- Remaining audit findings (M4 echo-gate policy, M5 config cache, M7 patient scan, M8 inbound consent, M9 double C-FIND, M10 dev compose, M11 volume shadowing, M12 dead field, L1–L8) are intentionally out of scope — several need product decisions or a second pass.

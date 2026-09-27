# DICOM services audit — chavi_client vs draw-client-2.0

Scope: complete read of `chavi_client/dicom_server` and the connection-relevant parts of
`draw-client-2.0/dicom_server`, plus `client_app` dependencies, Docker files, settings, tests, and the
shared `pynetdicom 3.0.4` internals. Status: **audit report only — no code changes.**

## 1. Files audited

**chavi_client/dicom_server (100%)**
`services/qr_client.py`, `services/ingest.py`, `services/query.py`, `services/classifier.py`,
`services/schedule_sync.py`, `scp/server.py`, `scp/handlers.py`, `models.py`, `tasks.py`, `views.py`,
`forms.py`, `admin.py`, `signals.py`, `apps.py`, `urls.py`, `__main__.py`,
`management/commands/*`, `tests/*` (test_qr, test_scp, test_ingest, test_auto_retrieval,
test_frontend, test_schedule_sync, test_live, utils).

**chavi_client dependencies**
`client_app/models.py` (`Patient`, `DICOMStudy`, `_make_canonical_id`, `StudyTypeSource`),
`client_app/signals.py` (consent → auto-retrieve), `client_app/tasks.py` (TaskRun helpers),
`chavi_client/settings.py` (LOGGING, CACHES, CELERY), `gunicorn.conf.py`, `Dockerfile`,
`entrypoint.docker.sh`, `docker-compose.yml`, `docker_install/*`.

**draw-client-2.0/dicom_server**
`query_retrieve_service.py`, `cstore_push_service.py`, `dicom_scp_service.py`, `service_manager.py`,
`apps.py`, `tasks.py`, `handlers/{c_store,c_find,c_get,c_move}_handler.py`, `views_qr.py`,
`forms_qr.py`, `models.py`, Docker/compose/`docker_install/*`.

**Library** — `pynetdicom 3.0.4`: `ae.py` `AE.associate`, `transport.py` `AddressInformation` /
`AssociationSocket.connect`.

---

## 2. Connect-path comparison — the code is identical

Every outbound call site: draw `query_retrieve_service.py:116,181,273,364`,
`cstore_push_service.py:75,318`, `handlers/c_move_handler.py:339`; chavi `qr_client.py:39,62,194,226`.
All are `ae.associate(<raw host string from DB>, <port>, ae_title=<called AET>)`.

| Step | draw-client | chavi_client | Differs? |
|---|---|---|---|
| SCU AE | one `AE` per process, singleton (`query_retrieve_service.py:547-553`), AET read once | fresh `AE` per call (`qr_client.py:25-31`), AET from 300 s cache | cosmetic |
| Timeouts | defaults; C-STORE service sets 30 s (`cstore_push_service.py:68-70`) | `network/acse/dimse = qr_timeout` (30 s) | no effect on connect |
| `connection_timeout` | not set | not set | same gap |
| Host value | `remote_node.host` raw from DB | `node.host` raw from DB | identical |
| Resolution | inside `AE.associate()` → `AddressInformation.address` → `socket.getaddrinfo(host, 0)` | same | identical (same pynetdicom 3.0.4) |
| Called AET | `remote_node.outgoing_ae_title` | `node.ae_title` | same semantics |
| Calling AET | `DicomServerConfig.ae_title` (default `DRAW_SCP`) | `DICOMServerConfiguration.ae_title` (default `CHAVI_CLIENT`) | **different value on the wire** |
| Failure reporting | exception text reaches the UI (`query_retrieve_service.py:135-141`) | bare `False`; reason only in the log (`qr_client.py:40-50`) | chavi hides the cause |
| Resolving process | gunicorn in `django-web` (SCP+SCU same container) | gunicorn in `chaviclient-django` (Echo button); celery child in `chaviclient-celery-worker` (jobs). `chaviclient-dicom` never dials out | different container |

Neither app pre-resolves, reads `/etc/hosts`, sets a `bind_address` on outbound associations, or has any
Docker-conditional logic. Draw's only `gethostbyname` (`cstore_push_service.py:246`) runs after the
transfer for audit logging.

**Conclusion.** There is no Python code in chavi_client that can turn a resolvable name into
`[Errno -5] No address associated with hostname` where draw would not. `Errno -5` is glibc
`EAI_NODATA`: the resolver of *the process that logged it* fell through to DNS and got an empty answer —
i.e. `/etc/hosts` did not match in that process's mount/resolver namespace at that moment. The
container split cannot itself produce the error; it only decides *whose* resolver is consulted. The two
variables that can still differ the outcome are (a) the resolver context of the calling process and
(b) the peer's acceptance of the calling/called AE titles.

---

## 3. Production log analysis

`~/Downloads/dicom_server.log` (excerpt meaning):

- `C-ECHO association to Siemens Workstation Phase II (DESKTOP-SU62PG0@siemenspacs:104) failed:
  [Errno -5] No address associated with hostname` — raised at `qr_client.py:41`, i.e. inside
  `AE.associate()` during `getaddrinfo`, **before** any TCP packet. Logged by PID 157/158 — a gunicorn
  worker or celery prefork child (the shared log format carries PID but no hostname, so the container
  is ambiguous — see M3).
- `... failed: aborted` for `www.dicomserver.co.uk:11112` at `qr_client.py:49` — a *different* failure:
  DNS resolved but the TCP connect failed/timed out and pynetdicom reports it as an A-ABORT. Likely
  outbound internet blocked from the LAN.
- A SIGTERM restart appears between identical failures — `docker compose restart` does not apply
  compose-file edits (new `extra_hosts`); only `docker compose up -d` recreates `HostConfig.ExtraHosts`.

User evidence since: `getent hosts siemenspacs` resolves inside `chaviclient-dicom`, and a
bare-pynetdicom `associate()` from that container with placeholder AE titles (`TESTSCU` →
`REMOTE_AE_TITLE`) did not establish. That test bypasses chavi code entirely — it proves resolution
works there and that the remaining failure is at the DICOM layer (AE titles) or TCP. A Siemens
workstation will reject an association whose *called* AET is not its own, and may whitelist *calling*
AETs — in which case `DRAW_SCP` succeeds and `CHAVI_CLIENT` (or `TESTSCU`) is rejected.

**Root-cause status: not yet confirmed.** The two candidate causes require the runtime checks in §4
to discriminate. Note also that `DESKTOP-SU62PG0` is a Windows computer name; the workstation's DICOM
AE title is configured separately and is often *not* the hostname — the `ae_title` stored for the node
in chavi's DB should be verified against the workstation's DICOM configuration, not its machine name.

---

## 4. Discriminating checks (production host, read-only)

```bash
# A — name resolution, the exact call pynetdicom makes, in each SCU container + draw reference
docker exec chaviclient-django        python -c "import socket; print(socket.getaddrinfo('siemenspacs', 104))"
docker exec chaviclient-celery-worker python -c "import socket; print(socket.getaddrinfo('siemenspacs', 104))"
docker exec draw-client-django-docker python -c "import socket; print(socket.getaddrinfo('siemenspacs', 104))"

# B — raw TCP reachability from the chavi django container
docker exec chaviclient-django python -c "import socket; s=socket.create_connection(('siemenspacs',104),5); print('TCP ok', s.getsockname()); s.close()"

# C — association with REAL AE titles, once per calling title, pynetdicom debug logging on
docker exec chaviclient-django python -c "
from pynetdicom import AE, debug_logger
from pynetdicom.sop_class import Verification
debug_logger()
for calling in ('CHAVI_CLIENT', 'DRAW_SCP'):
    ae = AE(ae_title=calling); ae.add_requested_context(Verification)
    a = ae.associate('siemenspacs', 104, ae_title='DESKTOP-SU62PG0')
    print(calling, 'established', a.is_established, 'rejected', a.is_rejected, 'aborted', a.is_aborted)
    if a.is_established: print(a.send_c_echo()); a.release()
"

# D — same as C inside draw-client-django-docker
# Supporting: cat /etc/nsswitch.conf /etc/resolv.conf /etc/hosts in both images;
#             docker inspect chaviclient-django --format '{{.Created}} {{.HostConfig.ExtraHosts}}'
```

| Result | Meaning |
|---|---|
| A fails only in chavi | resolver/nsswitch/resolv.conf difference between the two images |
| A ok, B fails | routing/firewall — compare `docker network inspect` subnets vs the LAN |
| C rejected as `CHAVI_CLIENT`, established as `DRAW_SCP` | workstation whitelists calling AETs → register `CHAVI_CLIENT` on it |
| C shows `A-ASSOCIATE-RJ` "Called AE Title Not Recognised" | `ae_title` in chavi's DB is wrong |

---

## 5. Findings — chavi_client `dicom_server`

### High

- **H1 — `echo()` discards the failure reason.** `qr_client.py:34-57`: DNS error, TCP refused/timeout,
  A-ASSOCIATE-RJ and non-zero C-ECHO status all return `False`; `views.py:129` and `admin.py:70`
  display only "C-ECHO failed". `_connect()` (`qr_client.py:60-73`) already classifies
  rejected/aborted/no-contexts but `echo()` doesn't use it. This is precisely why the current outage
  was hard to see.
- **H2 — `_connect()` used only by `find_studies`.** `move_study` (`qr_client.py:194-196`) and
  `get_study` (`:226-232`) re-implement a weaker "rejected or timed out"; `socket.gaierror` raised
  inside `associate()` propagates uncaught from find/move/get.
- **H3 — Connectivity failure reported as SUCCESS.** `find_studies_for_patient` (`qr_client.py:129-137`)
  swallows every exception per PatientID; `task_retrieve_studies` (`tasks.py:89-97`) marks
  `total == 0` as `SUCCESS`. A C-FIND that never connected yields a green job with 0 studies.
- **H4 — Consent signal fires retrieval against nodes with auto-retrieval disabled.**
  `client_app/signals.py` → `task_auto_retrieve_patient` (`tasks.py`) selects
  `RemoteDICOMNode.objects.filter(is_active=True)` **without** `auto_retrieve_enabled=True` and passes
  `force=True`. Marking a patient consented immediately opens associations to *every* active node.
- **H5 — Test suite is red.** `tests/test_frontend.py:176-178` asserts
  `delay(node.pk, patient_id, user.pk, job.pk)` but `views.py:150-153` now passes
  `patient_id_aliases=aliases`; `assert_called_once_with` fails — the alias feature landed without the
  frontend tests being run.
- **H6 — Docs never say which container needs `extra_hosts`.** `docker_install/README.md` states
  "Outbound connections need no compose configuration". It must name `chaviclient-django` **and**
  `chaviclient-celery-worker`, require `docker compose up -d` (not `restart`), and give the
  `getent hosts` verification.

### Medium

- **M1 — No `connection_timeout`** (`qr_client.py:25-31`): a SYN to an unroutable LAN IP blocks a
  gunicorn thread ~2 min per Echo click. Same gap in draw.
- **M2 — TCP failures surface as "aborted".** Add a pre-flight
  `socket.create_connection((host, port), timeout)` in `_connect()` to distinguish DNS / refused /
  timeout / DICOM-reject.
- **M3 — Shared log, no origin.** django, worker and dicom containers all write `dicom_server.log` into
  the `app_data` volume; format carries `{process:d}` only (`settings.py`). Add `%(hostname)s` or
  per-container files.
- **M4 — C-ECHO gate aborts retrieval** (`tasks.py`): job dies if Verification is rejected; several
  PACS accept C-FIND but not C-ECHO.
- **M5 — Config cache 300 s** (`models.py` `DICOMServerConfiguration.load`): AE-title changes lag up to
  5 min in web/worker; the SCP never picks them up without a container restart (draw hot-reloads via
  `dicom_scp_service.py` `refresh_config`).
- **M6 — Study UID collision across patients + orphan file.** `ingest.py` `_upsert_study` uses
  `get_or_create(patient=…, study_instance_uid=…)` where `study_instance_uid` is the PK: if the UID
  exists under another patient (alias/canonical mismatch), `create` raises `IntegrityError` → caught
  → 0xC000 "Internal storage error" **after** the file was written — orphan on disk, no cleanup.
- **M7 — O(N) patient scan per received instance** (`ingest.py`, canonical-ID fallback): every
  unknown/ambiguous PatientID iterates the whole `Patient` table inside the association thread —
  a 500-image C-MOVE does 500 full-table iterations.
- **M8 — Inbound storage ignores consent.** Ingest gates only on patient existence; retrieval requires
  `chavi_consent=True`. A PACS push stores images for non-consented patients — policy inconsistency to
  decide deliberately.
- **M9 — Auto-retrieval does C-FIND twice.** `_auto_retrieve_patient_node` finds studies, then
  `task_retrieve_studies` echoes and finds again before filtering to `job.study_uids` — doubles PACS
  load per patient per sweep.
- **M10 — Dev `docker-compose.yml` lacks rabbitmq/worker/beat**; `.delay()` fails against
  `amqp://guest@localhost`. Only `docker_install/example_docker-compose.yml` is complete.
- **M11 — `app_data:/app` named volume shadows image code** (both projects). Verified *not* stale for
  `qr_client.py` today (log lines 41/49 match HEAD), but image updates won't reach `/app` on existing
  installs.
- **M12 — `retrieve_all` form field is dead** (`forms.py`): never read in
  `RetrieveStudiesView.form_valid`; `RetrievalJob.study_uids` is never set from the UI — "retrieve all"
  is the only behaviour despite the checkbox.

### Low

- L1 `tasks.py` `update_fields` includes `completed_at`/`error_log` on the RUNNING transition.
- L2 No AE-title validator on `DICOMServerConfiguration.ae_title` / `RemoteDICOMNode.ae_title` (draw
  enforces `^[A-Z0-9_\-]+$`); `host` has no strip/format validation.
- L3 `ingest.py` `STATUS_SERVER_DISABLED` reuses `0xA700` (same as unknown patient).
- L4 `query.py` globs `*.dcm` on disk per study per C-FIND response inside the association thread.
- L5 `query.py` `_fill`: `ds.add_new(e.tag, e.VR, '')` for unknown requested keys raises for SQ-VR keys
  (e.g. `RequestAttributesSequence`), failing the whole C-FIND.
- L6 `get_study` requests `StoragePresentationContexts` (120/170 classes): standard CT/MR/RT included;
  newer RT 2nd-gen, waveform and some SR classes would be refused as sub-ops. Draw's SCP accepts
  `AllStoragePresentationContexts`.
- L7 `client_app/signals.py` `pre_save` issues an extra `Patient.objects.get` on every Patient save.
- L8 `chaviclient-celery-worker` lacks the `./logs` bind mount in the example compose.

### Verified correct

`scp/server.py` lifecycle and signal handling; `_db_cleanup` DB-connection hygiene in `scp/handlers.py`;
C-GET role negotiation (`qr_client.py`); sub-operation accounting with DIMSE-timeout fallback
(`_subop_stats` counts remaining as failed); schedule sync via signals + PeriodicTask + management
command; loopback tests (`test_qr.py`, `test_scp.py`, `test_ingest.py`) exercise echo/find/move/get and
store end-to-end against stub peers.

---

## 6. draw-client observations (context only — not to be changed unless asked)

- `docker_install/README.md` states `extra_hosts` is needed "only if the C-MOVE service is used" and
  "C-FIND and C-ECHO work without it" — **incorrect**; `extra_hosts` is pure name resolution required
  whenever `host` is a bare hostname. This wording plausibly shaped the chavi deployment.
- `apps.py` starts the SCP thread from `ready()` under `gunicorn --workers 4 --preload` — the thread
  lives in the master pre-fork; fragile design.
- `query_retrieve_service.py` singleton reads `ae_title` once per process; config change needs restart.
- `dicom_scp_service.py` `require_called_aet=False` — SCP accepts any called AET (lenient inbound).
- `test_connection` returns generic "Failed to establish association" for both reject and abort (same
  weakness as chavi, though it does pass exception text through).

---

## 7. Recommended fix order (for a follow-up implementation pass)

1. `echo()` → return `(ok, reason)` via `_connect()`; add `connection_timeout`; TCP pre-flight; surface
   the reason in view/admin/job `error_log`.
2. `find_studies_for_patient` → re-raise when *all* IDs fail; job status `FAILED`.
3. `task_auto_retrieve_patient` → filter `auto_retrieve_enabled=True`.
4. Fix `tests/test_frontend.py` (`patient_id_aliases=[]`).
5. `_upsert_study` → look up by UID first; delete the file on DB failure.
6. README: name the SCU containers, `up -d`, `getent` check; add hostname to the log format.

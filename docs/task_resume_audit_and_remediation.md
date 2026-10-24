# Task Resume Audit & Remediation Plan

> **Status: IMPLEMENTED & TESTED.** All phases (0–6) are complete. New coverage
> lives in `client_app/tests_task_resume.py` (20 tests). Full suites green:
> `client_app` + `deidentification` + `dicom_archive` (205) and `dicom_server`
> (249). See the per-phase notes below for what landed where.

Scope: every Celery task in the codebase, audited for the ability to **restart after a
mid-run failure, worker death, Celery soft/hard time limit, or RabbitMQ timeout** — and to
do that **from the Task Runs UI** (`taskrun_list.html`, `taskrun_detail.html`,
`task_progress.html`).

Trigger case: `deidentification/services/legacy_import.py` +
`import_legacy_mapping_task` (`deidentification/tasks.py:455`) — currently **not
restartable at all** (see Finding F1).

---

# PART 1 — AUDIT

## 1.1 How resume works today (existing infrastructure)

| Piece | Location | What it does |
|---|---|---|
| `TaskRun` model | `client_app/models.py:2437` | One row per dispatched task. Keyed by **current Celery task id** (`task_id`, unique). Stores `task_args`/`task_kwargs` (original dispatch args, for redispatch), `manifest_path`, `resume_count`, progress, `result_summary`, `error_log`. |
| `_create_task_run()` | `client_app/tasks.py` | `update_or_create(task_id=celery_task_id)`. Because resume/auto-continue **rewrite `task_run.task_id` to the new Celery id before redispatch**, the same DB row (same pk) is reused across resumes. **The TaskRun pk is stable across resumes; the Celery id is not.** |
| `TASK_REGISTRY` | `client_app/views.py` (~line 1276) | `task_name -> callable` map. `_redispatch_task_run()` re-dispatches with stored args/kwargs. **A task is UI-resumable only if it is in this registry AND has stored `task_args`.** |
| `TaskRunResumeView` / `TaskRunRetryView` | `client_app/views.py` | Resume: only `FAILURE`/`STALLED`. Retry: also `SUCCESS` (creates a *new* TaskRun row). Both require `task_args` non-null. |
| Manifest checkpointing | `client_app/services/task_checkpoint.py` | JSONL file, one `{"item_id", "status": "done"}` line per completed item. `read_manifest()` returns the done-set so a rerun can skip finished items. |
| `_auto_continue_task()` | `client_app/tasks.py` | On `SoftTimeLimitExceeded`: redispatch same task + args, rewrite `task_id` on the same row, notify user. Capped at `MAX_AUTO_CONTINUE_ATTEMPTS = 20`. **Relies on the task's own checkpointing to make the continuation useful.** |
| Stall detection | `task_detect_stalled_tasks` (beat) | `PROGRESS`/`STARTED` runs with no progress for 10 min → `STALLED` + notification. This is what makes a hard-killed task *visible* as resumable — but only if the task is also in the registry. |
| Progress UI | `task_progress.html` + `celery_progress` app | Polls `celery_progress:task_status/<celery_id>`. On `FAILURE` shows only "View Task Runs" / "Back to Home" — **no resume path**. |

### Criteria used in the audit below

A task is **resumable from the UI** only if all of:

- **A. Registry** — `task_name` is in `TASK_REGISTRY` (redispatchable).
- **B. Args stored** — `task_args`/`task_kwargs` captured at dispatch (true for all current tasks).
- **C. Timeout handling** — `SoftTimeLimitExceeded` is caught and auto-continued (or a graceful in-task deadline converts a timeout into a clean partial state).
- **D. Checkpointing / idempotency** — a rerun skips already-completed work (manifest, DB status flags, or safe `update_or_create` semantics).
- **E. Input durability** — the task's inputs (uploaded files, temp state) still exist when it is redispatched.

## 1.2 Task-by-task audit

Legend: ✅ resumable · ⚠️ partial / conditional · ❌ not resumable · — not applicable (beat/chord plumbing)

### `client_app/tasks.py`

| Task | Checkpointing (D) | Timeout (C) | Registry (A) | Verdict |
|---|---|---|---|---|
| `task_associate_dicom_to_project` | none, but idempotent (`get_or_create`) | auto-continue | yes | ✅ full rerun, safe |
| `task_process_bulk_dicom` | per-upload (`upload.status == 'Processed'` skipped) | auto-continue | yes | ✅ per-upload granularity; in-flight upload reruns from its start |
| `task_export_dicom_data` | manifest + zip append mode | auto-continue | yes | ✅ per-study |
| `task_process_dicom_per_patient` | per-file (`obj.processed` skipped) | auto-continue | yes | ✅ per-file |
| `task_extract_and_analyze_upload` | session match rows + preserved temp dir | auto-continue | yes | ✅ |
| `task_process_confirmed_matches` | per-match status (`PROCESSED`/`UNMATCHED` skipped) | auto-continue | yes | ✅ |
| `task_export_dicom_data_parallel` | manifest + zip append | auto-continue | yes | ✅ per-study |
| `task_export_patient_data` | manifest + zip append | auto-continue | yes | ✅ per-patient |
| `task_process_unprocessed_dicom` | per-study (`status == "Processed"` skipped) | auto-continue | yes | ✅ per-study |
| `task_detect_stalled_tasks` | — | — | — | beat task |
| `task_cleanup_stale_exports` | — | — | — | beat task |

### `deidentification/tasks.py`

| Task | Checkpointing (D) | Timeout (C) | Registry (A) | Verdict |
|---|---|---|---|---|
| `deidentify_dicom_studies_bulk_task` (dispatcher) | per-study results on parent `result_summary`; skips to first unrecorded index | n/a (short dispatcher) | yes | ✅ |
| `deidentify_dicom_study_task` (chain link) | per-series / per-sub-batch manifest | auto-continue (`soft_time_limit=3300`) | yes | ✅ mid-study resume |
| `finalize_deidentification_batch_task` | n/a (aggregation, idempotent) | n/a (short) | **no** | ❌ if it dies, parent run sits `PROGRESS`→`STALLED` forever, unrecoverable from UI (F4) |
| `import_legacy_mapping_task` | **none** — manifest path created but never written/read; `fetchall()` on 4 tables | **none** — `soft_time_limit=600`, no `SoftTimeLimitExceeded` handler → unhandled → `FAILURE` | **no** | ❌ **plus inputs destroyed** (F1) |
| `build_dicom_download_zip_task` | none (zip not appendable) | handler exists but only **fails** the task, no auto-continue (`soft_time_limit=3600`) | **no** | ❌ (F2) |
| `build_clinical_download_zip_task` | none | handler only fails (`soft_time_limit=1800`) | **no** | ❌ (F2) |
| `create_missing_records_task` | idempotent (existence checks per record) | **none** — `soft_time_limit=1800`, no handler | **no** | ❌ (F3) |

### `dicom_archive/tasks.py`

| Task | Checkpointing (D) | Timeout (C) | Registry (A) | Verdict |
|---|---|---|---|---|
| `archive_studies_task` | per-study failure isolation, but **not idempotent**: re-archiving an already-archived study raises "destination not empty" → reported as per-study failure | **none** (global 3300s soft, no handler) | **no** | ❌ (F5) |
| `dearchive_studies_task` | per-study; idempotent (uids without an `ARCHIVED` record are skipped) | **none** | **no** | ❌ (F5) |
| `task_scheduled_archive` | — | — | — | beat dispatcher |

### `dicom_server/tasks.py`

| Task | Checkpointing (D) | Timeout (C) | Registry (A) | Verdict |
|---|---|---|---|---|
| `task_retrieve_studies` | per-item status on `RetrievalJobStudy`/`Series` rows, **but `_run_job_retrieval` never skips `done` items** — a rerun re-retrieves everything | **bug**: graceful deadline is 3.5 h but the task has no own limits, so the global **1 h hard limit SIGKILLs it first**; job left `RUNNING`, TaskRun → `STALLED` | **no** | ❌ (F6) |
| `task_query_patient_studies` (chord header) | per-patient row status; never raises | n/a (short) | no (chord) | ⚠️ safe to redeliver; but see F11 (chord loss) |
| `task_finalize_batch_query` (chord body) | — | — | no | ⚠️ if the chord result message is lost (broker restart/timeout) the batch is stuck in `QUERYING` forever (F11) |
| `task_retrieve_patient_selection` (chord header) | per-item status, not skipped on rerun | graceful deadline works (own `time_limit=4h`, `soft=3.5h`) → job ends `PARTIAL` | **no** | ❌ (F7) |
| `task_finalize_retrieval_batch` (chord body) | — | — | no | ⚠️ F11 |
| `task_auto_retrieve_*` (4 tasks) | — | — | — | beat/event-driven |
| `task_bulk_schedule_run` | — | — | — | beat dispatcher |
| `task_bulk_schedule_finalize_query` / `chunk_done` / `finalize_retrieval` (chord bodies) | — | — | no | ⚠️ F11 |

### `extractor/tasks.py` (tracked on `BackgroundTask`, **not** `TaskRun` — separate UI)

| Task | Checkpointing | Verdict |
|---|---|---|
| `compute_lookup_embeddings_task` + `embed_lookup_table_chunk` + `finalize_lookup_embeddings_task` | DB-level chunk checkpointing (`collect_pending_rows` + unique constraint); redelivered chunk is a no-op | ✅ crash-resilient by design; ⚠️ if a chunk link is hard-killed the self-perpetuating chain breaks and `BackgroundTask` stays `running` with no recovery path (F10) |
| `advance_extraction_job` | stage-based on job status; explicit re-dispatch from extractor UI | ✅ |
| `ocr_processed_text_task` / `deidentify_processed_text_task` | none (single-shot) | ⚠️ not resumable, but short-lived; tracked outside TaskRun UI |

## 1.3 Key findings

- **F1 — `import_legacy_mapping_task` is unrecoverable (the reported case).** Four independent blockers:
  1. Not in `TASK_REGISTRY` → UI shows "Resume N/A".
  2. No `SoftTimeLimitExceeded` handler with `soft_time_limit=600` → a timeout is an unhandled exception → `FAILURE`.
  3. **The `finally` block deletes the uploaded `db_path`/`key_path` temp files** — even a manual redispatch would die with `FileNotFoundError`. Inputs are destroyed on every failure.
  4. No checkpointing: the manifest path is created but the service never writes/reads it; a rerun reprocesses 100% of rows (safe via `update_or_create`, but slow, and `unmatched_rows`/`fetchall()` give unbounded memory on large DBs).
- **F2 — ZIP build tasks** (`build_dicom_download_zip`, `build_clinical_download_zip`): not in registry; soft-limit handler only fails the task; zip path keyed on `self.request.id`, so a redispatch would orphan the partial zip and rebuild under a new name.
- **F3 — `create_missing_records_task`**: not in registry; no soft-limit handler. Rerun is safe (idempotent), so this is a cheap fix.
- **F4 — `finalize_deidentification_batch_task`**: not in registry. If it fails or is killed, the parent bulk run is stuck `PROGRESS`→`STALLED` with no UI recovery, even though re-running finalize is idempotent.
- **F5 — Archive tasks**: not in registry; no timeout handling; `archive_studies` is not idempotent (already-archived studies surface as failures on rerun).
- **F6 — `task_retrieve_studies` time-limit bug**: graceful deadline (3.5 h) is longer than the effective hard limit (global 1 h) → SIGKILL mid-retrieval, `RetrievalJob` left `RUNNING`, TaskRun `STALLED`, not in registry. `task_retrieve_patient_selection` does it right (own 4 h/3.5 h limits).
- **F7 — Retrieval reruns are not incremental**: `_run_job_retrieval` ignores items already marked `done`, so even a manual redispatch re-pulls every study/series.
- **F8 — Manifest keying must be stable across resumes.** Celery task ids change on every redispatch. Export tasks solve this by taking a stable `task_id` argument; the deid chain keys on the parent Celery id (study-level manifest is lost on parent resume — acceptable, the study reruns). `import_legacy_mapping` keys on `self.request.id` → checkpoint would be lost on resume. **Use the stable `TaskRun.pk` as the manifest key.**
- **F9 — UI gaps**: (a) `task_progress.html` failure state has no resume action; (b) list/detail gate the Resume button on `task_args` only, so unregistered tasks show a generic "does not support automatic resume" error *after* the click; (c) no indication of *how* a resume behaves (checkpointed vs full rerun).
- **F10 — Extractor chunk chain**: hard-killed chunk link breaks the self-perpetuating chain; `BackgroundTask` stays `running` forever. Outside the TaskRun UI, but same class of problem.
- **F11 — Chord loss (RabbitMQ timeout) leaves batches stuck.** In the bulk-retrieval flows, if a chord *result* message is lost (broker restart, queue purge, timeout) the chord body never fires: `RetrievalBatch` sits in `QUERYING`/`RETRIEVING` indefinitely. No beat task or UI action detects or recovers this. A hard-killed `task_retrieve_patient_selection` (4 h limit) has the same effect.

## 1.4 Summary scorecard

| Module | Resumable | Not resumable |
|---|---|---|
| `client_app` | 9/9 long-running tasks | — |
| `deidentification` | 2/7 (bulk dispatcher, per-study link) | 5: legacy import, 2× zip build, create_missing_records, finalize batch |
| `dicom_archive` | 0/2 | archive, dearchive |
| `dicom_server` | 0/2 user-facing retrieval tasks | retrieve_studies, retrieve_patient_selection (+ stuck-batch recovery gap) |
| `extractor` | chunked embeddings, extraction jobs (own UI) | OCR / text-deid single-shot (short-lived) |

---

# PART 2 — REMEDIATION PLAN (BACKEND)

Design rules applied throughout:

1. **Registry membership = resumable.** Every long-running task gets a `TASK_REGISTRY` entry; the UI derives button visibility from it (Part 3).
2. **Every long-running task catches `SoftTimeLimitExceeded`** and calls `_auto_continue_task(...)` (existing helper, capped at 20 attempts).
3. **Checkpoints are keyed on stable identifiers** — `TaskRun.pk` or a dispatch-time `run_key` — never on `self.request.id` (F8).
4. **Inputs survive failure.** Uploaded/temp inputs are deleted only on success; a beat cleanup reaps stale ones.
5. **Reruns skip completed work** via manifest or DB status flags; where that is impossible (zips), the rerun is a documented full rebuild.

## Phase 0 — Foundation (no behavior change)

1. **`client_app/services/task_checkpoint.py`** — extend for payload-carrying entries:
   - `write_manifest_entry(path, item_id, status='done', payload=None)` — include optional JSON payload (needed to restore `unmatched_rows` on resume, Phase 1).
   - `read_manifest_entries(path) -> dict[item_id, entry]` — full entries, not just the done-set. Keep `read_manifest()` as a thin wrapper for existing callers.
2. **`client_app/tasks.py`** — add helper:
   ```python
   def stable_manifest_key(task_run, prefix):
       """Manifest key stable across resumes (TaskRun pk survives redispatch)."""
       return manifest_path_for_task(f"{prefix}-{task_run.pk}")
   ```
3. **`client_app/views.py`** — expose resumability to templates:
   - `RESUME_NOTES: dict[task_name, str]` — one-line UI hint per task, e.g. `"Resumes from the last checkpoint"`, `"Reruns from the start (idempotent)"`, `"Rebuilds the ZIP from the start"`.
   - `TaskRun.is_resumable` property (or view-level helper): `task_args is not None and task_name in TASK_REGISTRY`.
4. **Standard timeout handler pattern** (copy-paste block used by every task fixed below):
   ```python
   except SoftTimeLimitExceeded:
       logger.warning("%s hit soft time limit — auto-continuing", task_name)
       if _auto_continue_task(task_run, <this_task>, self.request.args, self.request.kwargs,
                              reason="approaching soft time limit"):
           return {'auto_continued': True}
       raise
   ```

## Phase 1 — `import_legacy_mapping_task` (the reported task; do first)

Files: `deidentification/tasks.py`, `deidentification/services/legacy_import.py`,
`deidentification/views.py`, `client_app/tasks.py` (cleanup beat).

1. **Stop destroying inputs (F1.3).**
   - Remove the `finally` block that unlinks `db_path`/`key_path`.
   - Delete the temp files **only on the success path** (after `_complete_task_run`).
   - Extend `task_cleanup_stale_exports` to also sweep `MEDIA_ROOT/legacy_import_tmp/*` older than 24 h (a resume within 24 h keeps its files; older abandoned uploads are reaped).
2. **Add checkpointing (F1.4).**
   - Service signature:
     ```python
     def import_legacy_mappings(db_path, key_path, progress_callback=None,
                                completed_items=None, manifest_write_callback=None) -> dict
     ```
   - Item ids: `patient:<original_id>`, `study:<study_uid>`, `series:<series_uid>`, `instance:<sop_uid>`.
   - Per row: if item id in `completed_items` → skip (do not re-decrypt/re-query); otherwise process and call `manifest_write_callback(item_id, status, payload)` where `status` is `done` or `unmatched` and `payload` carries the unmatched-row dict (so `unmatched_rows` is reconstructable after resume).
   - **Stream rows** (`cursor.execute(...)` + `fetchmany(500)` loop) instead of `fetchall()` — bounds memory on large DBs.
   - **Cap `unmatched_rows`** in `result_summary` (e.g. first 5 000 + `unmatched_total` count) to bound the JSON column; `LegacyImportResultsView` already paginates from this list.
   - Rebuild `stats` counters from manifest entries + new work so progress and the final summary are correct after a resume.
   - Task side: create the TaskRun first, then
     ```python
     manifest_path = stable_manifest_key(task_run, 'legacy-import')
     task_run.manifest_path = str(manifest_path); task_run.save(update_fields=[...])
     completed = read_manifest_entries(manifest_path)
     ```
     and pass `completed_items`/callback into the service. `cleanup_manifest()` on success.
3. **Timeout handling (F1.2).** Add the Phase-0 `SoftTimeLimitExceeded` block. Keep `soft_time_limit=600`: each continuation picks up at the last checkpointed row; 20 continuations × 10 min covers very large DBs, after which the run fails with the existing "attempts exhausted" message and is still UI-resumable.
4. **Registry (F1.1).** Add `'import_legacy_mapping': import_legacy_mapping_task` to `TASK_REGISTRY` (+ `RESUME_NOTES` entry: "Resumes from the last imported row").
5. **View** (`LegacyImportView.post`): no change required — the uuid temp names already make inputs unique; they now simply survive failure.

Result: timeout → auto-continue; worker death/broker loss → stall detection marks `STALLED` → **Resume in UI continues from the last checkpointed row**; inputs intact.

## Phase 2 — Remaining `deidentification` tasks

1. **`build_dicom_download_zip_task` / `build_clinical_download_zip_task` (F2)**
   - Add both to `TASK_REGISTRY` (+ notes: "Rebuilds the ZIP from the start").
   - Replace the fail-only `SoftTimeLimitExceeded` block with the Phase-0 auto-continue pattern.
   - Key the output zip on a **stable id** (TaskRun pk, resolved after `_create_task_run`) instead of `self.request.id`, so a resume overwrites the same file rather than orphaning the partial one. (ZIP format is not appendable — resume is a full rebuild; document that in the UI note.)
2. **`create_missing_records_task` (F3)**
   - Add to `TASK_REGISTRY` (+ note: "Reruns from the start; existing records are skipped").
   - Add the Phase-0 auto-continue block. Rerun is already idempotent (existence checks), so no manifest needed.
   - Optional hardening: if `len(records)` is large, the dispatch message and `task_args` JSON grow — consider passing a `TaskRun`-stored payload reference instead of inline records if this ever exceeds a few MB.
3. **`finalize_deidentification_batch_task` (F4)**
   - Add to `TASK_REGISTRY` (+ note: "Re-aggregates recorded per-study results").
   - Already idempotent (reads parent `result_summary`, rewrites terminal state, cleans manifests). This un-sticks parent runs whose finalize link died.

## Phase 3 — `dicom_archive` tasks (F5)

1. **`archive_studies_task`**
   - Add to `TASK_REGISTRY`; add Phase-0 auto-continue block.
   - Make `archive_studies()` idempotent: before archiving, skip studies whose `ArchivedStudy` record is already `ARCHIVED` at the target location (report under a new `skipped` key, not `failed`). This turns a resume into "finish the remaining studies".
2. **`dearchive_studies_task`**
   - Add to `TASK_REGISTRY`; add Phase-0 auto-continue block.
   - Already idempotent (`dearchive_studies` skips uids without an `ARCHIVED` record; a failed study stays `ARCHIVED` and is retried).

## Phase 4 — `dicom_server` retrieval (F6, F7, F11)

1. **Fix the time-limit bug (F6).** Give `task_retrieve_studies` the same explicit limits as `task_retrieve_patient_selection`:
   ```python
   @shared_task(bind=True, time_limit=4 * 3600, soft_time_limit=3.5 * 3600)
   ```
   so the existing 3.5 h graceful deadline in `_run_job_retrieval` can actually fire (job → `PARTIAL`, remaining items marked failed with the timeout reason) instead of a 1 h SIGKILL leaving the job `RUNNING`.
2. **Make reruns incremental (F7).** In `_run_job_retrieval`, pre-load the outcome of already-processed items and skip them:
   ```python
   done = { (s.study_instance_uid, s.series_instance_uid): s
            for s in job.studies.prefetch_related('series') ... if s.status == 'done' }
   ```
   For each `done` item: fold its stored `completed` count into `instances`, append its stored stats to `item_results`, and `continue` (still counting toward progress). Everything else runs as today. This makes both manual resume and auto-continue genuinely continue rather than re-pull.
3. **Registry (F6/F7).** Add `'dicom_server.task_retrieve_studies'` and `'dicom_server.task_retrieve_patient_selection'` to `TASK_REGISTRY` (+ notes: "Re-runs only the studies/series not yet retrieved").
4. **Stuck-batch recovery for lost chords (F11).** New beat task, e.g. `task_recover_stuck_batches` (every 5 min):
   - `RetrievalBatch` in `QUERYING` where **all** `RetrievalBatchPatient.query_status` are terminal (`DONE`/`ERROR`) but the batch never advanced → re-dispatch the matching finalizer (`task_finalize_batch_query` for manual batches, `task_bulk_schedule_finalize_query` for scheduled ones).
   - `RetrievalBatch` in `RETRIEVING` where **all** jobs are terminal but the batch never advanced → re-dispatch `task_finalize_retrieval_batch` / `task_bulk_schedule_finalize_retrieval`.
   - Batch in either state with **no row-level progress for > 30 min** and not all-terminal → mark `FAILED` with a clear `error_log` ("chord lost / no progress") + user notification, so the UI shows a recoverable failure instead of an eternal spinner.
   - Both finalizers are idempotent aggregations, so re-firing them is safe.
5. **UI hook for batches** (implemented with Part 3): on the batch detail view, when the batch is stuck (`FAILED` via recovery, or `QUERYING`/`RETRIEVING` older than the threshold), show a "Re-finalize batch" button that calls the same finalizer dispatch.

---

# PART 3 — UI CHANGES, VERIFICATION, ROLLOUT

## Phase 5 — Task Runs UI (F9)

### 5.1 `client_app/views.py`

- **`TaskRunListView.get_context_data` / `TaskRunDetailView.get_context_data`**: add
  ```python
  ctx['resumable_task_names'] = set(TASK_REGISTRY)
  ctx['resume_notes'] = RESUME_NOTES
  ```
  and annotate each `TaskRun` with `can_resume` (status in `FAILURE`/`STALLED` + `task_args` + name in registry) — either via a model property (preferred, reusable in all three templates) or a context list.
- **`TaskProgressView.get_context_data`**: look up `TaskRun.objects.filter(task_id=kwargs['task_id']).first()` and pass it as `task_run` (plus `can_resume`/`resume_note`). This is what lets the progress page offer a direct resume.
- **`TaskRunResumeView` / `TaskRunRetryView`**: distinguish the two failure modes in the error message — *"this task type does not support resume"* (not in registry) vs *"no stored arguments"* (pre-registry run).

### 5.2 `templates/client_app/taskrun_list.html`

- Replace the `{% if task.task_args %}` gate on the Resume button with `{% if task.can_resume %}`.
- In the `else` branch, keep the "N/A" chip but make the reason specific:
  - not in registry → "This task type cannot be resumed"
  - no stored args → existing "predates automatic resume support" text.
- Optionally show the `resume_notes` text as the button tooltip (`title=`).

### 5.3 `templates/client_app/taskrun_detail.html`

- Same `can_resume` gating for Resume/Retry.
- Add a "Resume behavior" line under the actions when `can_resume`: the `RESUME_NOTES` entry (e.g. "Resumes from the last checkpoint" vs "Reruns from the start (idempotent)") so users know what to expect.
- The existing **Celery State** field is the diagnostic for "task lost to broker": `PENDING` forever + TaskRun `STALLED` ⇒ safe to Resume. Keep it visible (it already is).

### 5.4 `templates/client_app/task_progress.html`

- In the `errorContainer` (FAILURE state), add, when `task_run` and `task_run.can_resume`:
  - a **Resume task** button — a small POST form to `{% url 'client_app:taskrun_resume' task_run.pk %}` with CSRF (the view redirects to the *new* task's progress page, so polling continues seamlessly);
  - a **View task details** link to `taskrun_detail`.
- When the task is not resumable, show the specific reason line instead.
- Also handle the "stalled, not failed" case: if polling sees the Celery state is `PENDING`/`UNKNOWN` for an extended period while `task_run.status == 'STALLED'`, surface the same Resume CTA (currently the page just keeps spinning on "Waiting to start...").

## Phase 6 — Verification

### 6.1 Unit/integration tests (per fixed task)

Pattern: dispatch the task against a fixture, simulate a mid-run death, redispatch via the **same code path the UI uses** (`_redispatch_task_run`), assert completed items are not redone.

| Task | Simulated failure | Assert after resume |
|---|---|---|
| `import_legacy_mapping` | raise after N rows (mock service) / inject `SoftTimeLimitExceeded` | manifest has N entries; resume processes only remaining rows; `unmatched_rows` identical to no-failure run; temp files deleted only on success; auto-continue fires on soft limit |
| `build_dicom_download_zip` / `build_clinical_download_zip` | kill mid-zip | resume rebuilds to the **same** zip path; old partial not orphaned |
| `create_missing_records` | raise mid-list | second run creates 0 duplicates |
| `finalize_deidentification_batch` | kill after parent has partial results | resume finalizes parent correctly (idempotent) |
| `archive_studies` | kill mid-batch | resume archives only remaining studies; already-archived reported as `skipped`, not `failed` |
| `dearchive_studies` | kill mid-batch | resume de-archives only remaining |
| `task_retrieve_studies` | mock C-MOVE that fails after k items; also assert task now carries 4 h/3.5 h limits | resume re-retrieves only non-`done` items; `instances_received` not double-counted |
| `task_recover_stuck_batches` | batch in `QUERYING` with all rows terminal | finalizer re-dispatched exactly once; batch reaches `AWAITING_SELECTION`; no-progress case → `FAILED` + notification |

### 6.2 UI tests

- Resume button visible ⇔ `can_resume` (matrix: status × registry × args) on list + detail.
- Progress page: FAILURE + resumable ⇒ Resume form present; POST redirects to new progress URL.
- Non-resumable failure ⇒ specific reason text, no form.

### 6.3 Manual E2E (pre-prod)

1. Legacy import with a large SQLite DB; `kill -9` the worker mid-run; confirm `STALLED` after the beat sweep; click **Resume** in the UI; confirm it continues from the checkpoint and the temp files were still present.
2. Same for a bulk deid run (existing behavior regression check).
3. Stop RabbitMQ mid bulk-retrieval chord; restart; confirm `task_recover_stuck_batches` re-finalizes the batch.

## Rollout order

| Step | Content | Risk |
|---|---|---|
| 1 | Phase 0 (foundation: manifest payload, stable key, `is_resumable`, notes) | none — additive |
| 2 | Phase 1 (legacy import) — the reported fix | low; isolated task |
| 3 | Phase 5 (UI) — exposes everything fixed so far | low; template + context only |
| 4 | Phase 2 (other deid tasks) | low |
| 5 | Phase 3 (archive tasks) | low–medium (idempotency change in `archive_studies`) |
| 6 | Phase 4 (retrieval limits + incremental rerun + stuck-batch recovery) | medium — touches live C-MOVE paths; deploy the limit fix first, then skip-`done`, then the recovery beat |
| 7 | Phase 6 tests land with each step, not after | — |

## Out of scope / follow-ups (noted, not planned here)

- **F10 — extractor `BackgroundTask` chain**: add a stall sweeper for `BackgroundTask` rows stuck in `running` (re-dispatch the next chunk from `result_data`), or migrate extractor tracking onto `TaskRun` for a single UI.
- **F2 note**: true incremental ZIP building (per-study sidecar files merged at the end) would make zip tasks checkpointable like the export tasks; deferred — full-rebuild resume is acceptable.
- `task_args` payload size for `create_missing_records` with very large unmatched sets (see Phase 2.2).
- Consider a global `task_acks_late` + `reject_on_worker_lost` review for the 4 h retrieval tasks (long un-ACKed messages under broker restarts).

# Chunked Lookup Embeddings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one embedding chunk (≤100 texts of one lookup table) the unit of
Celery work, so no single task runs long enough to trip RabbitMQ's 30-minute
delivery-ack timeout — the `406 PRECONDITION_FAILED - delivery acknowledgement
timed out` that was force-closing the worker channel and causing the same table
to be embedded by several worker processes at once.

**Architecture:** Replace the "embed the whole table in one task" chain link with
a self-perpetuating chunk task. Each chunk task re-reads the DB (which rows
already have a current embedding), embeds the next bounded chunk, persists it,
then enqueues the next chunk. When a table is exhausted it advances to the next
table; the last table triggers `finalize_lookup_embeddings_task`. The DB is the
source of truth, so a redelivered / duplicate chunk is a harmless no-op (unique
constraint + `ignore_conflicts`). Each task now runs ~2–3 min (< 30 min), so the
ack timeout can't fire and duplicate execution can't corrupt data. This is
**not** a chord / parallel fan-out — exactly one chunk task runs at a time, so
memory and provider load stay bounded.

**Tech Stack:** Django, Celery (prefork pool), RabbitMQ/AMQP, pgvector,
`sentence-transformers` / OpenAI-compatible embedding providers.

**Spec:** Session directive (Fix A, agreed in-conversation): *"each task checks
which values have embeddings from the database state (an acceptable DB lookup),
embeds the next 100 (or whatever is left for a small table), then the next task
is triggered and does the same; do not use a chord (it would start all chunks at
once and swamp memory/CPU); do not worry about the per-task DB lookups —
embeddings are computed once, not daily."* No separate spec file.

## Global Constraints

- Tests run with `python manage.py test extractor.tests.<Class> -v 2` from the
  repo root (Django `TestCase`). The full suite is `python manage.py test
  extractor`.
- `close_old_connections()` calls are patched to no-ops in tests
  (`extractor.services.embedding_index.close_old_connections` and
  `extractor.tasks.close_old_connections`) because they are fatal inside
  `TestCase`'s wrapping transaction. Follow the existing pattern in
  `EmbeddingIndexTests.setUp` (patch both targets in `setUp`, stop via
  `addCleanup`).
- The embedding provider is mocked in tests by patching
  `extractor.services.embedding_index.get_provider`.
- `LookupEmbedding` has a `UniqueConstraint` on
  `[content_type, object_id, field_name, embedding_config, index_version]`; all
  embedding writes use `bulk_create(..., ignore_conflicts=True)` so re-embedding
  the same row is a no-op.
- `task_id` MUST remain the **first positional arg** of every embedding task so
  the view's `_inflight_embedding_tasks_alive` substring match on
  `t.get('args')` (extractor/views_semantic_search.py:34) keeps working.
- Preserve refresh build-then-swap semantics: a refresh writes under
  `config.version + 1` and only swaps on full success; a gap-fill writes under
  the live `config.version`.
- The management-command path (`compute_lookup_embeddings` service,
  extractor/management/commands/compute_lookup_embeddings.py) must keep working —
  the existing `EmbeddingIndexTests` (extractor/tests.py:1588) must still pass.
- Sequential, self-perpetuating dispatch only. Do NOT introduce a chord or
  parallel fan-out.
- There are 56 lookup models (`app_label='lookup'`); `LookupLaterality.model`
  is `'lookuplaterality'`. Tests that assert a table name must use the
  lowercase model name.

---

### Task 1: Add chunk primitives to the embedding service

Extract the "find what's left to embed" and "embed + persist one chunk" logic
out of `compute_lookup_table_embeddings` into reusable, testable functions.
These become the building blocks for both the serial management-command path and
the new self-perpetuating Celery chunk task (Tasks 2–3).

**Files:**
- Modify: `extractor/services/embedding_index.py` (add `CHUNK_SIZE` +
  `_lookup_model`, `_source_rows`, `prepare_table`, `collect_pending_rows`,
  `embed_one_chunk`)
- Test: `extractor/tests.py` (new `ChunkedEmbeddingServiceTests`)

**Interfaces:**
- Produces (all in `extractor/services/embedding_index.py`):
  - `CHUNK_SIZE: int` — module constant, default `100`.
  - `_lookup_model(content_type) -> Optional[Model]`
  - `_source_rows(content_type) -> List[Tuple[str, str, str]]` — every
    `(object_id, field_name, text_value)` that should carry an embedding, sorted
    by `(object_id, field_name)`.
  - `prepare_table(config, content_type, target_version) -> None` — idempotent
    stale-flag + non-current delete at the target generation.
  - `collect_pending_rows(config, content_type, target_version,
    exclude_keys=frozenset(), chunk_size=CHUNK_SIZE) ->
    Tuple[List[Tuple[str, str, str]], int]` — returns `(chunk, remaining)`;
    `chunk == []` when the table is exhausted. `exclude_keys` is a set of
    `(object_id, field_name)` tuples.
  - `embed_one_chunk(provider, config, content_type, target_version, chunk) ->
    Tuple[int, int, List[Tuple[str, str]]]` — returns
    `(count, failed, failed_keys)`.

- [ ] **Step 1: Write the failing tests**

Add to `extractor/tests.py` (imports at the top of the file already include
`TestCase`, `ContentType`, and `patch`/`Mock` — verify and reuse, adding
`from unittest.mock import patch, Mock` if missing):

```python
class ChunkedEmbeddingServiceTests(TestCase):
    """collect_pending_rows / embed_one_chunk tile a table into bounded,
    stable, non-overlapping chunks and make re-embedding a no-op."""

    def setUp(self):
        from lookup.models import LookupLaterality
        from extractor.models import EmbeddingConfiguration

        self.model = LookupLaterality
        self.ct = ContentType.objects.get_for_model(LookupLaterality)
        self.config = EmbeddingConfiguration.objects.create(
            model_name='test-embed', model_provider='sentence-transformers',
            embedding_dimension=384, is_active=True)
        for code, label in (('C1', 'zz-lab-a'), ('C2', 'zz-lab-b'),
                            ('C3', 'zz-lab-c'), ('C4', 'zz-lab-d')):
            LookupLaterality.objects.create(code=code, label=label)

        # The builder calls close_old_connections() — fatal inside TestCase's
        # wrapping transaction.
        for target in (
                'extractor.services.embedding_index.close_old_connections',
                'extractor.tasks.close_old_connections'):
            patcher = patch(target, lambda: None)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def _provider(texts_seen=None):
        provider = Mock()
        def embed(texts):
            if texts_seen is not None:
                texts_seen.extend(texts)
            return [[0.1] * 384 for _ in texts]
        provider.embed_texts.side_effect = embed
        return provider

    def test_collect_pending_returns_first_chunk_and_remaining(self):
        from extractor.services.embedding_index import collect_pending_rows
        chunk, remaining = collect_pending_rows(
            self.config, self.ct, 1, chunk_size=2)
        self.assertEqual(remaining, 4)
        self.assertEqual(len(chunk), 2)
        self.assertEqual([r[0] for r in chunk], ['C1', 'C2'])
        self.assertEqual([r[1] for r in chunk], ['label', 'label'])

    def test_collect_pending_excludes_embedded_and_failed(self):
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import collect_pending_rows

        LookupEmbedding.objects.create(
            content_type=self.ct, object_id='C1', field_name='label',
            text_value='zz-lab-a', embedding=[0.1] * 384,
            embedding_config=self.config, index_version=1)

        chunk, remaining = collect_pending_rows(
            self.config, self.ct, 1,
            exclude_keys={('C2', 'label')}, chunk_size=10)
        ids = [r[0] for r in chunk]
        self.assertNotIn('C1', ids)  # already embedded
        self.assertNotIn('C2', ids)  # excluded (previously failed)
        self.assertEqual(ids, ['C3', 'C4'])
        self.assertEqual(remaining, 2)

    def test_embed_one_chunk_writes_and_reports(self):
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import embed_one_chunk

        chunk = [('C1', 'label', 'zz-lab-a'), ('C2', 'label', 'zz-lab-b')]
        count, failed, failed_keys = embed_one_chunk(
            self._provider(), self.config, self.ct, 1, chunk)
        self.assertEqual((count, failed), (2, 0))
        self.assertEqual(failed_keys, [])
        self.assertEqual(
            LookupEmbedding.objects.filter(index_version=1).count(), 2)

    def test_embed_one_chunk_returns_failed_keys_on_error(self):
        from extractor.services.embedding_index import embed_one_chunk

        failing = Mock()
        failing.embed_texts.side_effect = RuntimeError('boom')
        chunk = [('C1', 'label', 'zz-lab-a'), ('C2', 'label', 'zz-lab-b')]
        count, failed, failed_keys = embed_one_chunk(
            failing, self.config, self.ct, 1, chunk)
        self.assertEqual((count, failed), (0, 2))
        self.assertEqual(failed_keys, [('C1', 'label'), ('C2', 'label')])

    def test_embed_one_chunk_is_idempotent(self):
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import embed_one_chunk

        chunk = [('C1', 'label', 'zz-lab-a')]
        embed_one_chunk(self._provider(), self.config, self.ct, 1, chunk)
        embed_one_chunk(self._provider(), self.config, self.ct, 1, chunk)
        self.assertEqual(
            LookupEmbedding.objects.filter(index_version=1).count(), 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test extractor.tests.ChunkedEmbeddingServiceTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'collect_pending_rows'`
(and `embed_one_chunk`).

- [ ] **Step 3: Write the implementation**

Add to `extractor/services/embedding_index.py`. Place `CHUNK_SIZE` right after
the existing `NON_SEMANTIC_FIELDS` constant; place the functions after
`_text_fields` (they reuse `_text_fields`, `composite_label_spec`,
`build_lookup_label`, `COMBINED_LABEL_FIELD`, `SemanticSearchService`,
`LookupEmbedding`, `close_old_connections` — all already imported in the module):

```python
# Bounded unit of work per Celery chunk task. Chosen so a single chunk stays
# well under the broker's 30-minute delivery-ack timeout.
CHUNK_SIZE = 100


def _lookup_model(content_type):
    return content_type.model_class()


def _source_rows(content_type):
    """
    Every (object_id, field_name, text_value) that should carry an embedding,
    in stable (object_id, field_name) order. A record may contribute several
    rows (one per semantic text field, plus the composite '__label__' when a
    DatabaseField declares label fields). Empty texts are skipped.
    """
    model = _lookup_model(content_type)
    if not model:
        return []
    pk_field = model._meta.pk.name
    text_fields = _text_fields(model)
    label_spec = composite_label_spec(content_type)
    rows = []
    for record in model.objects.all().iterator():
        pk = str(getattr(record, pk_field))
        for field in text_fields:
            value = str(getattr(record, field, '') or '')
            if value.strip():
                rows.append((pk, field, value))
        if label_spec:
            label = build_lookup_label(record, label_fields=label_spec)
            if label.strip():
                rows.append((pk, COMBINED_LABEL_FIELD, label))
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def prepare_table(config, content_type, target_version) -> None:
    """
    Idempotent per-table setup: flag stale rows (source gone/changed) and drop
    non-current rows at the target generation so collect_pending_rows sees a
    clean picture. Safe to run on every chunk — after the first pass it is a
    no-op (rows are already non-current / deleted).
    """
    model = _lookup_model(content_type)
    if not model:
        return
    SemanticSearchService.mark_stale_embeddings(
        content_type, model,
        embedding_config=config, index_version=target_version)
    LookupEmbedding.objects.filter(
        content_type=content_type, embedding_config=config,
        index_version=target_version, is_current=False,
    ).delete()


def collect_pending_rows(config, content_type, target_version,
                         exclude_keys=frozenset(), chunk_size=CHUNK_SIZE):
    """
    The next bounded chunk of rows still needing an embedding at
    target_version, plus the total remaining count.

    Skips rows already present (is_current=True at target_version) and any key
    in exclude_keys (per-run failures we are not retrying). Returns
    (chunk, remaining) where chunk is [] once the table is exhausted. Rows are
    tiled in stable (object_id, field_name) order so successive chunks never
    overlap.
    """
    prepare_table(config, content_type, target_version)
    embedded = set(
        LookupEmbedding.objects.filter(
            content_type=content_type, embedding_config=config,
            index_version=target_version, is_current=True,
        ).values_list('object_id', 'field_name')
    )
    pending = [
        row for row in _source_rows(content_type)
        if (row[0], row[1]) not in embedded
        and (row[0], row[1]) not in exclude_keys
    ]
    return pending[:chunk_size], len(pending)


def embed_one_chunk(provider, config, content_type, target_version, chunk):
    """
    Encode + persist one chunk. Returns (count, failed, failed_keys).

    On an encode error the chunk's keys are returned as failed_keys so the
    caller can exclude them on the next pass instead of retrying the same rows
    forever. Writes use ignore_conflicts so a duplicate/re-run chunk is a
    no-op.
    """
    if not chunk:
        return 0, 0, []
    texts = [text for _, _, text in chunk]
    close_old_connections()  # encode idles the DB connection for minutes
    try:
        vectors = provider.embed_texts(texts)
        if len(vectors) != len(chunk):
            raise ValueError(
                f"provider returned {len(vectors)} embeddings "
                f"for {len(chunk)} texts")
    except Exception:
        close_old_connections()
        return 0, len(chunk), [(pk, field) for pk, field, _ in chunk]
    rows = [LookupEmbedding(
        content_type=content_type, object_id=pk, field_name=field,
        text_value=text, embedding=vector,
        embedding_config=config, index_version=target_version,
    ) for (pk, field, text), vector in zip(chunk, vectors)]
    LookupEmbedding.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows), 0, []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test extractor.tests.ChunkedEmbeddingServiceTests -v 2`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add extractor/services/embedding_index.py extractor/tests.py
git commit -m "feat(embeddings): add collect_pending_rows + embed_one_chunk chunk primitives"
```

### Task 2: Refactor `compute_lookup_table_embeddings` onto the chunk primitives

Rewrite the serial table builder to loop over `collect_pending_rows` /
`embed_one_chunk` instead of inlining the chunk loop. This DRYs the two paths
(management command vs. Celery) onto one "how to embed a chunk" definition and
preserves the existing per-row resume, stale-repair, and build-then-swap
behavior that `EmbeddingIndexTests` covers.

**Files:**
- Modify: `extractor/services/embedding_index.py` (replace the body of
  `compute_lookup_table_embeddings`; update its docstring; update the module
  top docstring and the `compute_lookup_embeddings` docstring to describe the
  new self-perpetuating chunk task)

**Interfaces:**
- Consumes: `collect_pending_rows`, `embed_one_chunk`, `get_provider`,
  `close_old_connections`, `_text_fields`, `composite_label_spec` (all in the
  same module).
- Produces: `compute_lookup_table_embeddings(config, content_type,
  target_version, refresh=False, progress_callback=None) ->
  Dict[str, Any]` with the SAME signature and return shape
  (`{'table', 'count', 'failed'}`) it has today — callers and tests are
  unchanged.

- [ ] **Step 1: Confirm the existing tests are the safety net**

Run: `python manage.py test extractor.tests.EmbeddingIndexTests -v 2`
Expected: PASS (this is the baseline you must not regress).

- [ ] **Step 2: Replace the function body**

> **Executed-deviation note (2026-10-13):** the first draft used a `while True:
> collect_pending_rows(...)` loop in the *serial* path, which re-scans the source
> table on every chunk → O(N²) on big tables (test suite blew up to ~3847s from
> ~56s). The serial path instead builds the pending list **once** (O(N)) and
> tiles it, calling `embed_one_chunk` per slice. The per-chunk DB re-read is kept
> only in the Celery chunk task (Task 3), where each task is one chunk so the
> single read is amortized. `collect_pending_rows` is therefore used by Task 3,
> not by the serial path below.

In `extractor/services/embedding_index.py`, replace the entire current
`compute_lookup_table_embeddings` function (from `def compute_lookup_table_` 
down through its `return {'table', ...}`) with:

```python
def compute_lookup_table_embeddings(
    config: EmbeddingConfiguration,
    content_type: ContentType,
    target_version: int,
    refresh: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Embed one lookup table's semantic text fields under the given index
    generation by tiling the table into bounded chunks (collect_pending_rows /
    embed_one_chunk). This is the serial driver for the management-command
    path; the Celery path (extractor.tasks.embed_lookup_table_chunk) runs the
    same primitives one chunk at a time.

    Builds resume per row: a target-version row whose stored text still matches
    the source is skipped in both refresh and gap-fill modes. Returns
    {'table', 'count', 'failed'}. Provider setup failures propagate as
    EmbeddingUnavailableError so callers can treat them as fatal.
    """
    notify = progress_callback or (lambda msg: None)
    provider = get_provider(config)  # raises EmbeddingUnavailableError

    lookup_model = content_type.model_class()
    table_name = content_type.model
    if not lookup_model:
        return {'table': table_name, 'count': 0, 'failed': 0}
    close_old_connections()  # model load idles the connection; drop it
    notify(f"Indexing {table_name}")

    text_fields = _text_fields(lookup_model)
    label_spec = composite_label_spec(content_type)
    if not text_fields and not label_spec:
        return {'table': table_name, 'count': 0, 'failed': 0}

    new_count = 0
    table_failed = 0
    # One-shot setup + a single O(N) pass to build the full pending list, then
    # tile it. (The Celery chunk task instead re-reads the DB per task via
    # collect_pending_rows — correct there because each task is one chunk.)
    # Re-scanning the source on every chunk here would be O(N^2) on big tables.
    prepare_table(config, content_type, target_version)
    embedded = set(
        LookupEmbedding.objects.filter(
            content_type=content_type, embedding_config=config,
            index_version=target_version, is_current=True,
        ).values_list('object_id', 'field_name')
    )
    pending = [
        row for row in _source_rows(content_type)
        if (row[0], row[1]) not in embedded
    ]
    chunk_total = (len(pending) + CHUNK_SIZE - 1) // CHUNK_SIZE if pending else 0
    for chunk_number, i in enumerate(range(0, len(pending), CHUNK_SIZE), 1):
        chunk = pending[i:i + CHUNK_SIZE]
        first_key = f"{chunk[0][0]}.{chunk[0][1]}"
        last_key = f"{chunk[-1][0]}.{chunk[-1][1]}"
        log.info(
            "Embedding %s v%s chunk %s/%s: %s texts (%s to %s)",
            table_name, target_version, chunk_number, chunk_total,
            len(chunk), first_key, last_key)
        encode_started = perf_counter()
        count, failed, _failed_keys = embed_one_chunk(
            provider, config, content_type, target_version, chunk)
        new_count += count
        table_failed += failed
        if count:
            log.info(
                "Saved %s v%s chunk %s/%s: %s rows (encode %.2fs)",
                table_name, target_version, chunk_number, chunk_total,
                count, perf_counter() - encode_started)

    return {'table': table_name, 'count': new_count, 'failed': table_failed}
```

- [ ] **Step 3: Update the three docstrings to describe the new architecture**

Update the module top docstring in `embedding_index.py` — replace the line that
reads "Celery (extractor.tasks): a chain of compute_lookup_table_embeddings_task
links, one per lookup table, followed by finalize_lookup_embeddings_task." with:

```text
- Celery (extractor.tasks.embed_lookup_table_chunk): a self-perpetuating task
  that embeds one bounded chunk of one lookup table, then enqueues the next
  chunk; the last table triggers finalize_lookup_embeddings_task.
```

In `compute_lookup_embeddings`'s docstring, replace "The Celery path runs the
same steps as a per-table chain (extractor.tasks)." with "The Celery path runs
the same primitives as a self-perpetuating per-chunk task
(extractor.tasks.embed_lookup_table_chunk)."

- [ ] **Step 4: Run the existing tests to verify no regression**

Run: `python manage.py test extractor.tests.EmbeddingIndexTests -v 2`
Expected: PASS (all previous tests — refresh swap, resume, gap-fill re-embed,
partial-failure no-swap, etc.).

- [ ] **Step 5: Commit**

```bash
git add extractor/services/embedding_index.py
git commit -m "refactor(embeddings): drive table build from chunk primitives (serial path)"
```

### Task 3: Add the self-perpetuating chunk task + table-advance helper

Replace `compute_lookup_table_embeddings_task` with `embed_lookup_table_chunk`.
Each run embeds the next bounded chunk of one table and enqueues the next chunk;
when a table is exhausted it advances to the next table, and the last table
triggers finalize. This is the piece that makes every delivery short (no 406)
and makes duplicate execution a no-op.

**Files:**
- Modify: `extractor/tasks.py` (add `_advance_to_next_table_or_finalize`; replace
  `compute_lookup_table_embeddings_task` with `embed_lookup_table_chunk`).
  Leave `_record_table_result` and `finalize_lookup_embeddings_task` unchanged.
- Test: `extractor/tests.py` (new `ChunkedEmbeddingTaskTests`).

**Interfaces:**
- Consumes (from `extractor.services.embedding_index`): `collect_pending_rows`,
  `embed_one_chunk`, `get_provider`, `CHUNK_SIZE`, `close_old_connections`.
- Consumes (module-level in `extractor.tasks`): `BackgroundTask`,
  `EmbeddingConfiguration`, `ContentType`, `LookupEmbedding`,
  `EmbeddingUnavailableError`, `_record_table_result`,
  `finalize_lookup_embeddings_task`.
- Produces:
  - `embed_lookup_table_chunk(self, task_id, config_id, content_type_id,
    target_version, refresh, table_index, table_total)` — `@shared_task(bind=True)`.
    `table_index` is the 1-based position of the table being processed; `task_id`
    is first (inflight check).
  - `_advance_to_next_table_or_finalize(task_id, config_id, target_version,
    refresh, table_index, table_total)` — module-level helper.

- [ ] **Step 1: Write the failing tests**

Add to `extractor/tests.py`:

```python
class ChunkedEmbeddingTaskTests(TestCase):
    """embed_lookup_table_chunk tiles one table into bounded, self-perpetuating
    chunk tasks and terminates by advancing tables / finalizing."""

    def setUp(self):
        from lookup.models import LookupLaterality
        from extractor.models import EmbeddingConfiguration, BackgroundTask

        self.model = LookupLaterality
        self.ct = ContentType.objects.get_for_model(LookupLaterality)
        self.config = EmbeddingConfiguration.objects.create(
            model_name='test-embed', model_provider='sentence-transformers',
            embedding_dimension=384, is_active=True)
        self.task = BackgroundTask.objects.create(
            task_id='emb-task-1', task_name='Compute Lookup Embeddings',
            status='pending', result_data={'results': []})
        for code, label in (('C1', 'zz-lab-a'), ('C2', 'zz-lab-b'),
                            ('C3', 'zz-lab-c')):
            LookupLaterality.objects.create(code=code, label=label)

        for target in (
                'extractor.services.embedding_index.close_old_connections',
                'extractor.tasks.close_old_connections'):
            patcher = patch(target, lambda: None)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def _provider():
        p = Mock()
        p.embed_texts.side_effect = lambda texts: [[0.1] * 384 for _ in texts]
        return p

    def _run_chunk(self):
        from extractor.models import LookupEmbedding
        from extractor.tasks import (embed_lookup_table_chunk,
                                     finalize_lookup_embeddings_task)
        with patch('extractor.services.embedding_index.get_provider',
                   return_value=self._provider()), \
             patch('extractor.services.embedding_index.CHUNK_SIZE', 2), \
             patch.object(embed_lookup_table_chunk, 'apply_async') as nxt, \
             patch.object(finalize_lookup_embeddings_task, 'apply_async') as fin:
            embed_lookup_table_chunk.run(
                self.task.task_id, self.config.id, self.ct.id,
                1, False, 1, 1)
            rows = LookupEmbedding.objects.filter(index_version=1).count()
        return rows, nxt, fin

    def test_first_chunk_embeds_and_dispatches_next(self):
        rows, nxt, fin = self._run_chunk()
        self.assertEqual(rows, 2)                 # CHUNK_SIZE=2 -> first chunk
        self.assertTrue(nxt.called)               # table not done -> next chunk
        self.assertFalse(fin.called)
        # next chunk carries the same table, same table_index
        self.assertEqual(nxt.call_args[1]['args'],
                         [self.task.task_id, self.config.id, self.ct.id,
                          1, False, 1, 1])

    def test_last_chunk_finalizes_with_task_id_first(self):
        from extractor.models import LookupEmbedding
        self._run_chunk()                          # embeds C1, C2
        rows, nxt, fin = self._run_chunk()          # embeds C3 -> last
        self.assertEqual(rows, 3)
        self.assertFalse(nxt.called)
        self.assertTrue(fin.called)
        # finalize args: task_id FIRST (inflight check depends on it)
        self.assertEqual(fin.call_args[1]['args'],
                         [self.task.task_id, self.config.id, 1, False])

    def test_failed_chunk_is_recorded_not_retried(self):
        from extractor.models import LookupEmbedding
        from extractor.tasks import (embed_lookup_table_chunk,
                                     finalize_lookup_embeddings_task)
        failing = Mock()
        failing.embed_texts.side_effect = RuntimeError('down')
        with patch('extractor.services.embedding_index.get_provider',
                   return_value=failing), \
             patch('extractor.services.embedding_index.CHUNK_SIZE', 2), \
             patch.object(embed_lookup_table_chunk, 'apply_async') as nxt, \
             patch.object(finalize_lookup_embeddings_task, 'apply_async') as fin:
            # chunk 1: 2 rows fail -> recorded, next chunk dispatched
            embed_lookup_table_chunk.run(
                self.task.task_id, self.config.id, self.ct.id, 1, False, 1, 1)
            self.task.refresh_from_db()  # task saved result_data on a fresh row
            self.assertEqual(
                LookupEmbedding.objects.filter(index_version=1).count(), 0)
            self.assertTrue(nxt.called)
            self.assertEqual(
                len(self.task.result_data['failed']['lookuplaterality']), 2)
            # chunk 2: last row fails -> table exhausted -> finalize (no loop)
            embed_lookup_table_chunk.run(
                self.task.task_id, self.config.id, self.ct.id, 1, False, 1, 1)
        self.assertTrue(fin.called)

    def test_fatal_short_circuits_chain(self):
        from extractor.models import LookupEmbedding
        from extractor.tasks import (embed_lookup_table_chunk,
                                     finalize_lookup_embeddings_task)
        self.task.result_data = {'fatal': 'provider dead', 'results': []}
        self.task.save()
        with patch('extractor.services.embedding_index.get_provider') as gp, \
             patch.object(embed_lookup_table_chunk, 'apply_async') as nxt, \
             patch.object(finalize_lookup_embeddings_task, 'apply_async') as fin:
            embed_lookup_table_chunk.run(
                self.task.task_id, self.config.id, self.ct.id, 1, False, 1, 1)
        gp.assert_not_called()
        nxt.assert_not_called()
        fin.assert_not_called()
        self.assertEqual(LookupEmbedding.objects.count(), 0)

    def test_advance_dispatches_next_table_then_finalize(self):
        from django.contrib.contenttypes.models import ContentType
        from extractor.tasks import (_advance_to_next_table_or_finalize,
                                     embed_lookup_table_chunk,
                                     finalize_lookup_embeddings_task)
        tables = list(ContentType.objects.filter(app_label='lookup')
                             .order_by('id'))
        self.assertGreaterEqual(len(tables), 2)
        with patch.object(embed_lookup_table_chunk, 'apply_async') as nxt, \
             patch.object(finalize_lookup_embeddings_task, 'apply_async') as fin:
            _advance_to_next_table_or_finalize(
                'tid', self.config.id, 1, False, 1, len(tables))
        self.assertTrue(nxt.called)
        self.assertFalse(fin.called)
        # 1-based table_index=1 finished -> next is tables[1], index 2
        self.assertEqual(nxt.call_args[1]['args'],
                         ['tid', self.config.id, tables[1].id, 1, False,
                          2, len(tables)])
        with patch.object(embed_lookup_table_chunk, 'apply_async') as nxt2, \
             patch.object(finalize_lookup_embeddings_task, 'apply_async') as fin2:
            _advance_to_next_table_or_finalize(
                'tid', self.config.id, 1, False, len(tables), len(tables))
        self.assertFalse(nxt2.called)
        self.assertTrue(fin2.called)
        self.assertEqual(fin2.call_args[1]['args'],
                         ['tid', self.config.id, 1, False])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test extractor.tests.ChunkedEmbeddingTaskTests -v 2`
Expected: FAIL — `cannot import name 'embed_lookup_table_chunk'` / no
`_advance_to_next_table_or_finalize`.

- [ ] **Step 3: Add the advance helper + chunk task**

In `extractor/tasks.py`, replace the entire `compute_lookup_table_embeddings_task`
function (from `@shared_task(bind=True)` / `def compute_lookup_table_embeddings_task` 
down through its final `_record_table_result(...)` line, and immediately after it
insert the new helpers). Keep `_record_table_result` (above it) and
`finalize_lookup_embeddings_task` (below it) untouched. New code:

```python
def _advance_to_next_table_or_finalize(task_id, config_id, target_version,
                                       refresh, table_index, table_total):
    """
    After a table's last chunk: dispatch the first chunk task of the next lookup
    table, or the finalize task if this was the last one. table_index is the
    1-based position of the table that just finished; table_total is the number
    of tables captured when the build was dispatched (so the boundary matches
    the build's own table set, not whatever the live table count is now).
    """
    if table_index < table_total:
        tables = list(ContentType.objects.filter(app_label='lookup').order_by('id'))
        next_ct = tables[table_index]  # 0-based: current was tables[table_index-1]
        embed_lookup_table_chunk.apply_async(args=[
            task_id, config_id, next_ct.id, target_version, refresh,
            table_index + 1, table_total])
    else:
        finalize_lookup_embeddings_task.apply_async(args=[
            task_id, config_id, target_version, refresh])


@shared_task(bind=True)
def embed_lookup_table_chunk(self, task_id, config_id, content_type_id,
                             target_version, refresh, table_index, table_total):
    """
    One self-perpetuating unit of work: embed the next chunk (<= CHUNK_SIZE
    texts) of ONE lookup table, then enqueue the next chunk.

    Reads the DB for what still needs embedding, so a redelivered or duplicate
    chunk is a harmless no-op (unique constraint + ignore_conflicts). When the
    table is exhausted it advances to the next table; the last table triggers
    finalize_lookup_embeddings_task.

    Deliberately short (< 30 min) so each delivery is ACKed well before the
    broker's consumer_ack_timeout — the 406 delivery-ack timeout can't fire and
    duplicate execution can't corrupt data.
    """
    import extractor.services.embedding_index as ei

    close_old_connections()
    task = BackgroundTask.objects.get(task_id=task_id)
    data = task.result_data or {}

    # A prior chunk already recorded a provider failure — stop the chain.
    if data.get('fatal'):
        return

    content_type = ContentType.objects.get(id=content_type_id)
    table_name = content_type.model

    try:
        config = EmbeddingConfiguration.objects.get(id=config_id)
    except EmbeddingConfiguration.DoesNotExist:
        task.mark_failed('Configuration not found')
        return

    # Keys this table failed on earlier this run (excluded, not retried).
    exclude_keys = set(map(tuple, data.get('failed', {}).get(table_name, [])))

    # Read phase: find the next chunk. A failure here is a table-level error.
    try:
        chunk, remaining = ei.collect_pending_rows(
            config, content_type, target_version,
            exclude_keys=exclude_keys, chunk_size=ei.CHUNK_SIZE)
    except EmbeddingUnavailableError as e:
        data['fatal'] = str(e)
        task.result_data = data
        task.mark_failed(f"Embedding provider unavailable: {e}")
        return
    except Exception as e:
        log.error(f"Collect failed for {table_name}: {e}", exc_info=True)
        _record_table_result(
            task, {'table': table_name, 'count': 0, 'failed': 0,
                   'error': str(e)}, table_index, table_total)
        _advance_to_next_table_or_finalize(
            task_id, config_id, target_version, refresh,
            table_index, table_total)
        return

    # Table already exhausted (e.g. resume after a crash) -> record + advance.
    if not chunk:
        _record_table_result(
            task, {
                'table': table_name,
                'count': LookupEmbedding.objects.filter(
                    content_type=content_type, embedding_config=config,
                    index_version=target_version, is_current=True).count(),
                'failed': len(exclude_keys),
            }, table_index, table_total)
        _advance_to_next_table_or_finalize(
            task_id, config_id, target_version, refresh,
            table_index, table_total)
        return

    # Encode phase.
    close_old_connections()  # model load / encode idles the connection
    try:
        provider = ei.get_provider(config)
    except EmbeddingUnavailableError as e:
        data['fatal'] = str(e)
        task.result_data = data
        task.mark_failed(f"Embedding provider unavailable: {e}")
        return

    count, failed, failed_keys = ei.embed_one_chunk(
        provider, config, content_type, target_version, chunk)

    if failed:
        # Record the failed keys so the next pass skips them (no infinite retry).
        failed_list = data.setdefault('failed', {}).setdefault(table_name, [])
        for key in failed_keys:
            if list(key) not in failed_list:
                failed_list.append(list(key))
        task.result_data = data
        task.save(update_fields=['result_data'])

    if remaining <= len(chunk):
        # This chunk was the last -> record the table and move on.
        _record_table_result(
            task, {
                'table': table_name,
                'count': LookupEmbedding.objects.filter(
                    content_type=content_type, embedding_config=config,
                    index_version=target_version, is_current=True).count(),
                'failed': len(data.get('failed', {}).get(table_name, [])),
            }, table_index, table_total)
        _advance_to_next_table_or_finalize(
            task_id, config_id, target_version, refresh,
            table_index, table_total)
    else:
        # More rows remain -> enqueue the next chunk of the same table.
        embed_lookup_table_chunk.apply_async(args=[
            task_id, config_id, content_type_id, target_version, refresh,
            table_index, table_total])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test extractor.tests.ChunkedEmbeddingTaskTests -v 2`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add extractor/tasks.py extractor/tests.py
git commit -m "feat(embeddings): self-perpetuating chunk task replaces whole-table task"
```

### Task 4: Point the dispatcher at the first chunk task

`compute_lookup_embeddings_task` currently builds a Celery `chain` of per-table
links + finalize. Replace that with a single dispatch of the first table's first
chunk — the self-perpetuating task does the rest. Also drop the now-unused
`chain` import.

**Files:**
- Modify: `extractor/tasks.py` (`compute_lookup_embeddings_task` body; the
  `from celery import ...` import line).
- Test: `extractor/tests.py` (new `EmbeddingDispatcherTests`).

**Interfaces:**
- Consumes: `embed_lookup_table_chunk` (Task 3), `BackgroundTask`,
  `EmbeddingConfiguration`, `ContentType`.
- Produces: `compute_lookup_embeddings_task(self, task_id, config_id,
  refresh=False)` — same signature, still the entry point the view calls
  (extractor/views_semantic_search.py:309). No changes to the view are needed.

- [ ] **Step 1: Write the failing test**

Add to `extractor/tests.py`:

```python
class EmbeddingDispatcherTests(TestCase):
    """compute_lookup_embeddings_task starts the build by dispatching the first
    table's first chunk (not a chain)."""

    def setUp(self):
        from lookup.models import LookupLaterality
        from extractor.models import (EmbeddingConfiguration,
                                      BackgroundTask)

        self.ct = ContentType.objects.get_for_model(LookupLaterality)
        self.config = EmbeddingConfiguration.objects.create(
            model_name='test-embed', model_provider='sentence-transformers',
            embedding_dimension=384, is_active=True)
        self.task = BackgroundTask.objects.create(
            task_id='emb-task-1', task_name='Compute Lookup Embeddings',
            status='pending')
        patcher = patch('extractor.tasks.close_old_connections',
                        lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dispatcher_starts_first_chunk(self):
        from django.contrib.contenttypes.models import ContentType
        from extractor.tasks import compute_lookup_embeddings_task
        from extractor.tasks import embed_lookup_table_chunk

        first_ct = ContentType.objects.filter(app_label='lookup') \
                                      .order_by('id').first()
        total = ContentType.objects.filter(app_label='lookup').count()
        with patch.object(embed_lookup_table_chunk, 'apply_async') as first:
            compute_lookup_embeddings_task.run(
                self.task.task_id, self.config.id, refresh=False)
        self.assertTrue(first.called)
        args = first.call_args[1]['args']
        # task_id FIRST (inflight check), config, first table, current version
        # (gap-fill), no refresh, 1-based index 1, total tables
        self.assertEqual(args[0], self.task.task_id)
        self.assertEqual(args[1], self.config.id)
        self.assertEqual(args[2], first_ct.id)
        self.assertEqual(args[3], self.config.version)
        self.assertEqual(args[4], False)
        self.assertEqual(args[5], 1)
        self.assertEqual(args[6], total)
        # dispatcher initialized result_data and marked the task running
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'running')
        self.assertEqual(self.task.result_data['results'], [])

    def test_dispatcher_marks_failed_when_no_tables(self):
        from django.contrib.contenttypes.models import ContentType
        from extractor.tasks import compute_lookup_embeddings_task
        from extractor.tasks import embed_lookup_table_chunk

        with patch.object(ContentType, 'objects') as objects_mock:
            objects_mock.filter.return_value.order_by.return_value.__iter__ \
                = lambda *a, **k: iter([])  # pretend: no lookup tables
            with patch.object(embed_lookup_table_chunk, 'apply_async') as first:
                compute_lookup_embeddings_task.run(
                    self.task.task_id, self.config.id, refresh=False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'failed')
        self.assertFalse(first.called)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python manage.py test extractor.tests.EmbeddingDispatcherTests -v 2`
Expected: `test_dispatcher_starts_first_chunk` FAILS — the current dispatcher
calls `chain(*links).apply_async()` (mocked as not-called) instead of
`embed_lookup_table_chunk.apply_async`.

- [ ] **Step 3: Rewrite the dispatcher body**

In `extractor/tasks.py`, replace the entire `compute_lookup_embeddings_task`
function body (from `task.mark_running()` down through
`task.mark_failed(f"Dispatch failed: {e}")`) with:

```python
    task.mark_running()

    try:
        config = EmbeddingConfiguration.objects.get(id=config_id)
    except EmbeddingConfiguration.DoesNotExist:
        task.mark_failed('Configuration not found')
        return

    content_types = list(ContentType.objects.filter(app_label='lookup')
                             .order_by('id'))
    if not content_types:
        task.mark_failed('No lookup tables found')
        return

    # Same build-then-swap generation for every chunk, fixed up front so a
    # re-run after a crash resumes the same version instead of bumping again.
    target_version = config.version + 1 if refresh else config.version
    total = len(content_types)

    task.result_data = {'results': [], 'target_version': target_version}
    task.save(update_fields=['result_data'])
    task.update_progress('Dispatching chunked embedding tasks',
                         processed_items=0, total_items=total)

    # Kick off the first table's first chunk; each chunk enqueues the next.
    first = content_types[0]
    log.info(f"Starting chunked embedding build for config {config_id} "
             f"({config.model_name}): {total} tables, target v{target_version}")
    try:
        embed_lookup_table_chunk.apply_async(args=[
            task_id, config_id, first.id, target_version, refresh,
            1, total])
    except Exception as e:
        log.error(f"Failed to dispatch first embedding chunk: {e}", exc_info=True)
        task.mark_failed(f"Dispatch failed: {e}")
```

Keep the function signature, docstring (update it to say "starts the build by
dispatching the first chunk"), and the leading `BackgroundTask` / `config`
guard that already exist. Then update the import line from
`from celery import chain, shared_task` to `from celery import shared_task`
(`chain` is no longer used anywhere in the file).

- [ ] **Step 4: Run the dispatcher tests**

Run: `python manage.py test extractor.tests.EmbeddingDispatcherTests -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add extractor/tasks.py extractor/tests.py
git commit -m "refactor(embeddings): dispatcher starts chunked build instead of a chain"
```

---

### Task 5: Full-suite regression gate + docs

Confirm the whole extractor suite (including the untouched management-command
path and the `EmbeddingIndexTests` refresh/resume/stale coverage) still passes,
and that nothing else references the removed task name.

**Files:**
- Verify only (no code changes expected).

- [ ] **Step 1: Confirm no stale references to the old task name**

Run: `grep -rn "compute_lookup_table_embeddings_task" extractor/ --include=*.py`
Expected: no matches (the only remaining reference is
`compute_lookup_table_embeddings`, the *service* function — a different name).

- [ ] **Step 2: Confirm the view is unaffected**

Run: `grep -n "compute_lookup_embeddings_task" extractor/views_semantic_search.py`
Expected: still `from extractor.tasks import compute_lookup_embeddings_task` and
`compute_lookup_embeddings_task.delay(task_id, active_config.id, refresh)` —
unchanged. `task_id` remains the first arg, so `_inflight_embedding_tasks_alive`
keeps working for the chunk tasks.

- [ ] **Step 3: Run the full extractor suite**

Run: `python manage.py test extractor -v 1`
Expected: PASS — all tests, including `EmbeddingIndexTests`,
`ChunkedEmbeddingServiceTests`, `ChunkedEmbeddingTaskTests`,
`EmbeddingDispatcherTests`.

- [ ] **Step 4: Commit (if any doc/tweak needed) and finish**

```bash
git add -A
git commit -m "test(embeddings): full-suite green for chunked lookup embeddings" || true
git log --oneline -6
```

"""
Shared lookup-embedding index builder.

Two execution paths use the same building blocks:

- Celery (extractor.tasks.embed_lookup_table_chunk): a self-perpetuating task
  that embeds one bounded chunk of one lookup table, then enqueues the next
  chunk; the last table triggers finalize_lookup_embeddings_task.
- Management command: compute_lookup_embeddings() runs the same steps serially.

Both share the build-then-swap refresh semantics:

- refresh=True builds under config.version+1; the new index only becomes live
  when the whole build succeeds, so a failed refresh never destroys a working
  index.
- refresh=False fills gaps in the current version.
- Rows whose source text vanished or changed are flagged is_current=False
  before building.
"""

from typing import Callable, Optional, Dict, Any, List
from logging import getLogger
from time import perf_counter

from django.contrib.contenttypes.models import ContentType
from django.db import close_old_connections, transaction
from django.db import models as django_models

from extractor.models import EmbeddingConfiguration, LookupEmbedding
from extractor.services.embeddings import get_provider
from extractor.services.semantic_search import (
    SemanticSearchService,
    build_lookup_label,
    composite_label_spec,
    COMBINED_LABEL_FIELD,
)

log = getLogger(__name__)

# Identifier-style fields carry no semantic signal (e.g. 'C78.0', 'P12345') —
# embedding them wastes compute and can surface junk matches, so they're
# skipped. A denylist (not an allowlist) so future fields embed by default.
NON_SEMANTIC_FIELDS = frozenset({
    'code',
    'meddra_code',
    'uniport_id',
    'unit_abbreviation',
    'staging_system_version',
})

# Bounded unit of work per Celery chunk task. Chosen so a single chunk stays
# well under the broker's 30-minute delivery-ack timeout.
CHUNK_SIZE = 100


def _text_fields(model_class) -> List[str]:
    names = []
    for field in model_class._meta.get_fields():
        if field.auto_created or field.is_relation:
            continue
        if field.name in ['created_at', 'updated_at', 'id']:
            continue
        if field.name in NON_SEMANTIC_FIELDS:
            continue
        if isinstance(field, (django_models.CharField, django_models.TextField)):
            names.append(field.name)
    return names


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


def finalize_lookup_index(config: EmbeddingConfiguration, target_version: int) -> None:
    """
    Swap generations: activate target_version and delete every other
    generation for this config. Atomic — the old index stays live until the
    pointer moves. Call only after a fully successful refresh build.
    """
    close_old_connections()
    with transaction.atomic():
        config.version = target_version
        config.save(update_fields=['version', 'updated_at'])
        LookupEmbedding.objects.filter(
            embedding_config=config
        ).exclude(index_version=target_version).delete()


def compute_lookup_embeddings(
    config: EmbeddingConfiguration,
    refresh: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Serial driver for the management-command path: embeds every lookup table
    via compute_lookup_table_embeddings, then swaps the generation on refresh.
    The Celery path runs the same primitives as a self-perpetuating per-chunk
    task (extractor.tasks.embed_lookup_table_chunk).

    Returns stats dict. Raises on provider failure or when nothing could be
    embedded at all (so callers never report a broken index as success).
    """
    notify = progress_callback or (lambda msg: None)

    provider = get_provider(config)  # raises EmbeddingUnavailableError — fail fast
    # Model download/load can idle the DB connection for minutes; remote
    # servers kill idle SSL sessions, so drop it before the next query.
    close_old_connections()
    notify(f"Provider ready: {config.model_provider} / {config.model_name}")

    content_types = list(ContentType.objects.filter(app_label='lookup').order_by('id'))
    if not content_types:
        raise ValueError("No lookup tables found")

    # Build-then-swap target generation
    target_version = config.version + 1 if refresh else config.version

    total_processed = 0
    total_failed = 0
    results = []

    for idx, content_type in enumerate(content_types, 1):
        notify(f"[{idx}/{len(content_types)}] {content_type.model}")
        try:
            stats = compute_lookup_table_embeddings(
                config, content_type, target_version, refresh=refresh)
        except Exception as e:
            log.error(f"Embedding failed for {content_type.model}: {e}")
            results.append({'table': content_type.model, 'count': 0, 'failed': 0, 'error': str(e)})
            continue
        total_processed += stats['count']
        total_failed += stats['failed']
        results.append(stats)

    if refresh:
        # A resumed run can legitimately add zero rows — completeness is
        # clean per-table results plus committed target-version rows, not
        # this run's write count.
        clean = all(not r.get('failed') and not r.get('error') for r in results)
        built = LookupEmbedding.objects.filter(
            embedding_config=config, index_version=target_version,
            is_current=True).exists()
        if not clean or not built:
            raise RuntimeError(
                "Refresh incomplete; keeping the existing index active. "
                "Re-run to resume the partial build."
            )
        finalize_lookup_index(config, target_version)
        notify(f"Index v{target_version} activated")

    errored = sum(1 for r in results if r.get('error'))
    if total_processed == 0 and (total_failed > 0 or errored):
        raise RuntimeError(
            f"All embedding computations failed "
            f"({errored} table errors, {total_failed} failed items)"
        )

    return {
        'total_processed': total_processed,
        'total_failed': total_failed,
        'tables_processed': len(results),
        'index_version': target_version,
        'results': results,
    }

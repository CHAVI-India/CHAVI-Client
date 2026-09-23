"""
Shared lookup-embedding index builder.

Two execution paths use the same building blocks:

- Celery (extractor.tasks): a chain of compute_lookup_table_embeddings_task
  links, one per lookup table, followed by finalize_lookup_embeddings_task.
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


def compute_lookup_table_embeddings(
    config: EmbeddingConfiguration,
    content_type: ContentType,
    target_version: int,
    refresh: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Embed one lookup table's semantic text fields under the given index
    generation. When a DatabaseField declares composite lookup_label_fields
    for this table, a '__label__' vector of the joined display label is also
    embedded per record — it's the string the LLM is asked to return.

    Builds resume per row: target-version rows whose stored text still
    matches the source are skipped in both refresh and gap-fill modes, so
    an interrupted build continues where it left off.

    Returns {'table', 'count', 'failed'}. Provider setup failures propagate as
    EmbeddingUnavailableError so callers can treat them as fatal.
    """
    notify = progress_callback or (lambda msg: None)
    provider = get_provider(config)  # raises EmbeddingUnavailableError

    lookup_model = content_type.model_class()
    table_name = content_type.model
    if not lookup_model:
        return {'table': table_name, 'count': 0, 'failed': 0}

    close_old_connections()
    notify(f"Indexing {table_name}")

    # Flag rows whose record was deleted or whose text changed — scoped to
    # the generation being built so a failed refresh can't mark the live
    # index stale.
    stale = SemanticSearchService.mark_stale_embeddings(
        content_type, lookup_model,
        embedding_config=config, index_version=target_version)
    if stale:
        log.info(f"  {table_name}: {stale} stale embeddings flagged")

    pk_field = lookup_model._meta.pk.name
    text_fields = _text_fields(lookup_model)
    label_spec = composite_label_spec(content_type)
    if not text_fields and not label_spec:
        return {'table': table_name, 'count': 0, 'failed': 0}

    # Stale rows at the generation being built are invisible to queries and
    # would only block re-embedding through the unique constraint.
    LookupEmbedding.objects.filter(
        content_type=content_type, embedding_config=config,
        index_version=target_version, is_current=False,
    ).delete()

    # One query for the whole table: what the target generation already has.
    # Covers gap-fill and refresh-resume alike — a re-run skips only rows
    # whose stored text still matches the source.
    existing = {
        (object_id, field_name): (row_id, text_value)
        for row_id, object_id, field_name, text_value in LookupEmbedding.objects.filter(
            content_type=content_type, embedding_config=config,
            index_version=target_version, is_current=True,
        ).values_list('id', 'object_id', 'field_name', 'text_value')
    }

    # Collect (pk, field, text) triples needing embeddings
    pending = []
    replaced_ids = []
    for record in lookup_model.objects.all().iterator():
        pk_value = getattr(record, pk_field)
        candidates = [(f, str(getattr(record, f, '') or '')) for f in text_fields]
        if label_spec:
            candidates.append((
                COMBINED_LABEL_FIELD,
                build_lookup_label(record, label_fields=label_spec),
            ))
        for field_name, text_value in candidates:
            if not text_value.strip():
                continue
            entry = existing.get((str(pk_value), field_name))
            if entry is not None:
                if entry[1] == text_value:
                    continue
                # Text changed after the stale scan — the old row must go
                # before the fresh one can take its unique slot.
                replaced_ids.append(entry[0])
            pending.append((str(pk_value), field_name, text_value))

    if replaced_ids:
        LookupEmbedding.objects.filter(id__in=replaced_ids).delete()

    # Batch-encode; flush each chunk so a crash mid-table loses at most one
    # chunk of work and memory stays bounded on very large tables.
    new_count = 0
    table_failed = 0
    chunk_total = (len(pending) + 99) // 100
    for i in range(0, len(pending), 100):
        chunk = pending[i:i + 100]
        chunk_number = i // 100 + 1
        first_key = f"{chunk[0][0]}.{chunk[0][1]}"
        last_key = f"{chunk[-1][0]}.{chunk[-1][1]}"
        log.info(
            "Embedding %s v%s chunk %s/%s: %s texts (%s to %s)",
            table_name, target_version, chunk_number, chunk_total,
            len(chunk), first_key, last_key)
        encode_started = perf_counter()
        try:
            vectors = provider.embed_texts([t for _, _, t in chunk])
            if len(vectors) != len(chunk):
                raise ValueError(
                    f"provider returned {len(vectors)} embeddings "
                    f"for {len(chunk)} texts")
        except Exception as e:
            log.error(
                "Embedding %s v%s chunk %s/%s failed after %.2fs: %s",
                table_name, target_version, chunk_number, chunk_total,
                perf_counter() - encode_started, e)
            table_failed += len(chunk)
            continue
        encode_seconds = perf_counter() - encode_started
        rows = [LookupEmbedding(
            content_type=content_type,
            object_id=pk_value,
            field_name=field_name,
            text_value=text_value,
            embedding=vector,
            embedding_config=config,
            index_version=target_version,
        ) for (pk_value, field_name, text_value), vector in zip(chunk, vectors)]
        # Encoding idles the DB connection for minutes — drop it before writing.
        close_old_connections()
        write_started = perf_counter()
        LookupEmbedding.objects.bulk_create(rows, ignore_conflicts=True)
        write_seconds = perf_counter() - write_started
        new_count += len(rows)
        log.info(
            "Saved %s v%s chunk %s/%s: %s rows "
            "(encode %.2fs, database %.2fs)",
            table_name, target_version, chunk_number, chunk_total,
            len(rows), encode_seconds, write_seconds)

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
    The Celery path runs the same steps as a per-table chain (extractor.tasks).

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

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

from django.contrib.contenttypes.models import ContentType
from django.db import close_old_connections
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

    # Flag rows whose record was deleted or whose text changed
    stale = SemanticSearchService.mark_stale_embeddings(content_type, lookup_model)
    if stale:
        log.info(f"  {table_name}: {stale} stale embeddings flagged")

    pk_field = lookup_model._meta.pk.name
    text_fields = _text_fields(lookup_model)
    label_spec = composite_label_spec(content_type)
    if not text_fields and not label_spec:
        return {'table': table_name, 'count': 0, 'failed': 0}

    # Collect (pk, field, text) triples needing embeddings
    pending = []
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
            if not refresh and LookupEmbedding.objects.filter(
                content_type=content_type,
                object_id=str(pk_value),
                field_name=field_name,
                embedding_config=config,
                index_version=target_version,
            ).exists():
                continue
            pending.append((str(pk_value), field_name, text_value))

    # Batch-encode
    new_rows = []
    table_failed = 0
    for i in range(0, len(pending), 100):
        chunk = pending[i:i + 100]
        try:
            vectors = provider.embed_texts([t for _, _, t in chunk])
        except Exception as e:
            log.error(f"Embedding batch failed for {table_name}: {e}")
            table_failed += len(chunk)
            continue
        for (pk_value, field_name, text_value), vector in zip(chunk, vectors):
            new_rows.append(LookupEmbedding(
                content_type=content_type,
                object_id=pk_value,
                field_name=field_name,
                text_value=text_value,
                embedding=vector,
                embedding_config=config,
                index_version=target_version,
            ))

    if new_rows:
        # The encode loop does no DB work — the connection may have idled
        # through it, so drop it before writing.
        close_old_connections()
        LookupEmbedding.objects.bulk_create(new_rows, ignore_conflicts=True)

    return {'table': table_name, 'count': len(new_rows), 'failed': table_failed}


def finalize_lookup_index(config: EmbeddingConfiguration, target_version: int) -> None:
    """
    Swap generations: mark every row outside the new build stale and make
    target_version live. Call only after a successful refresh build.
    """
    close_old_connections()
    LookupEmbedding.objects.filter(
        embedding_config=config
    ).exclude(index_version=target_version).update(is_current=False)
    config.version = target_version
    config.save(update_fields=['version', 'updated_at'])


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
        if total_processed == 0:
            raise RuntimeError(
                "Refresh produced zero embeddings; keeping the existing index active."
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

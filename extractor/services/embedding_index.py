"""
Shared lookup-embedding index builder.

Used by the Celery task (extractor.tasks.compute_lookup_embeddings_task) and the
management command, so both paths use the same provider adapter and the same
build-then-swap refresh semantics:

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
from django.db import models as django_models

from extractor.models import EmbeddingConfiguration, LookupEmbedding
from extractor.services.embeddings import get_provider
from extractor.services.semantic_search import SemanticSearchService

log = getLogger(__name__)


def _text_fields(model_class) -> List[str]:
    names = []
    for field in model_class._meta.get_fields():
        if field.auto_created or field.is_relation:
            continue
        if field.name in ['created_at', 'updated_at', 'id']:
            continue
        if isinstance(field, (django_models.CharField, django_models.TextField)):
            names.append(field.name)
    return names


def compute_lookup_embeddings(
    config: EmbeddingConfiguration,
    refresh: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Compute embeddings for all lookup tables under the given configuration.

    Returns stats dict. Raises on provider failure or when nothing could be
    embedded at all (so callers never report a broken index as success).
    """
    notify = progress_callback or (lambda msg: None)

    provider = get_provider(config)  # raises EmbeddingUnavailableError
    notify(f"Provider ready: {config.model_provider} / {config.model_name}")

    content_types = list(ContentType.objects.filter(app_label='lookup'))
    if not content_types:
        raise ValueError("No lookup tables found")

    # Build-then-swap target generation
    target_version = config.version + 1 if refresh else config.version

    total_processed = 0
    total_failed = 0
    results = []

    for idx, content_type in enumerate(content_types, 1):
        lookup_model = content_type.model_class()
        if not lookup_model:
            continue
        table_name = content_type.model
        notify(f"[{idx}/{len(content_types)}] {table_name}")

        # Flag rows whose record was deleted or whose text changed
        stale = SemanticSearchService.mark_stale_embeddings(content_type, lookup_model)
        if stale:
            log.info(f"  {table_name}: {stale} stale embeddings flagged")

        pk_field = lookup_model._meta.pk.name
        text_fields = _text_fields(lookup_model)
        if not text_fields:
            continue

        # Collect (pk, field, text) pairs needing embeddings
        pending = []
        for record in lookup_model.objects.all().iterator():
            pk_value = getattr(record, pk_field)
            for field_name in text_fields:
                text_value = getattr(record, field_name, None)
                if not text_value or str(text_value).strip() == '':
                    continue
                if not refresh:
                    exists = LookupEmbedding.objects.filter(
                        content_type=content_type,
                        object_id=str(pk_value),
                        field_name=field_name,
                        embedding_config=config,
                        index_version=target_version,
                    ).exists()
                    if exists:
                        continue
                pending.append((str(pk_value), field_name, str(text_value)))

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
            LookupEmbedding.objects.bulk_create(new_rows, ignore_conflicts=True)

        total_processed += len(new_rows)
        total_failed += table_failed
        results.append({'table': table_name, 'count': len(new_rows), 'failed': table_failed})

    if refresh:
        if total_processed == 0:
            raise RuntimeError(
                "Refresh produced zero embeddings; keeping the existing index active."
            )
        # Swap: old generation goes stale, new generation becomes live
        LookupEmbedding.objects.filter(
            embedding_config=config
        ).exclude(index_version=target_version).update(is_current=False)
        config.version = target_version
        config.save(update_fields=['version', 'updated_at'])
        notify(f"Index v{target_version} activated")

    if total_processed == 0 and total_failed > 0:
        raise RuntimeError(f"All {total_failed} embedding computations failed")

    return {
        'total_processed': total_processed,
        'total_failed': total_failed,
        'tables_processed': len(content_types),
        'index_version': target_version,
        'results': results,
    }

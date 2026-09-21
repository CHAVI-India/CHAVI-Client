"""
Semantic search service for finding similar lookup entries using pre-computed embeddings.
"""

from typing import List, Dict, Optional
from django.contrib.contenttypes.models import ContentType
from extractor.models import EmbeddingConfiguration, LookupEmbedding, DatabaseField
from extractor.services.embeddings import get_provider, EmbeddingUnavailableError
from logging import getLogger

log = getLogger(__name__)


def build_lookup_label(obj, db_field=None, label_fields=None) -> str:
    """
    Build the display label for a lookup record. When the field config declares
    composite label fields (e.g. CTCAE grade + description), join them so
    'Grade 3' and 'Severe' are never confused. Falls back to __str__.
    """
    fields = label_fields
    if fields is None and db_field is not None:
        fields = db_field.lookup_label_fields or (
            [db_field.lookup_table_value_field_name] if db_field.lookup_table_value_field_name else None
        )
    if fields:
        parts = [str(getattr(obj, f, '') or '').strip() for f in fields]
        parts = [p for p in parts if p]
        if parts:
            return ' — '.join(parts)
    return str(obj)


# Synthetic field_name for the per-record composite-label embedding.
COMBINED_LABEL_FIELD = '__label__'


def composite_label_spec(content_type) -> Optional[List[str]]:
    """
    First multi-field lookup_label_fields spec declared by a DatabaseField
    pointing at this lookup table — drives the '__label__' composite vector
    embedded alongside per-field vectors. Single-field specs are skipped:
    they duplicate a field that is already embedded on its own.
    """
    for spec in DatabaseField.objects.filter(
        lookup_content_type=content_type
    ).values_list('lookup_label_fields', flat=True):
        if spec and len(spec) > 1:
            return list(spec)
    return None


class SemanticSearchService:
    """
    Service for performing semantic search on lookup tables using pgvector.
    """

    @classmethod
    def get_active_config(cls) -> Optional[EmbeddingConfiguration]:
        return EmbeddingConfiguration.objects.filter(is_active=True).first()

    @classmethod
    def get_embedding_model(cls):
        """
        Compatibility shim: returns (provider, config) for the active config.
        """
        config = cls.get_active_config()
        if not config:
            log.error("No active embedding configuration found")
            return None, None
        try:
            return get_provider(config), config
        except EmbeddingUnavailableError as e:
            log.error(f"Embedding provider unavailable: {e}")
            return None, None
        except Exception as e:
            log.error(f"Error loading embedding provider: {e}")
            return None, None

    @classmethod
    def compute_query_embedding(cls, query_text: str) -> Optional[List[float]]:
        """
        Compute embedding for a query text using the active provider.
        """
        provider, config = cls.get_embedding_model()
        if not provider or not config:
            return None
        try:
            return provider.embed_texts([query_text])[0]
        except Exception as e:
            log.error(f"Error computing query embedding: {e}")
            return None

    @classmethod
    def find_similar_lookup_entries(
        cls,
        lookup_model_class,
        pk_field_name: str,
        value_field_name: str,
        query_text: str,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None,
        db_field=None,
    ) -> List[Dict[str, any]]:
        """
        Find the most similar lookup entries to the query text using semantic
        search over the *current* index version only.

        Returns list of dicts with 'code', 'label', 'similarity' keys — label is
        the record's real display label (composite-aware), not the embedded text.
        """
        provider, config = cls.get_embedding_model()
        if not config:
            log.warning("No embedding config available")
            return []

        if top_k is None:
            top_k = config.top_k_results
        if threshold is None:
            threshold = config.similarity_threshold

        query_embedding = cls.compute_query_embedding(query_text)
        if not query_embedding:
            return []

        content_type = ContentType.objects.get_for_model(lookup_model_class)

        try:
            from pgvector.django import CosineDistance

            similar_embeddings = LookupEmbedding.objects.filter(
                content_type=content_type,
                embedding_config=config,
                index_version=config.version,
                is_current=True,
            ).annotate(
                distance=CosineDistance('embedding', query_embedding)
            ).order_by('distance')[:top_k * 3]

            best_matches = {}
            for emb in similar_embeddings:
                similarity = 1 - emb.distance
                if similarity < threshold:
                    continue
                if emb.object_id not in best_matches or similarity > best_matches[emb.object_id]['similarity']:
                    best_matches[emb.object_id] = {
                        'code': emb.object_id,
                        'field_name': emb.field_name,
                        'similarity': float(similarity),
                    }

            # Resolve real labels from the lookup objects (composite-aware)
            results = []
            if best_matches:
                objects = {
                    str(getattr(o, pk_field_name)): o
                    for o in lookup_model_class.objects.filter(
                        **{f"{pk_field_name}__in": list(best_matches.keys())}
                    )
                }
                for object_id, match in best_matches.items():
                    obj = objects.get(str(object_id))
                    if obj is None:
                        continue  # stale row — marked by cleanup
                    results.append({
                        'code': object_id,
                        'label': build_lookup_label(obj, db_field=db_field),
                        'similarity': match['similarity'],
                    })

            results.sort(key=lambda x: x['similarity'], reverse=True)
            return results[:top_k]

        except Exception as e:
            log.error(f"Error performing semantic search: {e}")
            return []

    @classmethod
    def get_filtered_lookup_options(
        cls,
        lookup_model_class,
        pk_field_name: str,
        value_field_name: str,
        document_context: str,
        db_field=None,
    ) -> List[Dict[str, str]]:
        """
        Get filtered lookup options based on document context.

        Uses the head AND tail of the document — clinical conclusions often sit
        at the end, so only the first 500 characters was biased. Uses the looser
        candidate_threshold: these are options shown to the LLM, not final matches.
        """
        config = cls.get_active_config()
        if not config:
            return []

        if len(document_context) > 500:
            context_snippet = document_context[:350] + "\n...\n" + document_context[-150:]
        else:
            context_snippet = document_context

        similar_entries = cls.find_similar_lookup_entries(
            lookup_model_class,
            pk_field_name,
            value_field_name,
            context_snippet,
            threshold=config.candidate_threshold,
            db_field=db_field,
        )

        return [
            {'code': entry['code'], 'label': entry['label']}
            for entry in similar_entries
        ]

    @classmethod
    def mark_stale_embeddings(cls, content_type, model_class) -> int:
        """
        Flag embeddings whose lookup record no longer exists or whose text
        changed since they were computed. Returns the number marked.
        """
        stale = 0
        qs = LookupEmbedding.objects.filter(content_type=content_type, is_current=True)
        live = {str(getattr(o, model_class._meta.pk.name)): o for o in model_class.objects.all()}
        label_spec = composite_label_spec(content_type)

        for emb in qs.iterator():
            obj = live.get(emb.object_id)
            if emb.field_name == COMBINED_LABEL_FIELD:
                # No such attribute on the record — recompute the joined label;
                # missing spec/record collapses to '' so the row goes stale.
                current_text = build_lookup_label(obj, label_fields=label_spec) if obj and label_spec else ''
            else:
                current_text = str(getattr(obj, emb.field_name, '') or '') if obj else ''
            if obj is None or current_text != emb.text_value:
                emb.is_current = False
                emb.save(update_fields=['is_current'])
                stale += 1
        return stale

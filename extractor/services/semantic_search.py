"""
Semantic search service for finding similar lookup entries using pre-computed embeddings.
"""

from typing import List, Dict, Optional, Tuple
from django.contrib.contenttypes.models import ContentType
from django.db.models import F
from extractor.models import EmbeddingConfiguration, LookupEmbedding
from logging import getLogger
import numpy as np

log = getLogger(__name__)


class SemanticSearchService:
    """
    Service for performing semantic search on lookup tables using pgvector.
    """
    
    _embedding_model = None
    _current_config = None
    
    @classmethod
    def get_embedding_model(cls):
        """
        Get or load the active embedding model (cached).
        """
        config = EmbeddingConfiguration.objects.filter(is_active=True).first()
        
        if not config:
            log.error("No active embedding configuration found")
            return None, None
        
        # Return cached model if config hasn't changed
        if cls._embedding_model and cls._current_config == config:
            return cls._embedding_model, config
        
        # Load new model
        try:
            if config.model_provider == 'sentence-transformers':
                from sentence_transformers import SentenceTransformer
                # Force CPU usage to avoid CUDA compatibility issues
                cls._embedding_model = SentenceTransformer(config.model_name, device='cpu')
                cls._current_config = config
                log.info(f"Loaded embedding model: {config.model_name} (using CPU)")
                return cls._embedding_model, config
            
            elif config.model_provider == 'openai':
                import openai
                if config.api_key:
                    openai.api_key = config.api_key
                cls._embedding_model = 'openai'
                cls._current_config = config
                return cls._embedding_model, config
            
            else:
                log.error(f"Unsupported embedding provider: {config.model_provider}")
                return None, None
                
        except Exception as e:
            log.error(f"Error loading embedding model: {e}")
            return None, None
    
    @classmethod
    def compute_query_embedding(cls, query_text: str) -> Optional[List[float]]:
        """
        Compute embedding for a query text.
        
        Args:
            query_text: The text to embed
            
        Returns:
            List of floats representing the embedding, or None on error
        """
        model, config = cls.get_embedding_model()
        
        if not model or not config:
            return None
        
        try:
            if config.model_provider == 'sentence-transformers':
                embedding = model.encode(query_text)
                return embedding.tolist()
            
            elif config.model_provider == 'openai':
                import openai
                response = openai.Embedding.create(
                    input=query_text,
                    model=config.model_name
                )
                return response['data'][0]['embedding']
            
            return None
            
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
        top_k: Optional[int] = None
    ) -> List[Dict[str, any]]:
        """
        Find the most similar lookup entries to the query text using semantic search.
        Searches across ALL embedded fields for the lookup table.
        
        Args:
            lookup_model_class: The Django model class for the lookup table
            pk_field_name: Name of the primary key field
            value_field_name: Name of the value field (used for display, not filtering)
            query_text: The text to search for
            top_k: Number of results to return (uses config default if None)
            
        Returns:
            List of dicts with 'code', 'label', and 'similarity' keys
        """
        # Get embedding config
        _, config = cls.get_embedding_model()
        if not config:
            log.warning("No embedding config available, falling back to exact match")
            return []
        
        if top_k is None:
            top_k = config.top_k_results
        
        # Compute query embedding
        query_embedding = cls.compute_query_embedding(query_text)
        if not query_embedding:
            log.warning("Could not compute query embedding")
            return []
        
        # Get content type for the lookup model
        content_type = ContentType.objects.get_for_model(lookup_model_class)
        
        # Perform similarity search using pgvector
        try:
            from pgvector.django import CosineDistance
            
            # Search across ALL fields for this lookup table (not just one field)
            # This allows matching against code, label, description, etc.
            similar_embeddings = LookupEmbedding.objects.filter(
                content_type=content_type,
                embedding_config=config
            ).annotate(
                distance=CosineDistance('embedding', query_embedding)
            ).order_by('distance')[:top_k * 3]  # Get more results since we're searching multiple fields
            
            # Group by object_id and keep the best match per record
            best_matches = {}
            for emb in similar_embeddings:
                object_id = emb.object_id
                similarity = 1 - emb.distance
                
                # Filter by threshold
                if similarity >= config.similarity_threshold:
                    # Keep the best match for each object_id
                    if object_id not in best_matches or similarity > best_matches[object_id]['similarity']:
                        best_matches[object_id] = {
                            'code': object_id,
                            'label': emb.text_value,
                            'field_name': emb.field_name,
                            'similarity': float(similarity)
                        }
            
            # Sort by similarity and return top_k
            results = sorted(best_matches.values(), key=lambda x: x['similarity'], reverse=True)[:top_k]
            
            log.info(f"Found {len(results)} similar entries for query: '{query_text[:50]}...'")
            return results
            
        except Exception as e:
            log.error(f"Error performing semantic search: {e}")
            return []
    
    @classmethod
    def get_filtered_lookup_options(
        cls,
        lookup_model_class,
        pk_field_name: str,
        value_field_name: str,
        document_context: str
    ) -> List[Dict[str, str]]:
        """
        Get filtered lookup options based on document context using semantic search.
        
        This is used during extraction to show only relevant options to the LLM.
        
        Args:
            lookup_model_class: The Django model class for the lookup table
            pk_field_name: Name of the primary key field
            value_field_name: Name of the value field
            document_context: The document text to use as context
            
        Returns:
            List of dicts with 'code' and 'label' keys
        """
        # Extract key phrases from document (simple approach - first 500 chars)
        context_snippet = document_context[:500] if len(document_context) > 500 else document_context
        
        # Find similar entries
        similar_entries = cls.find_similar_lookup_entries(
            lookup_model_class,
            pk_field_name,
            value_field_name,
            context_snippet
        )
        
        # Convert to standard format
        return [
            {'code': entry['code'], 'label': entry['label']}
            for entry in similar_entries
        ]

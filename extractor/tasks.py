"""
Background tasks for semantic search embedding computation.
Uses simple threading with database-based progress tracking.
"""

from django.contrib.contenttypes.models import ContentType
from logging import getLogger

from extractor.models import EmbeddingConfiguration, LookupEmbedding, DatabaseField, BackgroundTask

log = getLogger(__name__)


def compute_lookup_embeddings_task(task_id, config_id, refresh=False):
    """
    Background task to compute embeddings for all lookup tables.
    
    Args:
        task_id: ID of the BackgroundTask tracking this job
        config_id: ID of the EmbeddingConfiguration to use
        refresh: If True, delete and recompute all embeddings
    """
    # Get task tracker
    try:
        task = BackgroundTask.objects.get(task_id=task_id)
    except BackgroundTask.DoesNotExist:
        log.error(f"BackgroundTask {task_id} not found")
        return
    
    task.mark_running()
    
    try:
        config = EmbeddingConfiguration.objects.get(id=config_id)
    except EmbeddingConfiguration.DoesNotExist:
        log.error(f"EmbeddingConfiguration {config_id} not found")
        task.mark_failed('Configuration not found')
        return
    
    log.info(f"Starting embedding computation with config: {config.model_name}")
    task.update_progress(f'Loading model: {config.model_name}...')
    
    try:
        # Load embedding model
        from sentence_transformers import SentenceTransformer
        from django.db import models as django_models
        
        model = SentenceTransformer(config.model_name, device='cpu')
        log.info(f"Model loaded: {config.model_name} (using CPU)")
        task.update_progress('Model loaded successfully')
    
        # Get all lookup content types
        content_types_list = ContentType.objects.filter(app_label='lookup')
        
        if not content_types_list.exists():
            log.warning("No lookup tables found")
            task.mark_failed('No lookup tables found')
            return
        
        total_processed = 0
        total_tables = content_types_list.count()
        results = []
        
        task.update_progress('Preparing to process lookup tables', 0, total_tables)
        
        # Process each lookup table
        for idx, content_type in enumerate(content_types_list, 1):
            lookup_model = content_type.model_class()
            if not lookup_model:
                continue
                
            table_name = content_type.model
            
            log.info(f"Processing table {idx}/{total_tables}: {table_name}")
            task.update_progress(f'Processing {table_name}', idx - 1, total_tables)
        
            # Delete existing embeddings if refresh
            if refresh:
                deleted_count = LookupEmbedding.objects.filter(
                    content_type=content_type,
                    embedding_config=config
                ).delete()[0]
                log.info(f"  Deleted {deleted_count} existing embeddings")
            
            # Get primary key field
            pk_field = lookup_model._meta.pk.name
            
            # Get all text fields (excluding timestamps and auto-created fields)
            text_fields = []
            for field in lookup_model._meta.get_fields():
                if field.auto_created or field.is_relation:
                    continue
                if field.name in ['created_at', 'updated_at', 'id']:
                    continue
                if isinstance(field, (django_models.CharField, django_models.TextField)):
                    text_fields.append(field.name)
            
            if not text_fields:
                log.warning(f"  No text fields found in {table_name}")
                continue
            
            log.info(f"  Text fields to embed: {', '.join(text_fields)}")
            
            # Get all records
            records = lookup_model.objects.all()
            total_records = records.count()
            
            table_processed = 0
            batch_embeddings = []
            
            for record in records:
                pk_value = getattr(record, pk_field)
                
                # Process each text field
                for field_name in text_fields:
                    text_value = getattr(record, field_name, None)
                    
                    if not text_value or str(text_value).strip() == '':
                        continue
                    
                    # Check if embedding already exists (if not refresh)
                    if not refresh:
                        exists = LookupEmbedding.objects.filter(
                            content_type=content_type,
                            object_id=str(pk_value),
                            field_name=field_name,
                            embedding_config=config
                        ).exists()
                        if exists:
                            continue
                    
                    # Compute embedding
                    try:
                        embedding = model.encode(str(text_value))
                        embedding_list = embedding.tolist()
                        
                        batch_embeddings.append(
                            LookupEmbedding(
                                content_type=content_type,
                                object_id=str(pk_value),
                                field_name=field_name,
                                text_value=str(text_value),
                                embedding=embedding_list,
                                embedding_config=config
                            )
                        )
                        
                    except Exception as e:
                        log.error(f"Error computing embedding for {pk_value}.{field_name}: {e}")
                        continue
            
            # Bulk create embeddings
            if batch_embeddings:
                LookupEmbedding.objects.bulk_create(
                    batch_embeddings,
                    ignore_conflicts=True
                )
                table_processed = len(batch_embeddings)
                log.info(f"    Created {table_processed} embeddings")
        
            total_processed += table_processed
            results.append({
                'table': table_name,
                'count': table_processed
            })
            
            log.info(f"  Completed {table_name}: {table_processed} embeddings")
        
        log.info(f"Embedding computation completed! Total: {total_processed} embeddings")
        
        # Mark task as complete
        task.mark_complete({
            'success': True,
            'total_processed': total_processed,
            'tables_processed': total_tables,
            'results': results
        })
        
    except Exception as e:
        log.error(f"Error in embedding computation: {e}", exc_info=True)
        task.mark_failed(str(e))

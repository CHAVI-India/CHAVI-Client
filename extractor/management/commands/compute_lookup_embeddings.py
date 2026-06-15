"""
Management command to compute and store embeddings for lookup table entries.

Usage:
    python manage.py compute_lookup_embeddings --refresh  # Recompute all
    python manage.py compute_lookup_embeddings --table lookupicdcode  # Specific table
"""

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from extractor.models import EmbeddingConfiguration, LookupEmbedding, DatabaseField
from logging import getLogger
import numpy as np

log = getLogger(__name__)


class Command(BaseCommand):
    help = 'Compute and store embeddings for lookup table entries'

    def add_arguments(self, parser):
        parser.add_argument(
            '--refresh',
            action='store_true',
            help='Delete existing embeddings and recompute all',
        )
        parser.add_argument(
            '--table',
            type=str,
            help='Specific lookup table to process (e.g., lookupicdcode)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Batch size for processing records',
        )

    def handle(self, *args, **options):
        refresh = options['refresh']
        specific_table = options['table']
        batch_size = options['batch_size']

        # Get active embedding configuration
        try:
            embedding_config = EmbeddingConfiguration.objects.filter(is_active=True).first()
            if not embedding_config:
                self.stdout.write(self.style.ERROR(
                    'No active embedding configuration found. '
                    'Please create one in the admin panel.'
                ))
                return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error loading embedding config: {e}'))
            return

        self.stdout.write(self.style.SUCCESS(
            f'Using embedding model: {embedding_config.model_name}'
        ))

        # Load embedding model
        embedding_model = self.load_embedding_model(embedding_config)
        if not embedding_model:
            return

        # Get all lookup content types
        if specific_table:
            content_types = ContentType.objects.filter(
                app_label='lookup',
                model=specific_table
            )
        else:
            content_types = ContentType.objects.filter(app_label='lookup')

        if not content_types.exists():
            self.stdout.write(self.style.WARNING('No lookup tables found to process'))
            return

        # Process each lookup table
        total_processed = 0
        for content_type in content_types:
            processed = self.process_lookup_table(
                content_type,
                embedding_model,
                embedding_config,
                refresh,
                batch_size
            )
            total_processed += processed

        self.stdout.write(self.style.SUCCESS(
            f'\nCompleted! Processed {total_processed} embeddings.'
        ))

    def load_embedding_model(self, config):
        """Load the embedding model based on configuration."""
        try:
            if config.model_provider == 'sentence-transformers':
                from sentence_transformers import SentenceTransformer
                self.stdout.write(f'Loading model: {config.model_name}...')
                # Force CPU usage to avoid CUDA compatibility issues
                model = SentenceTransformer(config.model_name, device='cpu')
                self.stdout.write(self.style.SUCCESS('Model loaded successfully (using CPU)'))
                return model
            
            elif config.model_provider == 'openai':
                import openai
                if not config.api_key:
                    self.stdout.write(self.style.ERROR(
                        'OpenAI API key not configured'
                    ))
                    return None
                openai.api_key = config.api_key
                return 'openai'  # Return marker for OpenAI
            
            else:
                self.stdout.write(self.style.ERROR(
                    f'Unsupported provider: {config.model_provider}'
                ))
                return None
                
        except ImportError as e:
            self.stdout.write(self.style.ERROR(
                f'Failed to import embedding library: {e}\n'
                f'Install with: pip install sentence-transformers'
            ))
            return None
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error loading model: {e}'))
            return None

    def process_lookup_table(self, content_type, model, config, refresh, batch_size):
        """Process all records in a lookup table, computing embeddings for all text fields."""
        from django.db import models as django_models
        
        lookup_model = content_type.model_class()
        if not lookup_model:
            return 0
            
        table_name = content_type.model
        
        self.stdout.write(f'\nProcessing table: {table_name}')
        
        # Delete existing embeddings if refresh
        if refresh:
            deleted_count = LookupEmbedding.objects.filter(
                content_type=content_type,
                embedding_config=config
            ).delete()[0]
            self.stdout.write(f'  Deleted {deleted_count} existing embeddings')
        
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
            self.stdout.write(self.style.WARNING(f'  No text fields found in {table_name}'))
            return 0
        
        self.stdout.write(f'  Text fields to embed: {", ".join(text_fields)}')
        
        # Get all records
        records = lookup_model.objects.all()
        total_records = records.count()
        
        self.stdout.write(f'  Total records: {total_records}')
        
        processed_count = 0
        
        # Process in batches
        for i in range(0, total_records, batch_size):
            batch = records[i:i + batch_size]
            batch_embeddings = []
            
            for record in batch:
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
                        if config.model_provider == 'sentence-transformers':
                            embedding = model.encode(str(text_value))
                            embedding_list = embedding.tolist()
                        elif config.model_provider == 'openai':
                            import openai
                            response = openai.Embedding.create(
                                input=str(text_value),
                                model=config.model_name
                            )
                            embedding_list = response['data'][0]['embedding']
                        else:
                            continue
                        
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
                        log.error(f'Error computing embedding for {pk_value}.{field_name}: {e}')
                        continue
            
            # Bulk create embeddings
            if batch_embeddings:
                LookupEmbedding.objects.bulk_create(
                    batch_embeddings,
                    ignore_conflicts=True
                )
                processed_count += len(batch_embeddings)
                self.stdout.write(f'  Processed: {i + len(batch)}/{total_records}')
        
        self.stdout.write(self.style.SUCCESS(
            f'  Completed {table_name}: {processed_count} embeddings created'
        ))
        
        return processed_count

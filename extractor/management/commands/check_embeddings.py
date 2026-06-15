"""
Management command to check embedding configuration and status.
"""

from django.core.management.base import BaseCommand
from extractor.models import EmbeddingConfiguration, LookupEmbedding
from django.db.models import Count


class Command(BaseCommand):
    help = 'Check embedding configuration and computed embeddings status'

    def handle(self, *args, **options):
        self.stdout.write(self.style.HTTP_INFO('\n=== Embedding Configuration Status ===\n'))
        
        # Check for active config
        active_config = EmbeddingConfiguration.objects.filter(is_active=True).first()
        
        if active_config:
            self.stdout.write(self.style.SUCCESS(f'✓ Active Configuration Found:'))
            self.stdout.write(f'  Model: {active_config.model_name}')
            self.stdout.write(f'  Provider: {active_config.model_provider}')
            self.stdout.write(f'  Dimensions: {active_config.embedding_dimension}')
            self.stdout.write(f'  Similarity Threshold: {active_config.similarity_threshold}')
            self.stdout.write(f'  Top K Results: {active_config.top_k_results}')
        else:
            self.stdout.write(self.style.ERROR('✗ No active embedding configuration found!'))
            self.stdout.write(self.style.WARNING('\nTo fix:'))
            self.stdout.write('  1. Go to Django Admin → Embedding Configurations')
            self.stdout.write('  2. Create a new configuration:')
            self.stdout.write('     - Model Name: all-MiniLM-L6-v2')
            self.stdout.write('     - Model Provider: sentence-transformers')
            self.stdout.write('     - Embedding Dimension: 384')
            self.stdout.write('     - Is Active: ✓')
            return
        
        self.stdout.write(self.style.HTTP_INFO('\n=== Computed Embeddings Status ===\n'))
        
        # Check embeddings
        total_embeddings = LookupEmbedding.objects.filter(
            embedding_config=active_config
        ).count()
        
        if total_embeddings == 0:
            self.stdout.write(self.style.ERROR('✗ No embeddings computed yet!'))
            self.stdout.write(self.style.WARNING('\nTo fix:'))
            self.stdout.write('  1. Install sentence-transformers:')
            self.stdout.write('     pip install sentence-transformers')
            self.stdout.write('  2. Compute embeddings:')
            self.stdout.write('     python manage.py compute_lookup_embeddings')
            return
        
        self.stdout.write(self.style.SUCCESS(f'✓ Total Embeddings: {total_embeddings}'))
        
        # Show breakdown by table
        by_table = LookupEmbedding.objects.filter(
            embedding_config=active_config
        ).values('content_type__model').annotate(count=Count('id')).order_by('-count')
        
        self.stdout.write('\nBreakdown by Lookup Table:')
        for item in by_table:
            table_name = item['content_type__model']
            count = item['count']
            self.stdout.write(f'  - {table_name}: {count} embeddings')
        
        self.stdout.write(self.style.SUCCESS('\n✓ Semantic search is ready to use!'))
        self.stdout.write('\nNext: Run an extraction to test semantic search.')

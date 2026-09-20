"""
Management command to compute and store embeddings for lookup table entries.

Usage:
    python manage.py compute_lookup_embeddings --refresh  # Rebuild into a new index version and swap on success
    python manage.py compute_lookup_embeddings            # Fill gaps in the current index
"""

from django.core.management.base import BaseCommand
from extractor.models import EmbeddingConfiguration
from extractor.services.embedding_index import compute_lookup_embeddings
from extractor.services.embeddings import EmbeddingUnavailableError
from logging import getLogger

log = getLogger(__name__)


class Command(BaseCommand):
    help = 'Compute and store embeddings for lookup table entries'

    def add_arguments(self, parser):
        parser.add_argument(
            '--refresh',
            action='store_true',
            help='Build a new index version and swap it in only if the build succeeds',
        )

    def handle(self, *args, **options):
        refresh = options['refresh']

        embedding_config = EmbeddingConfiguration.objects.filter(is_active=True).first()
        if not embedding_config:
            self.stdout.write(self.style.ERROR(
                'No active embedding configuration found. '
                'Please create one in the admin panel.'
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f'Using embedding model: {embedding_config.model_name} ({embedding_config.model_provider})'
        ))

        try:
            result = compute_lookup_embeddings(
                embedding_config,
                refresh=refresh,
                progress_callback=lambda msg: self.stdout.write(f'  {msg}'),
            )
        except EmbeddingUnavailableError as e:
            self.stdout.write(self.style.ERROR(f'Embedding provider unavailable: {e}'))
            return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Embedding computation failed: {e}'))
            return

        self.stdout.write(self.style.SUCCESS(
            f"\nCompleted! {result['total_processed']} embeddings created "
            f"({result['total_failed']} failed), index v{result['index_version']}."
        ))

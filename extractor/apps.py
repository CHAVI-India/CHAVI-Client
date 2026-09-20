from django.apps import AppConfig


class ExtractorConfig(AppConfig):
    name = 'extractor'

    def ready(self):
        # Warm the embedding provider inside each Celery worker process at
        # startup, so the first extraction doesn't pay the model-load cost.
        # worker_process_init only fires under a Celery worker — the web
        # process keeps lazy loading.
        try:
            from celery.signals import worker_process_init
        except ImportError:
            return

        @worker_process_init.connect
        def _warm_embedding_provider(**_kwargs):
            from logging import getLogger
            log = getLogger(__name__)
            try:
                from extractor.models import EmbeddingConfiguration
                from extractor.services.embeddings import get_provider
                config = EmbeddingConfiguration.objects.filter(is_active=True).first()
                if config and 'sentence' in (config.model_provider or '').lower():
                    get_provider(config)
                    log.info(f"Embedding provider warmed ({config.model_name})")
            except Exception as e:
                # Cold start still works — the provider lazily loads on first use
                log.warning(f"Embedding provider warm-up failed (will lazy-load): {e}")

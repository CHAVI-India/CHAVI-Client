"""
Warm the HuggingFace cache with the configured NER model so workers never
hit the network on first use. Safe to run at image build or deploy time.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Prefetch the HF NER model (DEID_HF_NER_MODEL) into the HF cache'

    def handle(self, *args, **options):
        from django.conf import settings
        from huggingface_hub import snapshot_download

        model = getattr(
            settings, 'DEID_HF_NER_MODEL',
            'Isotonic/deberta-v3-base_finetuned_ai4privacy_v2')
        self.stdout.write(f'Downloading {model} …')
        path = snapshot_download(model)
        self.stdout.write(self.style.SUCCESS(f'Cached at {path}'))

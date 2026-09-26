"""
Backfill deidentification for ProcessedText rows that predate the feature.

Dispatches one deid Celery task per non-deidentified version that doesn't
already have a deid derivative.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Dispatch deidentification tasks for all non-deidentified processed texts'

    def add_arguments(self, parser):
        parser.add_argument(
            '--upload', type=int, default=None,
            help='Restrict to a single FileUpload id')
        parser.add_argument(
            '--sync', action='store_true',
            help='Run in-process instead of dispatching Celery tasks')

    def handle(self, *args, **options):
        from django.conf import settings
        from extractor.models import ProcessedText

        if not getattr(settings, 'EXTRACTOR_DEID_ENABLED', True):
            self.stdout.write(self.style.WARNING(
                'EXTRACTOR_DEID_ENABLED is False — nothing to do'))
            return

        qs = (ProcessedText.objects
              .filter(deidentified=False, deid_derivatives__isnull=True)
              .select_related('file_upload'))
        if options['upload']:
            qs = qs.filter(file_upload_id=options['upload'])

        targets = list(qs)
        if not targets:
            self.stdout.write(self.style.SUCCESS('Nothing to deidentify.'))
            return

        if options['sync']:
            from extractor.services.text_deidentification import (
                TextDeidentificationService,
            )
            done = failed = 0
            for pt in targets:
                try:
                    if TextDeidentificationService.deidentify(pt):
                        done += 1
                except Exception as e:
                    failed += 1
                    self.stderr.write(
                        self.style.ERROR(f'ProcessedText {pt.id}: {e}'))
            self.stdout.write(self.style.SUCCESS(
                f'Deidentified {done} text(s); {failed} failed.'))
            return

        from extractor.models import BackgroundTask
        from django.utils import timezone
        from extractor.tasks import deidentify_processed_text_task

        dispatched = 0
        for pt in targets:
            task = BackgroundTask.objects.create(
                task_id=f"deid-{pt.id}-{int(timezone.now().timestamp())}",
                task_name=f"Deidentify processed file {pt.id}",
                status='pending',
            )
            deidentify_processed_text_task.delay(task.task_id, pt.id)
            dispatched += 1

        self.stdout.write(self.style.SUCCESS(
            f'Dispatched deidentification for {dispatched} text(s).'))

from django.db import migrations
from django.db import models


def backfill_file_size(apps, schema_editor):
    """Fill file_size from disk for existing rows; leave NULL when the
    physical file is no longer present (the exact case that used to break
    the file listing page)."""
    FileUpload = apps.get_model('extractor', 'FileUpload')
    for upload in FileUpload.objects.all():
        if upload.file_size is None and upload.file:
            try:
                upload.file_size = upload.file.storage.size(upload.file.name)
                upload.save(update_fields=['file_size'])
            except (OSError, FileNotFoundError):
                pass


class Migration(migrations.Migration):

    dependencies = [
        ('extractor', '0036_alter_textdeidentificationpipelineconfig_slug'),
    ]

    operations = [
        migrations.AddField(
            model_name='fileupload',
            name='file_size',
            field=models.BigIntegerField(blank=True, help_text='Size of the uploaded file in bytes (snapshot at upload time).', null=True),
        ),
        migrations.RunPython(backfill_file_size, migrations.RunPython.noop),
    ]

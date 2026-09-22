import encrypted_model_fields.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('extractor', '0020_extractionreviewbatch_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='extractionresult',
            name='extraction_basis',
            field=models.CharField(blank=True, choices=[('explicit', 'Explicitly reported'), ('inferred', 'Inferred from context'), ('clinical_inference', 'Clinically inferred'), ('calculated', 'Calculated from reported values'), ('unknown', 'Unknown')], default='', max_length=24),
        ),
        migrations.AddField(
            model_name='extractionresult',
            name='inference_note',
            field=encrypted_model_fields.fields.EncryptedTextField(blank=True, null=True),
        ),
    ]

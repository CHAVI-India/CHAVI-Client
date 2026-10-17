from django.db import migrations


def seed(apps, schema_editor):
    P = apps.get_model('extractor', 'TextDeidentificationPipelineConfig')
    if P.objects.filter(slug='spacy-no-llm-rules').exists():
        return
    P.objects.create(
        name='spaCy · no-LLM · rules', slug='spacy-no-llm-rules',
        ner_engine='spacy', is_default=True)


def unseed(apps, schema_editor):
    P = apps.get_model('extractor', 'TextDeidentificationPipelineConfig')
    P.objects.filter(slug='spacy-no-llm-rules').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('extractor', '0033_deid_pipeline_and_model_type'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

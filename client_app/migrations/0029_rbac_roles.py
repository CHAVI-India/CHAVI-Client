"""Create the seven functional RBAC role groups.

Groups are the user-facing unit of authorisation in CHAVI: administrators
assign users to these groups in the Django admin (or via the shell), and the
views check the underlying model permissions with ``PermissionRequiredMixin``
/ ``perms.*`` in templates.

``post_migrate`` only creates ``auth.Permission`` rows *after* all migrations
have run, so this migration calls ``create_permissions`` manually for the
involved apps before resolving the permission matrix below.

The ``ROLES`` dict is also imported by the test-suite and documentation to
describe the role matrix.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations


# Models a clinical user may *read* through the frontend (patient summary,
# list views, exports).
CLINICAL_VIEW_MODELS = [
    'patient', 'diagnosis', 'outcome', 'lesion', 'lesionresponse', 'symptom',
    'germlinegenomicalterations', 'pathology', 'immunohistochemistry',
    'cytogenetics', 'somaticgenomicalterations', 'geneexpressiondata',
    'epigeneticdata', 'othertreatment', 'radiotherapy', 'radiotherapyvolume',
    'radiotherapydosevolumedata', 'surgery', 'concomitantmedications',
    'systemictherapy', 'systemictherapyschedule', 'adverseeffects',
    'patientreportedoutcome', 'patientoutcome', 'comorbidity',
    'stageinformation', 'laboratoryresults', 'patientassessment',
    'dicomstudy', 'dicomseries', 'dicominstance', 'patientdicomfile',
    'project', 'taskrun',
]

# Clinical models that have frontend create/update views (BaseFormView /
# BaseUpdateView). Deletion deliberately stays admin-only.
CLINICAL_EDIT_MODELS = [
    'patient', 'comorbidity', 'symptom', 'patientassessment',
    'laboratoryresults', 'patientoutcome', 'patientreportedoutcome',
    'germlinegenomicalterations', 'patientdicomfile', 'diagnosis',
    'pathology', 'stageinformation', 'lesion', 'lesionresponse', 'surgery',
    'radiotherapy', 'radiotherapyvolume', 'radiotherapydosevolumedata',
    'systemictherapy', 'systemictherapyschedule', 'othertreatment',
    'concomitantmedications', 'outcome', 'adverseeffects',
    'immunohistochemistry', 'cytogenetics', 'somaticgenomicalterations',
    'geneexpressiondata', 'epigeneticdata',
]


def _ca(verbs, models):
    return [f'client_app.{verb}_{model}' for verb in verbs for model in models]


def _app(app_label, verbs, models):
    return [f'{app_label}.{verb}_{model}' for verb in verbs for model in models]


ROLES = {
    'Clinical Data Viewer': (
        _ca(['view'], CLINICAL_VIEW_MODELS)
    ),
    'Clinical Data Entry': (
        _ca(['view'], CLINICAL_VIEW_MODELS)
        + _ca(['add', 'change'], CLINICAL_EDIT_MODELS)
    ),
    'Data Import Operator': (
        _app('data_import', ['add', 'view', 'change'], ['fileimportsession'])
        + _ca(['view'], ['dicomstudy', 'unprocesseddicomstudies', 'taskrun'])
        + _ca(['add'], ['patient', 'patientdicomfile'])
        + _ca(['view', 'add', 'change'], ['bulkdicomuploadsession'])
        + _ca(['view', 'change'], ['bulkdicomstudymatch'])
        + _ca(['view'], ['patient', 'patientdicomfile'])
        + _app('dicom_server', ['view'], ['remotedicomnode', 'inbounddicominstance'])
        + _app('dicom_server', ['add', 'view'], ['retrievaljob', 'patientidalias'])
    ),
    'LLM Extraction Operator': (
        _app('extractor', ['add', 'view', 'change', 'delete'], ['fileupload'])
        + _app('extractor', ['view', 'change'], ['processedtext', 'extractionresult'])
        + _app('extractor', ['add', 'view'], ['extractionjob', 'recordcreation'])
        + _app('extractor', ['view'], [
            'extractedrecord', 'extractionreviewbatch', 'backgroundtask',
            'databasetable', 'databasefield', 'responsemodel',
        ])
        + _ca(['view'], ['patient', 'taskrun'])
    ),
    'LLM Configuration': (
        _app('extractor', ['add', 'view', 'change', 'delete'], [
            'clientconfiguration', 'responsemodel', 'responsemodeltable',
            'responsemodeltablefield', 'databasetable', 'databasefield',
            'instructormessage', 'embeddingconfiguration',
        ])
        + _app('extractor', ['view'], [
            'fileupload', 'processedtext', 'extractionjob', 'extractionresult',
            'recordcreation', 'lookupembedding', 'backgroundtask',
        ])
        + _ca(['view'], ['taskrun'])
    ),
    'Deidentification Operator': (
        _app('deidentification', ['add', 'view'], ['deidpatient', 'deidentificationjob'])
        + _app('deidentification', ['view'], [
            'deidstudy', 'deidseries', 'deidinstance', 'pixelredactionlog',
        ])
        + _ca(['view'], [
            'patient', 'dicomstudy', 'dicomseries', 'dicominstance', 'taskrun',
        ])
    ),
    'DICOM Administrator': (
        _app('dicom_server', ['add', 'view', 'change', 'delete'], [
            'remotedicomnode', 'patientidalias',
        ])
        + _app('dicom_server', ['view', 'change'], [
            'dicomserverconfiguration', 'autoretrievalstate',
        ])
        + _app('dicom_server', ['view'], ['inbounddicominstance', 'retrievaljob'])
        + _ca(['view'], ['dicomstudy', 'taskrun'])
    ),
}


def create_rbac_groups(apps, schema_editor):
    db_alias = schema_editor.connection.alias

    # Permission rows are normally created by the post_migrate signal *after*
    # this migration — create them manually so we can assign them below.
    for app_label in (
        'auth', 'client_app', 'data_import', 'deidentification',
        'dicom_server', 'extractor',
    ):
        app_config = apps.get_app_config(app_label)
        app_config.models_module = True
        create_permissions(
            app_config, verbosity=0, interactive=False,
            using=db_alias, apps=apps,
        )
        app_config.models_module = None

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    for role_name, perm_strings in ROLES.items():
        group, _ = Group.objects.using(db_alias).get_or_create(name=role_name)
        perm_qs = Permission.objects.using(db_alias).filter(
            content_type__app_label__in={p.split('.')[0] for p in perm_strings},
        )
        by_key = {
            f'{p.content_type.app_label}.{p.codename}': p for p in perm_qs
        }
        missing = [p for p in perm_strings if p not in by_key]
        if missing:
            raise RuntimeError(
                f'Cannot build role {role_name!r}: unknown permissions '
                f'{sorted(set(missing))}'
            )
        group.permissions.set([by_key[p] for p in perm_strings])


def remove_rbac_groups(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Group = apps.get_model('auth', 'Group')
    Group.objects.using(db_alias).filter(name__in=list(ROLES)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('client_app', '0028_backfill_canonical_patient_id'),
        ('data_import', '0006_fileparentrecordmapping'),
        ('deidentification', '0001_initial'),
        ('dicom_server', '0003_alter_dicomserverconfiguration_ae_title_and_more'),
        ('extractor', '0025_alter_clientconfiguration_context_size_and_more'),
    ]

    operations = [
        migrations.RunPython(create_rbac_groups, remove_rbac_groups),
    ]

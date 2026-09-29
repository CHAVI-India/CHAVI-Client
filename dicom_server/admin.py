from django.contrib import admin, messages
from unfold.admin import ModelAdmin

from dicom_server.models import (
    DICOMServerConfiguration, RemoteDICOMNode, InboundDICOMInstance,
    PatientIDAlias, AutoRetrievalState, RetrievalJob,
    RetrievalBatch, RetrievalBatchPatient,
)
from dicom_server.services import qr_client
from dicom_server.services.schedule_sync import sync_node_schedule


@admin.register(DICOMServerConfiguration)
class DICOMServerConfigurationAdmin(ModelAdmin):
    list_display = ['ae_title', 'bind_address', 'port', 'max_pdu', 'qr_timeout', 'is_enabled', 'updated_at']

    def has_add_permission(self, request):
        return not DICOMServerConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class PatientIDAliasInline(admin.TabularInline):
    model = PatientIDAlias
    extra = 1
    autocomplete_fields = ['patient']


@admin.register(RemoteDICOMNode)
class RemoteDICOMNodeAdmin(ModelAdmin):
    list_display = [
        'name', 'ae_title', 'host', 'port', 'is_active', 'prefer_c_get',
        'auto_retrieve_enabled', 'crontab_display',
    ]
    list_filter = ['is_active', 'auto_retrieve_enabled']
    search_fields = ['name', 'ae_title', 'host']
    actions = ['test_echo', 'sync_schedules']
    inlines = [PatientIDAliasInline]
    fieldsets = (
        (None, {
            'fields': ('name', 'ae_title', 'host', 'port', 'is_active', 'prefer_c_get'),
        }),
        ('Patient ID mapping', {
            'fields': ('patient_id_transforms',),
            'description': 'Regex transform rules used to generate remote '
                           'PatientID candidates for C-FIND.',
        }),
        ('Automatic retrieval schedule', {
            'fields': (
                'auto_retrieve_enabled',
                'auto_retrieve_minute', 'auto_retrieve_hour',
                'auto_retrieve_day_of_week', 'auto_retrieve_day_of_month',
                'auto_retrieve_month_of_year',
                'auto_retrieve_min_interval_minutes',
                'auto_retrieve_batch_size',
            ),
        }),
    )

    @admin.display(description='Schedule')
    def crontab_display(self, obj):
        return ' '.join(obj.crontab_tuple)

    def test_echo(self, request, queryset):
        for node in queryset:
            try:
                ok, err = qr_client.echo(node)
            except Exception as e:
                ok, err = False, str(e)
            if ok:
                self.message_user(request, f"{node}: C-ECHO succeeded", messages.SUCCESS)
            else:
                self.message_user(request, f"{node}: C-ECHO failed {err}", messages.ERROR)
    test_echo.short_description = "Test connectivity (C-ECHO)"

    @admin.action(description='Sync selected node schedules to Celery Beat')
    def sync_schedules(self, request, queryset):
        for node in queryset:
            sync_node_schedule(node)
        self.message_user(request, 'Node schedules synced.')


@admin.register(InboundDICOMInstance)
class InboundDICOMInstanceAdmin(ModelAdmin):
    list_display = [
        'received_at', 'status', 'dicom_patient_id', 'matched_patient',
        'study_instance_uid', 'sop_instance_uid', 'modality', 'calling_ae_title',
    ]
    list_filter = ['status', 'modality', 'calling_ae_title']
    search_fields = ['dicom_patient_id', 'study_instance_uid', 'sop_instance_uid']
    date_hierarchy = 'received_at'
    readonly_fields = [f.name for f in InboundDICOMInstance._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(RetrievalJob)
class RetrievalJobAdmin(ModelAdmin):
    list_display = ['pk', 'patient', 'node', 'status', 'instances_received', 'created_by', 'created_at']
    list_filter = ['status', 'node']
    readonly_fields = [f.name for f in RetrievalJob._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(AutoRetrievalState)
class AutoRetrievalStateAdmin(ModelAdmin):
    list_display = ['patient', 'node', 'last_attempt_at', 'last_success_at']
    list_filter = ['node']
    search_fields = ['patient__patient_id']
    readonly_fields = [f.name for f in AutoRetrievalState._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RetrievalBatch)
class RetrievalBatchAdmin(ModelAdmin):
    list_display = [
        'pk', 'node', 'status', 'created_by', 'created_at', 'completed_at',
    ]
    list_filter = ['status', 'node']
    readonly_fields = [f.name for f in RetrievalBatch._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(RetrievalBatchPatient)
class RetrievalBatchPatientAdmin(ModelAdmin):
    list_display = ['batch', 'patient', 'query_status', 'selected', 'job']
    list_filter = ['query_status', 'selected']
    search_fields = ['patient__patient_id']
    readonly_fields = [f.name for f in RetrievalBatchPatient._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

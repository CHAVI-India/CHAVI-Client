from django.contrib import admin, messages
from unfold.admin import ModelAdmin

from dicom_server.models import (
    DICOMServerConfiguration, RemoteDICOMNode, InboundDICOMInstance, RetrievalJob,
)


@admin.register(DICOMServerConfiguration)
class DICOMServerConfigurationAdmin(ModelAdmin):
    list_display = ['ae_title', 'bind_address', 'port', 'max_pdu', 'qr_timeout', 'is_enabled', 'updated_at']

    def has_add_permission(self, request):
        return not DICOMServerConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RemoteDICOMNode)
class RemoteDICOMNodeAdmin(ModelAdmin):
    list_display = ['name', 'ae_title', 'host', 'port', 'is_active', 'prefer_c_get']
    list_filter = ['is_active']
    search_fields = ['name', 'ae_title', 'host']
    actions = ['test_echo']

    def test_echo(self, request, queryset):
        from dicom_server.services import qr_client
        for node in queryset:
            try:
                ok = qr_client.echo(node)
            except Exception as e:
                ok, err = False, str(e)
            else:
                err = ''
            if ok:
                self.message_user(request, f"{node}: C-ECHO succeeded", messages.SUCCESS)
            else:
                self.message_user(request, f"{node}: C-ECHO failed {err}", messages.ERROR)
    test_echo.short_description = "Test connectivity (C-ECHO)"


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

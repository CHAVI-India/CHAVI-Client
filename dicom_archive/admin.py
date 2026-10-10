from django.contrib import admin
from unfold.admin import ModelAdmin

from dicom_archive.models import ArchiveConfiguration, ArchiveLocation, ArchivedStudy


@admin.register(ArchiveLocation)
class ArchiveLocationAdmin(ModelAdmin):
    list_display = ['name', 'storage_type', 'path', 'is_default', 'is_active', 'updated_at']
    list_filter = ['storage_type', 'is_default', 'is_active']
    search_fields = ['name', 'path']


@admin.register(ArchiveConfiguration)
class ArchiveConfigurationAdmin(ModelAdmin):
    list_display = ['enabled', 'archive_after_days', 'delete_local_after_archive', 'batch_limit', 'updated_at']

    def has_add_permission(self, request):
        return not ArchiveConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ArchivedStudy)
class ArchivedStudyAdmin(ModelAdmin):
    list_display = ['study', 'location', 'status', 'reason', 'size_bytes', 'instance_count', 'archived_at', 'archived_by']
    list_filter = ['status', 'reason', 'location']
    search_fields = ['study__study_instance_uid']
    readonly_fields = [f.name for f in ArchivedStudy._meta.fields]

    def has_add_permission(self, request):
        return False

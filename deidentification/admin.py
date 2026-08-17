from django.contrib import admin

from deidentification.models import (
    DeidPatient, DeidStudy, DeidSeries, DeidInstance,
    DeidentificationJob, PixelRedactionLog,
)


@admin.register(DeidPatient)
class DeidPatientAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'created_at')
    search_fields = ('patient__patient_id',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(DeidStudy)
class DeidStudyAdmin(admin.ModelAdmin):
    list_display = ('id', 'study', 'deid_patient', 'created_at')
    search_fields = ('study__study_instance_uid',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(DeidSeries)
class DeidSeriesAdmin(admin.ModelAdmin):
    list_display = ('id', 'series', 'deid_study', 'created_at')
    search_fields = ('series__series_instance_uid',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(DeidInstance)
class DeidInstanceAdmin(admin.ModelAdmin):
    list_display = ('id', 'instance', 'deid_series', 'created_at')
    search_fields = ('instance__sop_instance_uid',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(DeidentificationJob)
class DeidentificationJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'study', 'status', 'processed_count', 'failed_count', 'failed_series_count', 'created_at')
    list_filter = ('status',)
    search_fields = ('study__study_instance_uid',)
    readonly_fields = ('created_at', 'updated_at', 'completed_at', 'error_log')


@admin.register(PixelRedactionLog)
class PixelRedactionLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'job', 'file_path', 'created_at')
    readonly_fields = ('created_at',)

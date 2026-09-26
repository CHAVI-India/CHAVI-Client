from django.contrib import admin
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.contrib.filters.admin import (
    RangeDateTimeFilter,
    ChoicesDropdownFilter,
    RelatedDropdownFilter,
)
from .models import (
    ClientConfiguration,
    FileUpload,
    ProcessedText,
    DatabaseTable,
    DatabaseField,
    ResponseModel,
    ResponseModelTable,
    ResponseModelTableField,
    InstructorMessage,
    ExtractionJob,
    ExtractionResult,
    RecordCreation,
    RecordCreationField,
    ExtractionReviewBatch,
    EmbeddingConfiguration,
    LookupEmbedding,
)
from allauth.account.decorators import secure_admin_login

# For Django AllAuth
admin.autodiscover()
admin.site.login = secure_admin_login(admin.site.login)

# region Inlines

class DatabaseFieldInline(TabularInline):
    model = DatabaseField
    extra = 1
    fields = ['clientapp_field_name', 'field_type', 'lookup_field', 'lookup_content_type']
    autocomplete_fields = []
    show_change_link = True


class ResponseModelTableInline(TabularInline):
    model = ResponseModelTable
    extra = 1
    fields = ['database_table']
    autocomplete_fields = ['database_table']
    show_change_link = True


class ResponseModelTableFieldInline(TabularInline):
    model = ResponseModelTableField
    extra = 1
    fields = ['field', 'order']
    autocomplete_fields = ['field']
    ordering = ['order']


class InstructorMessageInline(StackedInline):
    model = InstructorMessage
    extra = 1
    fields = ['role', 'prompt']
    tab = True


class ExtractionResultInline(TabularInline):
    model = ExtractionResult
    extra = 0
    fields = ['database_field', 'extracted_data', 'data_accuracy', 'data_edited', 'verified_by', 'verification_date_time']
    readonly_fields = ['database_field', 'extracted_data', 'created_at']
    show_change_link = True


class RecordCreationInline(TabularInline):
    model = RecordCreation
    extra = 0
    fields = ['database_table', 'created_record_pk', 'operation', 'record_created', 'record_created_by', 'record_created_error']
    readonly_fields = ['record_created_at']
    show_change_link = True


class RecordCreationFieldInline(TabularInline):
    model = RecordCreationField
    extra = 0
    fields = ['extraction_result', 'previous_value']
    readonly_fields = ['created_at']


# endregion


# region Model Admin Classes

@admin.register(ClientConfiguration)
class ClientConfigurationAdmin(ModelAdmin):
    list_display = ['llm_model_name', 'model_provider', 'model_api_key_expires', 'model_api_key_validity', 'created_at']
    list_filter = ['model_provider', 'model_api_key_expires', ('created_at', RangeDateTimeFilter)]
    search_fields = ['llm_model_name', 'model_provider']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('LLM Configuration', {
            'fields': ['llm_model_name', 'model_provider', 'model_base_url']
        }),
        ('Request Limits', {
            'fields': ['context_size', 'model_max_tokens', 'request_timeout']
        }),
        ('API Key', {
            'fields': ['model_api_key', ('model_api_key_expires', 'model_api_key_validity'), 'model_api_refresh_key']
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )


@admin.register(FileUpload)
class FileUploadAdmin(ModelAdmin):
    list_display = ['file', 'file_type', 'patient_id', 'processing_status', 'created_at']
    list_filter = [
        ('processing_status', ChoicesDropdownFilter),
        ('file_type', ChoicesDropdownFilter),
        ('created_at', RangeDateTimeFilter),
    ]
    search_fields = ['file', 'patient_id__patient_id']
    autocomplete_fields = ['patient_id']
    readonly_fields = ['file_type', 'created_at', 'updated_at']
    fieldsets = (
        ('File', {
            'fields': ['file', 'file_type', 'patient_id']
        }),
        ('Status', {
            'fields': ['processing_status']
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )


@admin.register(ProcessedText)
class ProcessedTextAdmin(ModelAdmin):
    list_display = ['file_upload', 'processed_file_path', 'processed_by_user', 'created_at']
    list_filter = [('created_at', RangeDateTimeFilter)]
    search_fields = ['file_upload__file', 'processed_by_user__username']
    autocomplete_fields = ['file_upload', 'processed_by_user']
    readonly_fields = ['processed_file_path', 'created_at', 'updated_at']
    fieldsets = (
        ('Processed File', {
            'fields': ['file_upload', 'processed_file_path', 'source_sheet', 'processing_warning', 'version', 'is_source_alias', 'processed_by_user']
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )


@admin.register(DatabaseTable)
class DatabaseTableAdmin(ModelAdmin):
    list_display = ['clientapp_content_type', 'clientapp_table_pk_field_name', 'created_at']
    list_filter = [('created_at', RangeDateTimeFilter)]
    search_fields = ['clientapp_content_type__model']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [DatabaseFieldInline]
    fieldsets = (
        ('Table Configuration', {
            'fields': ['clientapp_content_type', 'clientapp_table_pk_field_name', 'clientapp_table_fk_fields']
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )


@admin.register(DatabaseField)
class DatabaseFieldAdmin(ModelAdmin):
    list_display = ['clientapp_database_table', 'clientapp_field_name', 'field_type', 'lookup_field', 'created_at']
    list_filter = [
        ('field_type', ChoicesDropdownFilter),
        'lookup_field',
        ('clientapp_database_table', RelatedDropdownFilter),
        ('created_at', RangeDateTimeFilter),
    ]
    search_fields = ['clientapp_field_name', 'clientapp_database_table__clientapp_content_type__model']
    autocomplete_fields = ['clientapp_database_table']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Field Configuration', {
            'fields': ['clientapp_database_table', 'clientapp_field_name', 'field_type', 'field_validation']
        }),
        ('Lookup Configuration', {
            'fields': ['lookup_field', 'lookup_content_type', 'lookup_table_value_field_name', 'lookup_table_pk_field_name', 'lookup_label_fields', 'lookup_config_source'],
            'description': "Set 'Auto-discovered' to let schema discovery manage these fields; 'Manual' protects your choices from being overwritten."
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )

    def save_model(self, request, obj, form, change):
        """
        Mark lookup config as manual when a human edits the lookup fields in
        admin, so the next schema discovery does not overwrite the choice.
        """
        if change:
            lookup_fields = {'lookup_field', 'lookup_content_type',
                             'lookup_table_value_field_name', 'lookup_table_pk_field_name',
                             'lookup_label_fields'}
            if lookup_fields & set(form.changed_data) and 'lookup_config_source' not in form.changed_data:
                obj.lookup_config_source = 'manual'
        super().save_model(request, obj, form, change)


@admin.register(ResponseModel)
class ResponseModelAdmin(ModelAdmin):
    list_display = ['name', 'client', 'created_at']
    list_filter = [
        ('client', RelatedDropdownFilter),
        ('created_at', RangeDateTimeFilter),
    ]
    search_fields = ['name', 'client__llm_model_name']
    autocomplete_fields = ['client']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ResponseModelTableInline, InstructorMessageInline]
    fieldsets = (
        ('Response Model', {
            'fields': ['name', 'client']
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )


@admin.register(ResponseModelTable)
class ResponseModelTableAdmin(ModelAdmin):
    list_display = ['response_model', 'database_table', 'created_at']
    list_filter = [
        ('response_model', RelatedDropdownFilter),
        ('database_table', RelatedDropdownFilter),
        ('created_at', RangeDateTimeFilter),
    ]
    search_fields = ['response_model__name', 'database_table__clientapp_content_type__model']
    autocomplete_fields = ['response_model', 'database_table']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ResponseModelTableFieldInline]
    fieldsets = (
        ('Table Mapping', {
            'fields': ['response_model', 'database_table']
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )


@admin.register(InstructorMessage)
class InstructorMessageAdmin(ModelAdmin):
    list_display = ['response_model', 'role', 'created_at']
    list_filter = [
        ('role', ChoicesDropdownFilter),
        ('response_model', RelatedDropdownFilter),
        ('created_at', RangeDateTimeFilter),
    ]
    search_fields = ['response_model__name']
    autocomplete_fields = ['response_model']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Message', {
            'fields': ['response_model', 'role', 'prompt']
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )


@admin.register(ExtractionJob)
class ExtractionJobAdmin(ModelAdmin):
    list_display = ['response_model', 'processed_file', 'extraction_status', 'extracted_by', 'tokens_used', 'extraction_start_datetime']
    list_filter = [
        ('extraction_status', ChoicesDropdownFilter),
        ('response_model', RelatedDropdownFilter),
        ('extracted_by', RelatedDropdownFilter),
        ('extraction_start_datetime', RangeDateTimeFilter),
    ]
    search_fields = ['response_model__name', 'extracted_by__username', 'processed_file__file_upload__file']
    autocomplete_fields = ['response_model', 'processed_file', 'extracted_by']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ExtractionResultInline, RecordCreationInline]
    fieldsets = (
        ('Job', {
            'fields': ['response_model', 'processed_file', 'extracted_by', 'processed_file_chunked']
        }),
        ('Status', {
            'fields': ['extraction_status', ('extraction_start_datetime', 'extraction_end_datetime'), 'extraction_error']
        }),
        ('LLM Usage', {
            'fields': ['tokens_used', 'raw_llm_response']
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )


@admin.register(ExtractionResult)
class ExtractionResultAdmin(ModelAdmin):
    list_display = ['extraction_job', 'database_field', 'data_accuracy', 'data_edited', 'verified_by', 'created_at']
    list_filter = [
        ('data_accuracy', ChoicesDropdownFilter),
        'data_edited',
        ('extraction_job', RelatedDropdownFilter),
        ('verified_by', RelatedDropdownFilter),
        ('created_at', RangeDateTimeFilter),
    ]
    search_fields = ['extraction_job__response_model__name', 'database_field__clientapp_field_name', 'verified_by__username']
    autocomplete_fields = ['extraction_job', 'database_field', 'verified_by']
    readonly_fields = ['extracted_data', 'data_accuracy', 'data_edited', 'edited_data', 'review_change', 'source_kind', 'verified_by', 'verification_date_time', 'created_at', 'updated_at']
    fieldsets = (
        ('Extraction', {
            'fields': ['extraction_job', 'database_field', 'extracted_data']
        }),
        ('Verification', {
            'fields': ['data_accuracy', ('data_edited', 'edited_data'), 'verified_by', 'verification_date_time']
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )


@admin.register(RecordCreation)
class RecordCreationAdmin(ModelAdmin):
    list_display = ['extraction_job', 'database_table', 'created_record_pk', 'operation', 'review_batch', 'record_created', 'record_created_by', 'record_created_at']
    list_filter = [
        ('operation', ChoicesDropdownFilter),
        'record_created',
        ('database_table', RelatedDropdownFilter),
        ('record_created_by', RelatedDropdownFilter),
        ('record_created_at', RangeDateTimeFilter),
    ]
    search_fields = ['extraction_job__response_model__name', 'created_record_pk', 'database_table__clientapp_content_type__model']
    autocomplete_fields = ['extraction_job', 'database_table', 'record_created_by']
    readonly_fields = ['record_created_at', 'review_batch', 'created_at', 'updated_at']
    inlines = [RecordCreationFieldInline]
    fieldsets = (
        ('Record Operation', {
            'fields': ['extraction_job', 'database_table', 'created_record_pk', 'operation']
        }),
        ('Result', {
            'fields': ['record_created', 'record_created_by', 'record_created_at', 'record_created_error']
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')]
        }),
    )


@admin.register(ExtractionReviewBatch)
class ExtractionReviewBatchAdmin(ModelAdmin):
    list_display = ['id', 'extraction_job', 'status', 'prepared_by', 'approved_by', 'created_at', 'approved_at']
    list_filter = [
        ('status', ChoicesDropdownFilter),
        ('created_at', RangeDateTimeFilter),
        ('approved_at', RangeDateTimeFilter),
    ]
    search_fields = ['id', 'extraction_job__id', 'prepared_by__username', 'approved_by__username']
    readonly_fields = ['id', 'extraction_job', 'prepared_by', 'approved_by', 'status', 'approved_at', 'expires_at', 'request_key', 'source_revision', 'payload_digest', 'snapshot', 'receipt', 'created_at', 'updated_at']
    fieldsets = (
        ('Review', {
            'fields': ['id', 'extraction_job', 'status', ('prepared_by', 'approved_by'), ('created_at', 'approved_at', 'expires_at')]
        }),
        ('Request', {
            'fields': ['request_key', 'source_revision', 'payload_digest']
        }),
        ('Encrypted approval data', {
            'fields': ['snapshot', 'receipt']
        }),
        ('Timestamps', {
            'fields': [('updated_at',)]
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.status != 'approved'

    def has_delete_permission(self, request, obj=None):
        return obj is not None and obj.status != 'approved'


@admin.register(EmbeddingConfiguration)
class EmbeddingConfigurationAdmin(ModelAdmin):
    list_display = ['model_name', 'model_provider', 'embedding_dimension', 'is_active_badge', 'similarity_threshold', 'top_k_results', 'created_at']
    list_filter = [
        'is_active',
        ('model_provider', ChoicesDropdownFilter),
        ('created_at', RangeDateTimeFilter),
    ]
    search_fields = ['model_name', 'model_provider']
    readonly_fields = ['created_at', 'updated_at']
    list_display_links = ['model_name']
    
    fieldsets = (
        ('Model Configuration', {
            'fields': ['model_name', 'model_provider', 'embedding_dimension', 'api_key'],
            'description': 'Configure the embedding model to use for semantic search'
        }),
        ('Search Settings', {
            'fields': ['is_active', 'similarity_threshold', 'top_k_results'],
            'description': 'Control how semantic search behaves during extraction'
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')],
            'classes': ['collapse']
        }),
    )
    
    def is_active_badge(self, obj):
        """Display active status as a badge."""
        if obj.is_active:
            return '✓ Active'
        return '✗ Inactive'
    is_active_badge.short_description = 'Status'
    
    def save_model(self, request, obj, form, change):
        # If setting this config as active, deactivate others
        if obj.is_active:
            EmbeddingConfiguration.objects.exclude(pk=obj.pk).update(is_active=False)
        super().save_model(request, obj, form, change)


@admin.register(LookupEmbedding)
class LookupEmbeddingAdmin(ModelAdmin):
    list_display = ['lookup_table', 'object_id', 'field_name', 'text_value_preview', 'embedding_config', 'created_at']
    list_filter = [
        ('content_type', RelatedDropdownFilter),
        ('embedding_config', RelatedDropdownFilter),
        ('created_at', RangeDateTimeFilter),
    ]
    search_fields = ['object_id', 'text_value', 'field_name']
    autocomplete_fields = ['embedding_config']
    readonly_fields = ['content_type', 'object_id', 'field_name', 'text_value', 'embedding', 'embedding_config', 'created_at', 'updated_at', 'embedding_preview', 'embedding_dimension']
    list_display_links = ['object_id']
    
    fieldsets = (
        ('Lookup Reference', {
            'fields': ['content_type', 'object_id', 'field_name'],
            'description': 'Reference to the lookup table entry'
        }),
        ('Embedding Data', {
            'fields': ['text_value', 'embedding_config', 'embedding_dimension', 'embedding_preview'],
            'description': 'Pre-computed embedding vector for semantic search'
        }),
        ('Timestamps', {
            'fields': [('created_at', 'updated_at')],
            'classes': ['collapse']
        }),
    )
    
    def lookup_table(self, obj):
        """Display lookup table name."""
        return obj.content_type.model
    lookup_table.short_description = 'Lookup Table'
    lookup_table.admin_order_field = 'content_type'
    
    def text_value_preview(self, obj):
        """Show truncated text value."""
        if len(obj.text_value) > 50:
            return f"{obj.text_value[:50]}..."
        return obj.text_value
    text_value_preview.short_description = 'Text Value'
    
    def embedding_dimension(self, obj):
        """Show embedding dimension."""
        if obj.embedding:
            return len(obj.embedding)
        return 0
    embedding_dimension.short_description = 'Dimensions'
    
    def embedding_preview(self, obj):
        """Show first few dimensions of embedding."""
        if obj.embedding:
            preview = str(obj.embedding[:5])
            return f"{preview}... (total: {len(obj.embedding)} dims)"
        return "No embedding"
    embedding_preview.short_description = 'Embedding Vector Preview'
    
    # Make this read-only in admin (embeddings should be computed via management command)
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        # Allow viewing but not editing
        return True
    
    def has_delete_permission(self, request, obj=None):
        # Allow deletion to refresh embeddings
        return True


# endregion

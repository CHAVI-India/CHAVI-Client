import os
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.core.paginator import Paginator
from django.utils import timezone
from logging import getLogger

from extractor.models import (
    ResponseModel, ResponseModelTable, ResponseModelTableField,
    DatabaseTable, DatabaseField, ClientConfiguration,
    ExtractionJob, ExtractionResult, ExtractionStatusChoices, DataAccuracyChoices,
    InstructorMessage, InstructorRole, EmbeddingConfiguration, LookupEmbedding,
    BackgroundTask, FileTypeChoices
)
from extractor.services.schema_discovery import SchemaDiscoveryService
from extractor.services.model_hierarchy import ancestor_tables, identity_field_names
from extractor.services.pydantic_builder import PydanticModelBuilder
from extractor.services.file_processor import FileProcessorService
from extractor.services.instructor_extractor import InstructorExtractionService
from extractor.tasks import advance_extraction_job
from extractor.models import FileUpload, ProcessedText

log = getLogger(__name__)


@login_required
@permission_required(['extractor.add_responsemodel', 'extractor.add_databasetable', 'extractor.add_databasefield'], raise_exception=True)
def wizard_start(request):
    """
    Step 1: Start the wizard - refresh schema and show initial form.
    Requires permissions to add ResponseModel, DatabaseTable, and DatabaseField.
    """
    return render(request, 'extractor/wizard_start.html')


@login_required
@permission_required(['extractor.add_responsemodel', 'extractor.add_databasetable', 'extractor.add_databasefield'], raise_exception=True)
@require_http_methods(["POST"])
def wizard_start_refresh_schema(request):
    """
    AJAX endpoint to refresh schema with progress updates.
    """
    progress_updates = []
    
    def progress_callback(status, message, progress):
        progress_updates.append({
            'status': status,
            'message': message,
            'progress': progress
        })
    
    try:
        discovery_result = SchemaDiscoveryService.discover_and_populate_schema(
            progress_callback=progress_callback
        )
        
        return JsonResponse({
            'success': True,
            'result': discovery_result,
            'progress_updates': progress_updates
        })
    except Exception as e:
        log.error(f"Schema discovery failed: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'progress_updates': progress_updates
        }, status=500)


@login_required
@permission_required(['extractor.add_responsemodel', 'extractor.view_clientconfiguration'], raise_exception=True)
def wizard_step1(request):
    """
    Step 1: Create ResponseModel with name and client selection.
    """
    if request.method == 'POST':
        name = request.POST.get('name')
        client_id = request.POST.get('client')
        
        if not name or not client_id:
            messages.error(request, "Please provide both name and client configuration.")
            return redirect('extractor:wizard_step1')
        
        client = get_object_or_404(ClientConfiguration, id=client_id)

        response_model = ResponseModel.objects.create(
            name=name,
            client=client,
            is_complete=False,
        )

        messages.success(request, f"Response model '{name}' created successfully.")
        return redirect('extractor:wizard_step2', response_model_id=response_model.id)
    
    clients = ClientConfiguration.objects.all()
    
    context = {
        'clients': clients,
    }
    
    return render(request, 'extractor/wizard_step1.html', context)


@login_required
@permission_required(['extractor.add_responsemodeltable', 'extractor.view_databasetable'], raise_exception=True)
def wizard_step2(request, response_model_id):
    """
    Step 2: Select database tables for extraction.
    Requires permissions to add ResponseModelTable and view DatabaseTable.
    """
    response_model = get_object_or_404(ResponseModel, id=response_model_id)

    if request.method == 'POST':
        selected_table_ids = {int(i) for i in request.POST.getlist('tables')}

        if not selected_table_ids:
            messages.error(request, "Please select at least one table.")
            return redirect('extractor:wizard_step2', response_model_id=response_model.id)

        selected_tables = list(DatabaseTable.objects.filter(id__in=selected_table_ids))

        # Required ancestors (the patient_path chain) must be extracted too —
        # write-back needs a parent record before a child can be created.
        ancestors = []
        seen = set(selected_table_ids)
        for table in selected_tables:
            for anc in ancestor_tables(table):
                if anc.id not in seen:
                    seen.add(anc.id)
                    ancestors.append(anc)

        with transaction.atomic():
            ResponseModelTable.objects.filter(response_model=response_model).delete()

            for table in selected_tables:
                ResponseModelTable.objects.create(
                    response_model=response_model,
                    database_table=table
                )

            for table in ancestors:
                model_table = ResponseModelTable.objects.create(
                    response_model=response_model,
                    database_table=table,
                    auto_added=True
                )
                # Pre-select the parent's identity fields (its match_fields
                # key-sets) so existing parents can be detected and new ones
                # created; the user can adjust in step 3.
                identity = set(identity_field_names(table))
                order = 0
                for db_field in table.databasefield_set.filter(is_active=True):
                    if db_field.clientapp_field_name in identity:
                        ResponseModelTableField.objects.create(
                            response_model_table=model_table,
                            field=db_field,
                            order=order
                        )
                        order += 1

        if ancestors:
            messages.info(
                request,
                "Auto-included required parent table(s): "
                + ", ".join(t.clientapp_content_type.model for t in ancestors))
        messages.success(request, f"{len(selected_tables)} table(s) selected.")
        return redirect('extractor:wizard_step3', response_model_id=response_model.id)

    tables_structure = SchemaDiscoveryService.get_hierarchical_table_structure()

    selected_tables = ResponseModelTable.objects.filter(
        response_model=response_model
    ).values_list('database_table_id', flat=True)

    auto_added_ids = set(ResponseModelTable.objects.filter(
        response_model=response_model, auto_added=True
    ).values_list('database_table_id', flat=True))

    context = {
        'response_model': response_model,
        'tables': tables_structure,
        'selected_tables': list(selected_tables),
        'auto_added_ids': auto_added_ids,
    }

    return render(request, 'extractor/wizard_step2.html', context)


@login_required
@permission_required(['extractor.add_responsemodeltablefield', 'extractor.view_databasefield'], raise_exception=True)
def wizard_step3(request, response_model_id):
    """
    Step 3: Select fields for each selected table.
    Requires permissions to add ResponseModelTableField and view DatabaseField.
    """
    response_model = get_object_or_404(ResponseModel, id=response_model_id)

    model_tables = ResponseModelTable.objects.filter(
        response_model=response_model
    ).select_related('database_table__clientapp_content_type')

    if not model_tables.exists():
        messages.error(request, "No tables selected. Please complete step 2.")
        return redirect('extractor:wizard_step2', response_model_id=response_model.id)

    if request.method == 'POST':
        with transaction.atomic():
            ResponseModelTableField.objects.filter(
                response_model_table__response_model=response_model
            ).delete()
            
            for model_table in model_tables:
                field_ids = request.POST.getlist(f'fields_{model_table.id}')

                for order, field_id in enumerate(field_ids):
                    database_field = get_object_or_404(
                        DatabaseField,
                        id=field_id,
                        clientapp_database_table=model_table.database_table,
                    )
                    ResponseModelTableField.objects.create(
                        response_model_table=model_table,
                        field=database_field,
                        order=order
                    )
        
        messages.success(request, "Fields configured successfully.")
        return redirect('extractor:wizard_step4', response_model_id=response_model.id)
    
    tables_with_fields = []
    for model_table in model_tables:
        # Only extractable fields are offered — internal FKs resolve from the
        # parent record and auto-generated PKs (uuid4 defaults) aren't text
        fields = [f for f in DatabaseField.objects.filter(
            clientapp_database_table=model_table.database_table,
            is_active=True,
        ) if f.is_extractable()]
        
        selected_fields = ResponseModelTableField.objects.filter(
            response_model_table=model_table
        ).values_list('field_id', flat=True)
        
        tables_with_fields.append({
            'model_table': model_table,
            'auto_added': model_table.auto_added,
            'fields': fields,
            'selected_fields': list(selected_fields),
        })
    
    context = {
        'response_model': response_model,
        'tables_with_fields': tables_with_fields,
    }
    
    return render(request, 'extractor/wizard_step3.html', context)


@login_required
@permission_required(['extractor.view_responsemodel', 'extractor.change_responsemodel'], raise_exception=True)
def wizard_step4(request, response_model_id):
    """
    Step 4: Review and generate Pydantic model.
    Requires permissions to view and change ResponseModel.
    """
    response_model = get_object_or_404(ResponseModel, id=response_model_id)
    
    validation_result = PydanticModelBuilder.validate_model_configuration(response_model)
    
    pydantic_code = None
    code_validation_result = None
    
    if validation_result['valid']:
        try:
            pydantic_code = PydanticModelBuilder.build_pydantic_model(response_model)

            # Validate the generated code
            code_validation_result = PydanticModelBuilder.validate_generated_code(pydantic_code)

            if not code_validation_result['valid']:
                messages.warning(request, "Generated code has validation issues. Please review.")
                for error in code_validation_result['errors']:
                    log.error(f"Code validation error: {error}")
            else:
                # Also build the live model — the same class the extractor will use
                PydanticModelBuilder.build_extraction_model(response_model)
                messages.success(request, "✓ Generated Pydantic model is valid and ready to use!")

        except Exception as e:
            log.error(f"Error building Pydantic model: {e}")
            validation_result['valid'] = False
            validation_result.setdefault('errors', []).append(str(e))
            messages.error(request, f"Error generating Pydantic model: {str(e)}")
    
    if request.method == 'POST':
        if validation_result['valid']:
            response_model.is_complete = True
            response_model.save(update_fields=['is_complete'])

            messages.success(request, f"Response model '{response_model.name}' configured successfully!")
            return redirect('extractor:wizard_complete', response_model_id=response_model.id)
        else:
            messages.error(request, "Cannot complete wizard. Please fix validation errors.")
    
    model_tables = ResponseModelTable.objects.filter(
        response_model=response_model
    ).select_related('database_table__clientapp_content_type')
    
    tables_summary = []
    for model_table in model_tables:
        fields = ResponseModelTableField.objects.filter(
            response_model_table=model_table
        ).select_related('field').order_by('order')
        
        tables_summary.append({
            'table': model_table,
            'fields': fields,
        })
    
    context = {
        'response_model': response_model,
        'tables_summary': tables_summary,
        'validation_result': validation_result,
        'code_validation_result': code_validation_result,
        'pydantic_code': pydantic_code,
    }
    
    return render(request, 'extractor/wizard_step4.html', context)


@login_required
@permission_required('extractor.view_responsemodel', raise_exception=True)
def wizard_complete(request, response_model_id):
    """
    Completion page showing the configured response model.
    Requires permission to view ResponseModel.
    """
    response_model = get_object_or_404(ResponseModel, id=response_model_id)
    
    pydantic_code = PydanticModelBuilder.build_pydantic_model(response_model)
    
    context = {
        'response_model': response_model,
        'pydantic_code': pydantic_code,
    }
    
    return render(request, 'extractor/wizard_complete.html', context)


@login_required
@permission_required('extractor.view_responsemodel', raise_exception=True)
def response_model_list(request):
    """
    List all configured response models.
    """
    response_models = ResponseModel.objects.filter(is_complete=True).select_related('client')

    context = {
        'response_models': response_models,
    }

    return render(request, 'extractor/response_model_list.html', context)


@login_required
@permission_required('extractor.view_responsemodel', raise_exception=True)
def response_model_detail(request, response_model_id):
    """
    View details of a specific response model.
    Requires permission to view ResponseModel.
    """
    response_model = get_object_or_404(ResponseModel, id=response_model_id)
    
    pydantic_code = PydanticModelBuilder.build_pydantic_model(response_model)
    
    model_tables = ResponseModelTable.objects.filter(
        response_model=response_model
    ).select_related('database_table__clientapp_content_type')
    
    tables_summary = []
    for model_table in model_tables:
        fields = ResponseModelTableField.objects.filter(
            response_model_table=model_table
        ).select_related('field').order_by('order')
        
        tables_summary.append({
            'table': model_table,
            'fields': fields,
        })
    
    # Get instructor messages
    instructor_messages = InstructorMessage.objects.filter(
        response_model=response_model
    ).order_by('created_at')
    
    context = {
        'response_model': response_model,
        'tables_summary': tables_summary,
        'pydantic_code': pydantic_code,
        'instructor_messages': instructor_messages,
    }
    
    return render(request, 'extractor/response_model_detail.html', context)


@login_required
@permission_required('extractor.view_databasefield', raise_exception=True)
@require_http_methods(["GET"])
def api_get_table_fields(request, table_id):
    """
    API endpoint to get fields for a specific table (AJAX).
    Requires permission to view DatabaseField.
    """
    try:
        database_table = DatabaseTable.objects.get(id=table_id)
        fields = [f for f in DatabaseField.objects.filter(
            clientapp_database_table=database_table) if f.is_extractable()]
        
        fields_data = [{
            'id': field.id,
            'name': field.clientapp_field_name,
            'type': field.get_field_type_display(),
            'is_lookup': field.lookup_field,
            'lookup_table': field.lookup_content_type.model if field.lookup_content_type else None,
        } for field in fields]
        
        return JsonResponse({
            'success': True,
            'fields': fields_data
        })
    except DatabaseTable.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Table not found'
        }, status=404)


@login_required
@permission_required('extractor.view_clientconfiguration', raise_exception=True)
def client_configuration_list(request):
    """
    List all LLM client configurations.
    Requires permission to view ClientConfiguration.
    """
    configurations = ClientConfiguration.objects.all().order_by('-created_at')
    
    context = {
        'configurations': configurations,
    }
    
    return render(request, 'extractor/client_configuration_list.html', context)


@login_required
@permission_required('extractor.view_clientconfiguration', raise_exception=True)
def client_configuration_detail(request, config_id):
    """
    View details of a specific client configuration.
    Requires permission to view ClientConfiguration.
    """
    configuration = get_object_or_404(ClientConfiguration, id=config_id)
    
    response_models = ResponseModel.objects.filter(client=configuration)
    
    context = {
        'configuration': configuration,
        'response_models': response_models,
    }
    
    return render(request, 'extractor/client_configuration_detail.html', context)


@login_required
@permission_required('extractor.add_clientconfiguration', raise_exception=True)
def client_configuration_create(request):
    """
    Create a new LLM client configuration.
    Requires permission to add ClientConfiguration.
    """
    if request.method == 'POST':
        llm_model_name = request.POST.get('llm_model_name')
        model_provider = request.POST.get('model_provider')
        model_api_key = request.POST.get('model_api_key')
        model_base_url = request.POST.get('model_base_url')
        model_api_key_expires = request.POST.get('model_api_key_expires') == 'on'
        model_api_key_validity = request.POST.get('model_api_key_validity') or None
        model_api_refresh_key = request.POST.get('model_api_refresh_key') or None
        try:
            request_timeout = int(request.POST.get('request_timeout') or 60)
            context_size = int(request.POST.get('context_size') or 8192)
        except ValueError:
            messages.error(request, "Timeout and context size must be numbers.")
            return redirect('extractor:client_configuration_create')

        if not all([llm_model_name, model_provider, model_api_key, model_base_url]):
            messages.error(request, "Please fill in all required fields.")
            return redirect('extractor:client_configuration_create')
        
        try:
            configuration = ClientConfiguration(
                llm_model_name=llm_model_name,
                model_provider=model_provider,
                model_api_key=model_api_key,
                model_base_url=model_base_url,
                model_api_key_expires=model_api_key_expires,
                model_api_key_validity=model_api_key_validity,
                model_api_refresh_key=model_api_refresh_key,
                request_timeout=request_timeout,
                context_size=context_size,
            )
            configuration.full_clean()
            configuration.save()

            messages.success(request, f"Client configuration '{llm_model_name}' created successfully!")
            return redirect('extractor:client_configuration_detail', config_id=configuration.id)

        except Exception as e:
            log.error(f"Error creating client configuration: {e}")
            messages.error(request, f"Error creating configuration: {str(e)}")
            return redirect('extractor:client_configuration_create')
    
    context = {
        'providers': [
            'OpenAI',
            'Anthropic',
            'Google',
            'Azure OpenAI',
            'Cohere',
            'Mistral',
            'Local (Ollama)',
            'Other',
        ]
    }
    
    return render(request, 'extractor/client_configuration_create.html', context)


@login_required
@permission_required('extractor.change_clientconfiguration', raise_exception=True)
def client_configuration_edit(request, config_id):
    """
    Edit an existing LLM client configuration.
    Requires permission to change ClientConfiguration.
    """
    configuration = get_object_or_404(ClientConfiguration, id=config_id)
    
    if request.method == 'POST':
        configuration.llm_model_name = request.POST.get('llm_model_name')
        configuration.model_provider = request.POST.get('model_provider')
        configuration.model_base_url = request.POST.get('model_base_url')
        configuration.model_api_key_expires = request.POST.get('model_api_key_expires') == 'on'
        configuration.model_api_key_validity = request.POST.get('model_api_key_validity') or None
        try:
            configuration.request_timeout = int(request.POST.get('request_timeout') or 60)
            configuration.context_size = int(request.POST.get('context_size') or 8192)
        except ValueError:
            messages.error(request, "Timeout and context size must be numbers.")
            return redirect('extractor:client_configuration_edit', config_id=configuration.id)

        new_api_key = request.POST.get('model_api_key')
        if new_api_key:
            configuration.model_api_key = new_api_key
        
        new_refresh_key = request.POST.get('model_api_refresh_key')
        if new_refresh_key:
            configuration.model_api_refresh_key = new_refresh_key
        
        try:
            configuration.full_clean()
            configuration.save()
            messages.success(request, f"Client configuration '{configuration.llm_model_name}' updated successfully!")
            return redirect('extractor:client_configuration_detail', config_id=configuration.id)
            
        except Exception as e:
            log.error(f"Error updating client configuration: {e}")
            messages.error(request, f"Error updating configuration: {str(e)}")
    
    context = {
        'configuration': configuration,
        'providers': [
            'OpenAI',
            'Anthropic',
            'Google',
            'Azure OpenAI',
            'Cohere',
            'Mistral',
            'Local (Ollama)',
            'Other',
        ]
    }
    
    return render(request, 'extractor/client_configuration_edit.html', context)


@login_required
@permission_required('extractor.delete_clientconfiguration', raise_exception=True)
def client_configuration_delete(request, config_id):
    """
    Delete an LLM client configuration.
    Requires permission to delete ClientConfiguration.
    """
    configuration = get_object_or_404(ClientConfiguration, id=config_id)
    
    if request.method == 'POST':
        config_name = configuration.llm_model_name
        
        response_models_count = ResponseModel.objects.filter(client=configuration).count()
        if response_models_count > 0:
            messages.error(
                request, 
                f"Cannot delete this configuration. It is used by {response_models_count} response model(s). "
                "Please delete or reassign those response models first."
            )
            return redirect('extractor:client_configuration_detail', config_id=configuration.id)
        
        configuration.delete()
        messages.success(request, f"Client configuration '{config_name}' deleted successfully!")
        return redirect('extractor:client_configuration_list')
    
    return redirect('extractor:client_configuration_detail', config_id=configuration.id)


@login_required
@permission_required('extractor.view_clientconfiguration', raise_exception=True)
@require_http_methods(["POST"])
def client_configuration_test_connection(request, config_id):
    """
    Test the API connection using the same OpenAI-compatible client path the
    extractor actually uses. Never logs headers, keys, or payloads.
    """
    configuration = get_object_or_404(ClientConfiguration, id=config_id)

    if configuration.api_key_expired():
        return JsonResponse({
            'success': False,
            'message': f"API key expired on {configuration.model_api_key_validity:%Y-%m-%d}. Update the key or validity date first.",
        }, status=400)

    try:
        from openai import OpenAI, APIConnectionError, APITimeoutError, AuthenticationError
        from datetime import datetime
        from extractor.services.url_policy import normalize_base_url

        base_url = normalize_base_url(configuration.model_base_url)
        is_local = any(h in base_url for h in ('localhost', '127.0.0.1', '::1'))

        client = OpenAI(
            base_url=base_url,
            api_key=configuration.model_api_key or 'not-needed',
            timeout=configuration.request_timeout,
            max_retries=0,
        )

        start_time = datetime.now()
        response = client.chat.completions.create(
            model=configuration.llm_model_name,
            messages=[{'role': 'user', 'content': 'Reply with the word "ok".'}],
            max_tokens=5,
        )
        response_time = (datetime.now() - start_time).total_seconds()

        return JsonResponse({
            'success': True,
            'message': 'API connection successful!',
            'details': {
                'status_code': 200,
                'response_time': f'{response_time:.2f}s',
                'model': configuration.llm_model_name,
                'provider': configuration.model_provider,
            }
        })

    except AuthenticationError:
        return JsonResponse({
            'success': False,
            'message': 'Authentication failed - check the API key',
            'details': {'endpoint': base_url},
        }, status=401)

    except APITimeoutError:
        hints = []
        if is_local:
            hints.append('Is the local server running? Check with: ollama list')
            hints.append('Verify the port number is correct')
        else:
            hints.append('Check your internet connection')
            hints.append('Verify the API endpoint URL is correct')
        return JsonResponse({
            'success': False,
            'message': f'Connection timeout - no response within {configuration.request_timeout}s',
            'details': {'error': 'Request timeout', 'endpoint': base_url, 'troubleshooting': hints},
        }, status=408)

    except APIConnectionError as e:
        hints = []
        if is_local:
            hints.append('The local server may not be running (e.g. ollama serve)')
            hints.append('Check the port is correct (Ollama default: 11434)')
        else:
            hints.append('Check your internet connection')
            hints.append('Verify the base URL is correct')
            hints.append('Check if a firewall is blocking the connection')
        return JsonResponse({
            'success': False,
            'message': 'Connection failed - could not reach API endpoint',
            'details': {'error': str(e.__cause__ or e)[:300], 'endpoint': base_url, 'troubleshooting': hints},
        }, status=503)

    except Exception as e:
        log.error(f"API connection test failed for config {config_id}: {type(e).__name__}: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Test failed: {type(e).__name__}: {str(e)[:200]}',
            'details': {'error': str(e)[:300]},
        }, status=500)


# File Upload Views

@login_required
@permission_required('extractor.view_fileupload', raise_exception=True)
def file_upload_list(request):
    """
    List all uploaded files with their processing status.
    """
    files = FileUpload.objects.all().select_related('patient_id').order_by('-created_at')
    
    context = {
        'files': files,
    }
    
    return render(request, 'extractor/file_upload_list.html', context)


def _validate_upload_content(uploaded_file, ext):
    """
    Magic-byte sanity check on the uploaded content. Returns an error string
    or None. Defence in depth on top of the extension validator.
    """
    head = uploaded_file.read(512)
    uploaded_file.seek(0)
    if ext == '.pdf' and not head.startswith(b'%PDF'):
        return "File content is not a valid PDF."
    if ext == '.xlsx' and not head.startswith(b'PK\x03\x04'):
        return "File content is not a valid Excel workbook."
    if ext == '.csv' and b'\x00' in head:
        return "File content does not look like a CSV (binary data found)."
    return None


@login_required
@permission_required('extractor.add_fileupload', raise_exception=True)
def file_upload_create(request):
    """
    Upload a new file.
    """
    if request.method == 'POST':
        file_upload = None
        try:
            uploaded_file = request.FILES.get('file')
            patient_id = request.POST.get('patient_id')

            if not uploaded_file:
                messages.error(request, "No file selected.")
                return redirect('extractor:file_upload_create')

            # Validate before anything touches storage
            ext = os.path.splitext(uploaded_file.name)[1].lower()
            file_type = FileUpload.EXTENSION_TO_FILE_TYPE.get(ext)
            if not file_type:
                messages.error(request, f"Unsupported file type '{ext}'. Allowed: PDF, CSV, XLSX.")
                return redirect('extractor:file_upload_create')

            max_bytes = getattr(settings, 'EXTRACTOR_MAX_UPLOAD_MB', 50) * 1024 * 1024
            if uploaded_file.size > max_bytes:
                messages.error(request, f"File exceeds maximum size of {max_bytes // (1024*1024)} MB.")
                return redirect('extractor:file_upload_create')

            content_error = _validate_upload_content(uploaded_file, ext)
            if content_error:
                messages.error(request, content_error)
                return redirect('extractor:file_upload_create')

            # Create FileUpload instance and run model validation before saving
            file_upload = FileUpload(
                file=uploaded_file,
                original_filename=uploaded_file.name,
                file_type=file_type,
            )

            if patient_id:
                from client_app.models import Patient
                try:
                    patient = Patient.objects.get(patient_id=patient_id)
                    file_upload.patient_id = patient
                except Patient.DoesNotExist:
                    messages.warning(request, f"Patient {patient_id} not found. File uploaded without patient link.")

            file_upload.full_clean()
            file_upload.save()

            messages.success(request, "File uploaded successfully!")
            return redirect('extractor:file_upload_detail', file_id=file_upload.id)

        except ValidationError as e:
            messages.error(request, f"Upload failed validation: {e}")
            return redirect('extractor:file_upload_create')
        except Exception as e:
            log.error(f"File upload error: {e}")
            # If a row/file was persisted before the failure, remove it
            if file_upload and file_upload.pk:
                file_upload.delete()
            messages.error(request, f"Upload failed: {str(e)}")
            return redirect('extractor:file_upload_create')

    # Get list of patients for dropdown
    from client_app.models import Patient
    patients = Patient.objects.all().order_by('patient_id')
    
    context = {
        'patients': patients,
    }
    
    return render(request, 'extractor/file_upload_create.html', context)


@login_required
@permission_required('extractor.view_fileupload', raise_exception=True)
def file_upload_detail(request, file_id):
    """
    View details of an uploaded file and its processed versions.
    """
    file_upload = get_object_or_404(FileUpload, id=file_id)
    processed_files = ProcessedText.objects.filter(file_upload=file_upload).order_by('-created_at')

    # Dependent records that deletion will cascade through — shown in the modal
    dependent_jobs = ExtractionJob.objects.filter(processed_file__file_upload=file_upload)
    dependent_results = ExtractionResult.objects.filter(extraction_job__in=dependent_jobs)

    context = {
        'file_upload': file_upload,
        'processed_files': processed_files,
        'dependent_jobs_count': dependent_jobs.count(),
        'dependent_results_count': dependent_results.count(),
    }

    return render(request, 'extractor/file_upload_detail.html', context)


@login_required
@permission_required('extractor.change_fileupload', raise_exception=True)
@require_http_methods(["POST"])
def file_upload_process(request, file_id):
    """
    Process an uploaded file (convert PDF to markdown, Excel to CSV, etc.)
    """
    file_upload = get_object_or_404(FileUpload, id=file_id)
    
    try:
        result = FileProcessorService.process_file(file_upload, user=request.user)

        if result['success']:
            messages.success(request, result['message'])
            if result['processed_files']:
                count = len(result['processed_files'])
                messages.info(request, f"{count} file(s) generated and ready for extraction.")
        elif result.get('processed_files'):
            # Partial conversion: some output exists but not everything succeeded
            messages.warning(request, result['message'] or "Processing completed with failures.")
            for error in result['errors']:
                messages.error(request, error)
        else:
            messages.error(request, result['message'] or "Processing failed.")
            for error in result['errors']:
                messages.error(request, error)

        for warning in result.get('warnings', []):
            messages.warning(request, warning)
        
    except Exception as e:
        log.error(f"File processing error: {e}")
        messages.error(request, f"Processing failed: {str(e)}")
    
    return redirect('extractor:file_upload_detail', file_id=file_upload.id)


@login_required
@permission_required('extractor.delete_fileupload', raise_exception=True)
def file_upload_delete(request, file_id):
    """
    Delete an uploaded file and all its processed versions.
    """
    file_upload = get_object_or_404(FileUpload, id=file_id)
    
    if request.method == 'POST':
        filename = file_upload.original_filename or os.path.basename(file_upload.file.name)

        # Delete processed files; abort rather than orphan DB rows or files
        if not FileProcessorService.delete_processed_files(file_upload):
            messages.error(request, "Could not delete processed files; upload was not deleted.")
            return redirect('extractor:file_upload_detail', file_id=file_upload.id)

        # Delete the upload
        file_upload.delete()

        messages.success(request, f"File '{filename}' and all processed versions deleted successfully!")
        return redirect('extractor:file_upload_list')

    return redirect('extractor:file_upload_detail', file_id=file_upload.id)


@login_required
@permission_required('extractor.view_processedtext', raise_exception=True)
def processed_text_view(request, processed_id):
    """
    View the content of a processed text file.
    """
    processed_text = get_object_or_404(ProcessedText, id=processed_id)
    
    content = FileProcessorService.get_processed_content(processed_text)
    
    context = {
        'processed_text': processed_text,
        'content': content,
    }
    
    return render(request, 'extractor/processed_text_view.html', context)


# Extraction Views

@login_required
@permission_required('extractor.change_processedtext', raise_exception=True)
@require_http_methods(["POST"])
def processed_text_ocr(request, processed_text_id):
    """
    Dispatch OCR for a scanned/image-only PDF (manual action). Creates a
    BackgroundTask and returns to the referring page.
    """
    processed_text = get_object_or_404(ProcessedText, id=processed_text_id)
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'extractor:extraction_dashboard'

    if processed_text.file_upload.file_type != FileTypeChoices.PDF:
        messages.error(request, "OCR is only supported for PDF uploads.")
        return redirect(next_url)

    if processed_text.ocr_applied:
        messages.info(request, "This version was already produced by OCR.")
        return redirect(next_url)

    running = BackgroundTask.objects.filter(
        task_name__startswith=f"OCR for processed file {processed_text_id}",
        status__in=['pending', 'running']
    ).exists()
    if running:
        messages.warning(request, "OCR is already in progress for this file.")
        return redirect(next_url)

    task = BackgroundTask.objects.create(
        task_id=f"ocr-{processed_text_id}-{int(timezone.now().timestamp())}",
        task_name=f"OCR for processed file {processed_text_id}",
        status='pending',
        user=request.user
    )
    from extractor.tasks import ocr_processed_text_task
    ocr_processed_text_task.delay(task.task_id, processed_text_id, request.user.id)

    messages.success(request, f"OCR started for '{processed_text.file_upload.original_filename}'.")
    return redirect(next_url)


@login_required
@permission_required('extractor.view_processedtext', raise_exception=True)
def extraction_dashboard(request):
    """
    Patient-centric dashboard: one row per patient with processed files,
    job-status summary, search/filters, and pagination.
    """
    from client_app.models import Patient
    from django.db.models import Q

    patients = (Patient.objects
                .filter(fileupload__isnull=False)
                .annotate(
                    file_count=Count('fileupload', distinct=True),
                    processed_count=Count('fileupload__processedtext', distinct=True),
                    jobs_completed=Count(
                        'fileupload__processedtext__extractionjob', distinct=True,
                        filter=Q(fileupload__processedtext__extractionjob__extraction_status='completed')),
                    jobs_failed=Count(
                        'fileupload__processedtext__extractionjob', distinct=True,
                        filter=Q(fileupload__processedtext__extractionjob__extraction_status='failed')),
                    jobs_active=Count(
                        'fileupload__processedtext__extractionjob', distinct=True,
                        filter=Q(fileupload__processedtext__extractionjob__extraction_status__in=['pending', 'processing'])),
                )
                .order_by('patient_id')
                .distinct())

    # Filters
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    file_type = request.GET.get('file_type', '').strip()
    date_from = request.GET.get('from', '').strip()
    date_to = request.GET.get('to', '').strip()

    if q:
        patients = patients.filter(patient_id__icontains=q)
    if status == 'none':
        patients = patients.filter(fileupload__processedtext__extractionjob__isnull=True)
    elif status:
        patients = patients.filter(
            fileupload__processedtext__extractionjob__extraction_status=status)
    if file_type:
        patients = patients.filter(fileupload__file_type=file_type)
    if date_from:
        patients = patients.filter(fileupload__created_at__date__gte=date_from)
    if date_to:
        patients = patients.filter(fileupload__created_at__date__lte=date_to)

    paginator = Paginator(patients, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'paginator': paginator,
        'response_models': ResponseModel.objects.filter(is_complete=True).select_related('client'),
        'filters': {'q': q, 'status': status, 'file_type': file_type,
                    'from': date_from, 'to': date_to},
        'status_choices': ExtractionStatusChoices.choices,
        'file_type_choices': FileTypeChoices.choices,
        'total_patients': paginator.count,
    }
    return render(request, 'extractor/extraction_dashboard.html', context)


@login_required
@permission_required('extractor.view_extractionresult', raise_exception=True)
def patient_data(request, patient_pk):
    """
    Dedicated per-patient page: files and job history. Review, edit, and
    write-back of extraction results live on the job detail page — each
    job links there.
    """
    from client_app.models import Patient

    patient = get_object_or_404(Patient, pk=patient_pk)

    processed_files = (ProcessedText.objects
                       .select_related('file_upload')
                       .filter(file_upload__patient_id=patient,
                               file_upload__processing_status='completed')
                       .order_by('file_upload_id', '-version'))

    file_rows = []
    for pf in processed_files:
        latest_job = (ExtractionJob.objects
                      .filter(processed_file=pf)
                      .order_by('-created_at').first())
        file_rows.append({'processed_file': pf, 'latest_job': latest_job})

    jobs = (ExtractionJob.objects
            .filter(processed_file__file_upload__patient_id=patient)
            .select_related('response_model__client', 'processed_file__file_upload')
            .order_by('-created_at')[:50])

    context = {
        'patient': patient,
        'file_rows': file_rows,
        'jobs': jobs,
        'response_models': ResponseModel.objects.filter(is_complete=True).select_related('client'),
    }
    return render(request, 'extractor/patient_data.html', context)


@login_required
@permission_required('extractor.add_extractionjob', raise_exception=True)
@require_http_methods(["POST"])
def extraction_start(request):
    """
    Start extraction for selected processed files.
    """
    try:
        processed_file_ids = request.POST.getlist('processed_files')
        response_model_id = request.POST.get('response_model')
        back = request.POST.get('next') or 'extractor:extraction_dashboard'
        
        if not processed_file_ids or not response_model_id:
            messages.error(request, "Please select files and a response model.")
            return redirect(back)
        
        response_model = get_object_or_404(ResponseModel, id=response_model_id)
        processed_files = ProcessedText.objects.filter(id__in=processed_file_ids)

        if not processed_files.exists():
            messages.error(request, "No valid files selected.")
            return redirect(back)

        # Readiness check: refuse to run an unbuildable extraction model
        readiness = PydanticModelBuilder.validate_model_configuration(response_model)
        if not readiness['valid']:
            for error in readiness['errors']:
                messages.error(request, error)
            return redirect(back)
        try:
            PydanticModelBuilder.build_extraction_model(response_model)
        except Exception as e:
            messages.error(request, f"Extraction model could not be built: {e}")
            return redirect(back)

        # Dispatch one Celery task per file; existing live jobs are reused
        # so double-submits don't double-charge.
        queued = 0
        reused = 0
        single_job = None
        for processed_file in processed_files:
            job, created = InstructorExtractionService.get_or_create_job(
                processed_file, response_model, request.user
            )
            single_job = job
            if created:
                advance_extraction_job.delay(job.id)
                queued += 1
            else:
                reused += 1

        messages.success(
            request,
            f"Extraction queued: {queued} job(s) dispatched"
            + (f", {reused} already running" if reused else "")
            + f" for {len(processed_files)} file(s)."
        )

        # One file → land on the job detail page where the staged pipeline
        # prompts wait for approval
        if processed_files.count() == 1 and single_job is not None:
            return redirect('extractor:extraction_job_detail', job_id=single_job.id)
        return redirect(back)
        
    except Exception as e:
        log.error(f"Extraction start failed: {e}")
        messages.error(request, f"Extraction failed: {str(e)}")
        return redirect(back)


@login_required
@permission_required('extractor.view_extractionjob', raise_exception=True)
def extraction_results_list(request):
    """
    List all extraction jobs with their results.
    """
    extraction_jobs = ExtractionJob.objects.select_related(
        'response_model',
        'processed_file__file_upload',
        'extracted_by'
    ).annotate(
        result_count=Count('extractionresult')
    ).order_by('-created_at')

    paginator = Paginator(extraction_jobs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    jobs_with_stats = [
        {'job': job, 'result_count': job.result_count}
        for job in page_obj.object_list
    ]

    context = {
        'jobs_with_stats': jobs_with_stats,
        'page_obj': page_obj,
    }

    return render(request, 'extractor/extraction_results_list.html', context)


@login_required
@permission_required('extractor.view_extractionjob', raise_exception=True)
def extraction_job_detail(request, job_id):
    """
    View details of a specific extraction job and its results.
    """
    extraction_job = get_object_or_404(
        ExtractionJob.objects.select_related(
            'response_model',
            'processed_file__file_upload__patient_id',
            'extracted_by'
        ),
        id=job_id
    )
    
    # Get all extraction results for this job
    extraction_results = ExtractionResult.objects.filter(
        extraction_job=extraction_job
    ).select_related(
        'database_field__clientapp_database_table',
        'record',
        'verified_by'
    ).order_by(
        'database_field__clientapp_database_table',
        'record__record_index',
        'database_field__clientapp_field_name'
    )

    # Record grid — the canonical review/edit/write-back surface, shared
    # with the patient page's staging view builder
    from extractor.services.patient_data import build_job_data_tree
    data_tree = build_job_data_tree(extraction_job)

    # Get processed file content
    content = FileProcessorService.get_processed_content(extraction_job.processed_file)

    # Stage trace → display entries; the prompt entry matching the awaiting
    # status is the one parked for approval
    awaiting_stage = {
        ExtractionStatusChoices.AWAITING_MINING: 'mining',
        ExtractionStatusChoices.AWAITING_EXTRACTION: 'extraction',
    }.get(extraction_job.extraction_status)
    trace = extraction_job.stage_trace or []
    pending_idx = max(
        (i for i, e in enumerate(trace)
         if e.get('kind') == 'prompt' and e.get('stage') == awaiting_stage),
        default=None)
    stage_entries = []
    for i, entry in enumerate(trace):
        stage_entries.append({
            'number': {'mining': 1, 'extraction': 2}.get(entry.get('stage'), '?'),
            'label': {'mining': 'Lookup mining', 'extraction': 'Extraction'}.get(
                entry.get('stage'), str(entry.get('stage', '')).title()),
            'kind': entry.get('kind'),
            'note': entry.get('note'),
            'messages': entry.get('messages') or [],
            'result_json': json.dumps(
                {k: v for k, v in entry.items()
                 if k not in ('stage', 'kind', 'at', 'messages', 'note')},
                indent=2, default=str) if entry.get('kind') == 'result' else None,
            'pending': awaiting_stage is not None and i == pending_idx,
        })

    context = {
        'extraction_job': extraction_job,
        'extraction_results': extraction_results,
        'data_tree': data_tree,
        'processed_content': content,
        'total_results': extraction_results.count(),
        'stage_entries': stage_entries,
        'stage_running': extraction_job.extraction_status in (
            ExtractionStatusChoices.PENDING, ExtractionStatusChoices.PROCESSING),
    }

    return render(request, 'extractor/extraction_job_detail.html', context)


@login_required
@permission_required('extractor.add_extractionjob', raise_exception=True)
@require_http_methods(["POST"])
def extraction_job_continue(request, job_id):
    """
    Approve the pending stage of a gated extraction job — dispatches the
    Celery task that sends the shown prompt to the LLM. 'cancel' abandons
    the job so the file can be re-extracted later.
    """
    extraction_job = get_object_or_404(ExtractionJob, id=job_id)
    back = redirect('extractor:extraction_job_detail', job_id=job_id)

    awaiting = (
        ExtractionStatusChoices.AWAITING_MINING,
        ExtractionStatusChoices.AWAITING_EXTRACTION,
    )
    if extraction_job.extraction_status not in awaiting:
        messages.error(request, "This job is not waiting for approval.")
        return back

    if request.POST.get('action') == 'cancel':
        extraction_job.extraction_status = ExtractionStatusChoices.SKIPPED
        extraction_job.extraction_end_datetime = timezone.now()
        extraction_job.save()
        messages.info(request, f"Extraction job #{job_id} cancelled.")
        return back

    advance_extraction_job.delay(extraction_job.id)
    messages.success(request, "Stage approved — dispatched to the worker.")
    return back


@login_required
@permission_required('extractor.change_extractionresult', raise_exception=True)
@require_http_methods(["POST"])
def extraction_result_update(request, result_id):
    """
    Update an extraction result (edit data, change accuracy).
    """
    extraction_result = get_object_or_404(ExtractionResult, id=result_id)

    action = request.POST.get('action', 'accept')
    data_accuracy = request.POST.get('data_accuracy')

    effective_value = extraction_result.edited_data if extraction_result.data_edited else extraction_result.extracted_data

    history_entry = {
        'action': action,
        'old': effective_value,
        'user': request.user.username,
        'at': timezone.now().isoformat(),
    }

    # Where to send the user back — job detail by default, patient page when posted from there
    back_url = request.POST.get('next') or None

    def _back():
        if back_url:
            return redirect(back_url)
        return redirect('extractor:extraction_job_detail', job_id=extraction_result.extraction_job.id)

    if action == 'correct':
        db_field = extraction_result.database_field
        if db_field.lookup_field:
            # Lookup fields are corrected via a dropdown of real options —
            # never free text. The posted code is resolved server-side.
            code = request.POST.get('edited_code')
            if not code:
                messages.error(request, "Correction requires selecting a lookup option.")
                return _back()
            from extractor.services.semantic_search import build_lookup_label
            model_class = db_field.lookup_content_type.model_class() if db_field.lookup_content_type else None
            obj = None
            if model_class:
                try:
                    obj = model_class.objects.get(**{db_field.lookup_table_pk_field_name or 'pk': code})
                except model_class.DoesNotExist:
                    obj = None
            if obj is None:
                messages.error(request, f"'{code}' is not a valid option for this field.")
                return _back()
            new_value = json.dumps({'label': build_lookup_label(obj, db_field), 'code': code})
        else:
            new_value = request.POST.get('edited_data')
            if not new_value or not new_value.strip():
                messages.error(request, "Correction requires a value.")
                return _back()
        # Compare against the *effective* value so re-submitting the original
        # clears the correction instead of silently keeping the old edit.
        if new_value == extraction_result.extracted_data:
            extraction_result.edited_data = None
            extraction_result.data_edited = False
        else:
            extraction_result.edited_data = new_value
            extraction_result.data_edited = True
        history_entry['new'] = new_value

    elif action == 'clear':
        extraction_result.edited_data = ''
        extraction_result.data_edited = True
        history_entry['new'] = ''

    elif action == 'revert':
        extraction_result.edited_data = None
        extraction_result.data_edited = False
        history_entry['new'] = extraction_result.extracted_data

    elif action in ('accept', 'reject'):
        pass  # accuracy set below

    else:
        messages.error(request, f"Unknown action '{action}'.")
        return _back()

    if action == 'accept' and not data_accuracy:
        data_accuracy = 'accurate'
    if action == 'reject':
        data_accuracy = 'inaccurate'

    if data_accuracy:
        if data_accuracy not in DataAccuracyChoices.values:
            messages.error(request, f"Invalid accuracy value '{data_accuracy}'.")
            return _back()
        extraction_result.data_accuracy = data_accuracy

    extraction_result.revision_history = (extraction_result.revision_history or []) + [history_entry]
    extraction_result.verified_by = request.user
    extraction_result.verification_date_time = timezone.now()
    extraction_result.save()

    messages.success(request, "Extraction result updated successfully.")
    return _back()


@login_required
@permission_required('extractor.add_recordcreation', raise_exception=True)
@require_http_methods(["POST"])
def extraction_record_create(request, extracted_record_id):
    """
    Write one extracted staging record into its client_app table
    (manual, create-only). Parent records must already exist.
    """
    from extractor.models import ExtractedRecord
    from extractor.services.record_writer import (
        create_record_for_extracted_record, RecordWriteError,
        find_duplicate_candidates, _effective_map)
    from extractor.services.patient_data import _grid_columns, _format_existing_cell, _cell_value

    record = get_object_or_404(
        ExtractedRecord.objects.select_related(
            'database_table__clientapp_content_type',
            'extraction_job__processed_file__file_upload'),
        id=extracted_record_id)
    patient = record.extraction_job.processed_file.file_upload.patient_id

    back_url = request.POST.get('next')
    if not back_url and patient:
        back_url = reverse('extractor:patient_data', kwargs={'patient_pk': patient.pk})

    try:
        # Duplicate check first — a match renders a confirm page instead of creating
        if request.POST.get('force') != '1':
            candidates = find_duplicate_candidates(record.database_table, record)
            if candidates:
                columns = _grid_columns(record.database_table)
                _, results = _effective_map(record)
                extracted_rows = [_cell_value(results.get(col.id)) if results.get(col.id)
                                  else {'text': '—', 'kind': 'not_found'}
                                  for col in columns]
                existing_rows = [
                    {'pk': c['pk'], 'matched_on': c['matched_on'],
                     'cells': [_format_existing_cell(c['row'], col) for col in columns]}
                    for c in candidates
                ]
                return render(request, 'extractor/confirm_duplicate_create.html', {
                    'record': record,
                    'table': record.database_table,
                    'model_name': record.database_table.clientapp_content_type.model,
                    'columns': columns,
                    'extracted_rows': extracted_rows,
                    'existing_rows': existing_rows,
                    'back_url': back_url,
                    'patient': patient,
                })

        creation, created = create_record_for_extracted_record(record, request.user)
        if created:
            messages.success(
                request,
                f"Created {record.database_table.clientapp_content_type.model} "
                f"record #{creation.created_record_pk}.")
        else:
            messages.info(
                request,
                f"Record already created as #{creation.created_record_pk}.")
    except RecordWriteError as e:
        messages.error(request, f"Cannot create record: {e}")
    except Exception as e:
        log.error(f"Record write-back failed for extracted record {extracted_record_id}: {e}",
                  exc_info=True)
        messages.error(request, "Record creation failed unexpectedly; check the logs.")

    return redirect(back_url or 'extractor:extraction_dashboard')


# Instructor Message Views

@login_required
@permission_required('extractor.view_instructormessage', raise_exception=True)
def instructor_message_list(request):
    """
    List all instructor messages (prompts) grouped by response model.
    """
    response_models = ResponseModel.objects.filter(
        is_complete=True
    ).select_related('client').prefetch_related('instructormessage_set')

    context = {
        'response_models': response_models,
    }

    return render(request, 'extractor/instructor_message_list.html', context)


@login_required
@permission_required('extractor.add_instructormessage', raise_exception=True)
def instructor_message_create(request, response_model_id):
    """
    Create a new instructor message (prompt) for a response model.
    """
    response_model = get_object_or_404(ResponseModel, id=response_model_id)
    
    if request.method == 'POST':
        role = request.POST.get('role', InstructorRole.SYSTEM)
        prompt_text = request.POST.get('prompt')
        order = request.POST.get('order') or 0

        if role not in InstructorRole.values:
            messages.error(request, f"Invalid role '{role}'.")
            return redirect('extractor:instructor_message_create', response_model_id=response_model_id)

        if not prompt_text:
            messages.error(request, "Prompt text is required.")
            return redirect('extractor:instructor_message_create', response_model_id=response_model_id)

        try:
            # Store prompt as JSON
            InstructorMessage.objects.create(
                response_model=response_model,
                role=role,
                order=int(order),
                prompt={'content': str(prompt_text)}
            )
            
            messages.success(request, "Instructor message created successfully!")
            return redirect('extractor:response_model_detail', response_model_id=response_model_id)
            
        except Exception as e:
            log.error(f"Error creating instructor message: {e}")
            messages.error(request, f"Error creating message: {str(e)}")
    
    context = {
        'response_model': response_model,
        'roles': InstructorRole.choices,
    }
    
    return render(request, 'extractor/instructor_message_form.html', context)


@login_required
@permission_required('extractor.change_instructormessage', raise_exception=True)
def instructor_message_edit(request, message_id):
    """
    Edit an existing instructor message.
    """
    instructor_message = get_object_or_404(InstructorMessage, id=message_id)
    
    if request.method == 'POST':
        role = request.POST.get('role', InstructorRole.SYSTEM)
        prompt_text = request.POST.get('prompt')
        order = request.POST.get('order') or instructor_message.order

        if role not in InstructorRole.values:
            messages.error(request, f"Invalid role '{role}'.")
            return redirect('extractor:instructor_message_edit', message_id=message_id)

        if not prompt_text:
            messages.error(request, "Prompt text is required.")
            return redirect('extractor:instructor_message_edit', message_id=message_id)

        try:
            instructor_message.role = role
            instructor_message.order = int(order)
            instructor_message.prompt = {'content': str(prompt_text)}
            instructor_message.save()
            
            messages.success(request, "Instructor message updated successfully!")
            return redirect('extractor:response_model_detail', response_model_id=instructor_message.response_model.id)
            
        except Exception as e:
            log.error(f"Error updating instructor message: {e}")
            messages.error(request, f"Error updating message: {str(e)}")
    
    # Extract prompt text from JSON
    prompt_text = ''
    if isinstance(instructor_message.prompt, dict):
        prompt_text = instructor_message.prompt.get('content', str(instructor_message.prompt))
    else:
        prompt_text = str(instructor_message.prompt)
    
    context = {
        'instructor_message': instructor_message,
        'response_model': instructor_message.response_model,
        'roles': InstructorRole.choices,
        'prompt_text': prompt_text,
    }
    
    return render(request, 'extractor/instructor_message_form.html', context)


@login_required
@permission_required('extractor.delete_instructormessage', raise_exception=True)
@require_http_methods(["POST"])
def instructor_message_delete(request, message_id):
    """
    Delete an instructor message.
    """
    instructor_message = get_object_or_404(InstructorMessage, id=message_id)
    response_model_id = instructor_message.response_model.id
    
    instructor_message.delete()
    messages.success(request, "Instructor message deleted successfully!")

    next_url = request.POST.get('next')
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
    return redirect('extractor:response_model_detail', response_model_id=response_model_id)


# Import semantic search views
from extractor.views_semantic_search import (
    semantic_search_settings,
    embedding_config_create,
    embedding_config_edit,
    embedding_config_delete,
    embedding_config_activate,
    compute_embeddings,
    get_embedding_progress,
)

import os
from django.shortcuts import render, redirect, get_object_or_404
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
    InstructorMessage, InstructorRole, EmbeddingConfiguration, LookupEmbedding
)
from extractor.services.schema_discovery import SchemaDiscoveryService
from extractor.services.pydantic_builder import PydanticModelBuilder
from extractor.services.file_processor import FileProcessorService
from extractor.services.instructor_extractor import InstructorExtractionService
from extractor.tasks import run_extraction_job
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
        selected_table_ids = request.POST.getlist('tables')

        if not selected_table_ids:
            messages.error(request, "Please select at least one table.")
            return redirect('extractor:wizard_step2', response_model_id=response_model.id)

        with transaction.atomic():
            ResponseModelTable.objects.filter(response_model=response_model).delete()

            for table_id in selected_table_ids:
                database_table = get_object_or_404(DatabaseTable, id=table_id)
                ResponseModelTable.objects.create(
                    response_model=response_model,
                    database_table=database_table
                )

        messages.success(request, f"{len(selected_table_ids)} table(s) selected.")
        return redirect('extractor:wizard_step3', response_model_id=response_model.id)
    
    tables_structure = SchemaDiscoveryService.get_hierarchical_table_structure()
    
    selected_tables = ResponseModelTable.objects.filter(
        response_model=response_model
    ).values_list('database_table_id', flat=True)
    
    context = {
        'response_model': response_model,
        'tables': tables_structure,
        'selected_tables': list(selected_tables),
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
        fields = DatabaseField.objects.filter(
            clientapp_database_table=model_table.database_table,
            is_active=True,
        )
        
        selected_fields = ResponseModelTableField.objects.filter(
            response_model_table=model_table
        ).values_list('field_id', flat=True)
        
        tables_with_fields.append({
            'model_table': model_table,
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
        fields = DatabaseField.objects.filter(clientapp_database_table=database_table)
        
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
    Test the API connection for a client configuration.
    Requires permission to view ClientConfiguration.
    """
    configuration = get_object_or_404(ClientConfiguration, id=config_id)
    
    try:
        import requests
        from datetime import datetime
        
        # Prepare headers
        headers = {
            'Authorization': f'Bearer {configuration.model_api_key}',
            'Content-Type': 'application/json'
        }
        
        # Test payload - simple completion request
        test_payload = {
            'model': configuration.llm_model_name,
            'messages': [
                {'role': 'user', 'content': 'Say "Connection successful" if you can read this.'}
            ],
            'max_tokens': 10
        }
        
        # Determine the endpoint based on provider
        provider = configuration.model_provider.lower()
        base_url = configuration.model_base_url.rstrip('/')
        
        # Add http:// if no scheme is provided
        if not base_url.startswith(('http://', 'https://')):
            base_url = f'http://{base_url}'
        
        if 'openai' in provider or 'azure' in provider:
            endpoint = f"{base_url}/v1/chat/completions"
        elif 'anthropic' in provider:
            endpoint = f"{base_url}/v1/messages"
            headers['anthropic-version'] = '2023-06-01'
            headers['x-api-key'] = configuration.model_api_key
            del headers['Authorization']
        elif 'google' in provider:
            endpoint = f"{base_url}/v1/models/{configuration.llm_model_name}:generateContent"
            headers['x-goog-api-key'] = configuration.model_api_key
            del headers['Authorization']
        elif 'ollama' in provider or 'local' in provider:
            # Ollama uses /api/chat endpoint and doesn't need auth
            endpoint = f"{base_url}/api/chat"
            test_payload = {
                'model': configuration.llm_model_name,
                'messages': [
                    {'role': 'user', 'content': 'Say "Connection successful" if you can read this.'}
                ],
                'stream': False
            }
            # Ollama doesn't use API keys
            headers = {'Content-Type': 'application/json'}
        else:
            # Generic OpenAI-compatible endpoint
            endpoint = f"{base_url}/v1/chat/completions"
        
        # Set timeout based on whether it's a local or remote API
        # Local models (especially large ones like medgemma) can take 60+ seconds for first inference
        timeout = 120 if 'localhost' in base_url or '127.0.0.1' in base_url else 30
        
        # Log the request details for debugging
        log.info(f"Testing connection to {endpoint}")
        log.info(f"Headers: {headers}")
        log.info(f"Payload: {test_payload}")
        
        # Make the request with timeout
        start_time = datetime.now()
        response = requests.post(
            endpoint,
            headers=headers,
            json=test_payload,
            timeout=timeout
        )
        end_time = datetime.now()
        response_time = (end_time - start_time).total_seconds()
        
        log.info(f"Response status: {response.status_code}")
        log.info(f"Response body: {response.text[:500]}")
        
        if response.status_code == 200:
            return JsonResponse({
                'success': True,
                'message': 'API connection successful!',
                'details': {
                    'status_code': response.status_code,
                    'response_time': f'{response_time:.2f}s',
                    'model': configuration.llm_model_name,
                    'provider': configuration.model_provider
                }
            })
        else:
            return JsonResponse({
                'success': False,
                'message': f'API returned error: {response.status_code}',
                'details': {
                    'status_code': response.status_code,
                    'error': response.text[:500]
                }
            }, status=400)
            
    except requests.exceptions.Timeout:
        is_local = 'localhost' in configuration.model_base_url or '127.0.0.1' in configuration.model_base_url
        timeout_msg = f'Connection timeout - API did not respond within {timeout} seconds'
        
        hints = []
        if is_local:
            hints.append('Is Ollama/local server running? Check with: ollama list')
            hints.append(f'Try accessing {endpoint} in your browser')
            hints.append('Verify the port number is correct')
        else:
            hints.append('Check your internet connection')
            hints.append('Verify the API endpoint URL is correct')
        
        return JsonResponse({
            'success': False,
            'message': timeout_msg,
            'details': {
                'error': 'Request timeout',
                'endpoint': endpoint,
                'troubleshooting': hints
            }
        }, status=408)
        
    except requests.exceptions.ConnectionError as e:
        is_local = 'localhost' in configuration.model_base_url or '127.0.0.1' in configuration.model_base_url
        
        hints = []
        if is_local:
            hints.append('Ollama may not be running. Start it with: ollama serve')
            hints.append('Check if the port is correct (default: 11434)')
            hints.append(f'Test manually: curl {endpoint}')
        else:
            hints.append('Check your internet connection')
            hints.append('Verify the base URL is correct')
            hints.append('Check if a firewall is blocking the connection')
        
        return JsonResponse({
            'success': False,
            'message': 'Connection failed - Could not reach API endpoint',
            'details': {
                'error': str(e)[:500],
                'endpoint': endpoint,
                'troubleshooting': hints
            }
        }, status=503)
        
    except Exception as e:
        log.error(f"API connection test failed: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Test failed: {str(e)}',
            'details': {'error': str(e)[:500]}
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
@permission_required('extractor.view_processedtext', raise_exception=True)
def extraction_dashboard(request):
    """
    Dashboard showing all processed files grouped by patient, ready for extraction.
    """
    from client_app.models import Patient
    
    # Get all processed files with their patients
    processed_files = ProcessedText.objects.select_related(
        'file_upload__patient_id',
        'processed_by_user'
    ).filter(
        file_upload__processing_status='completed'
    ).order_by('-created_at')
    
    # Group by patient
    patients_data = {}
    unlinked_files = []
    
    for pf in processed_files:
        patient = pf.file_upload.patient_id
        
        if patient:
            if patient.patient_id not in patients_data:
                patients_data[patient.patient_id] = {
                    'patient': patient,
                    'files': [],
                    'total_files': 0,
                    'extracted_files': 0,
                }
            
            # Latest job status for this file — a pending or failed job is
            # NOT "extracted", and the badge must say so
            latest_job = ExtractionJob.objects.filter(
                processed_file=pf
            ).order_by('-created_at').values_list('extraction_status', flat=True).first()

            patients_data[patient.patient_id]['files'].append({
                'processed_file': pf,
                'has_extraction': latest_job is not None,
                'job_status': latest_job,
            })
            patients_data[patient.patient_id]['total_files'] += 1
            if latest_job == 'completed':
                patients_data[patient.patient_id]['extracted_files'] += 1
        else:
            latest_job = ExtractionJob.objects.filter(
                processed_file=pf
            ).order_by('-created_at').values_list('extraction_status', flat=True).first()
            unlinked_files.append({
                'processed_file': pf,
                'has_extraction': latest_job is not None,
                'job_status': latest_job,
            })

    # Get available response models (complete ones only — mid-wizard models
    # have no tables/fields yet)
    response_models = ResponseModel.objects.filter(is_complete=True).select_related('client')
    
    context = {
        'patients_data': patients_data,
        'unlinked_files': unlinked_files,
        'response_models': response_models,
        'total_patients': len(patients_data),
        'total_processed_files': processed_files.count(),
    }
    
    return render(request, 'extractor/extraction_dashboard.html', context)


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
        
        if not processed_file_ids or not response_model_id:
            messages.error(request, "Please select files and a response model.")
            return redirect('extractor:extraction_dashboard')
        
        response_model = get_object_or_404(ResponseModel, id=response_model_id)
        processed_files = ProcessedText.objects.filter(id__in=processed_file_ids)

        if not processed_files.exists():
            messages.error(request, "No valid files selected.")
            return redirect('extractor:extraction_dashboard')

        # Readiness check: refuse to run an unbuildable extraction model
        readiness = PydanticModelBuilder.validate_model_configuration(response_model)
        if not readiness['valid']:
            for error in readiness['errors']:
                messages.error(request, error)
            return redirect('extractor:extraction_dashboard')
        try:
            PydanticModelBuilder.build_extraction_model(response_model)
        except Exception as e:
            messages.error(request, f"Extraction model could not be built: {e}")
            return redirect('extractor:extraction_dashboard')

        # Dispatch one Celery task per file; existing live jobs are reused
        # so double-submits don't double-charge.
        queued = 0
        reused = 0
        for processed_file in processed_files:
            job, created = InstructorExtractionService.get_or_create_job(
                processed_file, response_model, request.user
            )
            if created:
                run_extraction_job.delay(job.id)
                queued += 1
            else:
                reused += 1

        messages.success(
            request,
            f"Extraction queued: {queued} job(s) dispatched"
            + (f", {reused} already running" if reused else "")
            + f" for {len(processed_files)} file(s)."
        )

        return redirect('extractor:extraction_results_list')
        
    except Exception as e:
        log.error(f"Extraction start failed: {e}")
        messages.error(request, f"Extraction failed: {str(e)}")
        return redirect('extractor:extraction_dashboard')


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

    # Group results by table, then by extracted record, so multi-record
    # extractions (e.g. several diagnoses) stay visually separated
    results_by_table = {}
    for result in extraction_results:
        table_name = str(result.database_field.clientapp_database_table)
        records = results_by_table.setdefault(table_name, {})
        record_key = result.record_id or 0
        bucket = records.setdefault(record_key, {
            'record_index': result.record.record_index if result.record else 0,
            'results': [],
        })
        bucket['results'].append(result)

    # Flatten into ordered lists for the template
    results_by_table = {
        table: sorted(records.values(), key=lambda r: r['record_index'])
        for table, records in results_by_table.items()
    }
    
    # Get processed file content
    content = FileProcessorService.get_processed_content(extraction_job.processed_file)
    
    context = {
        'extraction_job': extraction_job,
        'extraction_results': extraction_results,
        'results_by_table': results_by_table,
        'processed_content': content,
        'total_results': extraction_results.count(),
    }
    
    return render(request, 'extractor/extraction_job_detail.html', context)


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

    if action == 'correct':
        new_value = request.POST.get('edited_data')
        if not new_value or not new_value.strip():
            messages.error(request, "Correction requires a value.")
            return redirect('extractor:extraction_job_detail', job_id=extraction_result.extraction_job.id)
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
        return redirect('extractor:extraction_job_detail', job_id=extraction_result.extraction_job.id)

    if action == 'accept' and not data_accuracy:
        data_accuracy = 'accurate'
    if action == 'reject':
        data_accuracy = 'inaccurate'

    if data_accuracy:
        if data_accuracy not in DataAccuracyChoices.values:
            messages.error(request, f"Invalid accuracy value '{data_accuracy}'.")
            return redirect('extractor:extraction_job_detail', job_id=extraction_result.extraction_job.id)
        extraction_result.data_accuracy = data_accuracy

    extraction_result.revision_history = (extraction_result.revision_history or []) + [history_entry]
    extraction_result.verified_by = request.user
    extraction_result.verification_date_time = timezone.now()
    extraction_result.save()

    messages.success(request, "Extraction result updated successfully.")
    return redirect('extractor:extraction_job_detail', job_id=extraction_result.extraction_job.id)


# Instructor Message Views

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

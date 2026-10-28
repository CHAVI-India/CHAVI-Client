import os
import re
import json
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.utils import timezone
from logging import getLogger

from extractor.models import (
    ResponseModel, ResponseModelTable, ResponseModelTableField,
    DatabaseTable, DatabaseField, ClientConfiguration,
    ExtractionJob, ExtractionResult, ExtractionStatusChoices, DataAccuracyChoices,
    InstructorMessage, InstructorRole, EmbeddingConfiguration, LookupEmbedding,
    BackgroundTask, FileTypeChoices, ExtractedRecord, ExtractionReviewBatch,
    DatabaseField
)
from extractor.services.schema_discovery import SchemaDiscoveryService
from extractor.services.model_hierarchy import ancestor_tables, identity_field_names
from extractor.services.pydantic_builder import PydanticModelBuilder
from extractor.services.file_processor import FileProcessorService
from extractor.services.instructor_extractor import InstructorExtractionService
from extractor.services.review import (
    ReviewConflictError, ReviewValidationError, approve_review,
    get_review_context, prepare_review, review_options,
)
from extractor.forms import ReviewApprovalForm
from extractor.tasks import advance_extraction_job
from extractor.models import FileUpload, ProcessedText, TextDeidentificationPipelineConfig

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


def build_table_sections(tables, selected_ids):
    """Group the flat, depth-ordered table list into display sections.

    ``SchemaDiscoveryService.get_hierarchical_table_structure()`` returns
    tables ordered patient → direct links → deeper levels → unlinked.
    This collapses that ordering into sections with presentation metadata:
    one each for the root (depth 0), direct links (depth 1), every deeper
    level, and unlinked tables (no patient relationship). Returns a list
    of {key, title, description, icon, icon_class, tables, count, selected}.
    """
    groups = {}
    for table in tables:
        groups.setdefault(table.get('depth'), []).append(table)

    def _meta(depth):
        if depth == 0:
            return (
                'Root',
                'The patient record — entry point for every extraction',
                'fas fa-user', 'text-chavi-charcoal-600',
            )
        if depth == 1:
            return (
                'Directly linked',
                'Tables with a direct relationship to the patient record',
                'fas fa-link', 'text-chavi-primary-600',
            )
        if depth is None:
            return (
                'Unlinked',
                'No discovered relationship to the patient record',
                'fas fa-unlink', 'text-gray-400',
            )
        intermediate = depth - 1
        return (
            f'Level {depth}',
            f'Reached from the patient via {intermediate} intermediate table'
            f'{"s" if intermediate > 1 else ""}',
            'fas fa-sitemap', 'text-chavi-sun-600',
        )

    sections = []
    for depth in [0, 1] + sorted(d for d in groups if isinstance(d, int) and d > 1) + [None]:
        group = groups.get(depth)
        if not group:
            continue
        title, description, icon, icon_class = _meta(depth)
        sections.append({
            'key': 'root' if depth == 0 else (f'level-{depth}' if depth is not None else 'unlinked'),
            'title': title,
            'description': description,
            'icon': icon,
            'icon_class': icon_class,
            'tables': group,
            'count': len(group),
            'selected': sum(1 for t in group if t['id'] in selected_ids),
        })
    return sections


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

    selected_ids = set(ResponseModelTable.objects.filter(
        response_model=response_model
    ).values_list('database_table_id', flat=True))

    auto_added_ids = set(ResponseModelTable.objects.filter(
        response_model=response_model, auto_added=True
    ).values_list('database_table_id', flat=True))

    # Presentation flags per table (selection state, auto-include, icon)
    # consumed by the check_card grids.
    for table in tables_structure:
        table['selected'] = table['id'] in selected_ids
        table['auto_added'] = table['id'] in auto_added_ids
        depth = table.get('depth')
        if depth == 0:
            table['icon'], table['icon_class'] = 'fas fa-user', 'text-chavi-charcoal-600'
        elif depth == 1:
            table['icon'], table['icon_class'] = 'fas fa-link', 'text-chavi-primary-600'
        elif depth:
            table['icon'], table['icon_class'] = 'fas fa-sitemap', 'text-chavi-sun-600'
        else:
            table['icon'], table['icon_class'] = 'fas fa-unlink', 'text-gray-400'

    context = {
        'response_model': response_model,
        'tables': tables_structure,
        'table_sections': build_table_sections(tables_structure, selected_ids),
        'selected_tables': list(selected_ids),
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
            extraction_concurrency = int(
                request.POST.get('extraction_concurrency') or 1)
            model_max_tokens_raw = request.POST.get('model_max_tokens', '').strip()
            model_max_tokens = int(model_max_tokens_raw) if model_max_tokens_raw else None
        except ValueError:
            messages.error(request, "Timeout, context size, concurrency and max tokens must be numbers.")
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
                extraction_concurrency=extraction_concurrency,
                model_max_tokens=model_max_tokens,
                model_type=request.POST.get('model_type') or 'system2',
                deid_local_certified=request.POST.get('deid_local_certified') == 'on',
            )
            configuration.full_clean()
            configuration.save()

            messages.success(request, f"Client configuration '{llm_model_name}' created successfully!")
            return redirect('extractor:client_configuration_detail', config_id=configuration.id)

        except Exception as e:
            log.error(f"Error creating client configuration: {e}")
            messages.error(request, f"Error creating configuration: {str(e)}")
            return redirect('extractor:client_configuration_create')
    
    limit_fields = ('request_timeout', 'context_size', 'model_max_tokens',
                    'extraction_concurrency')
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
        ],
        'field_help': {
            n: ClientConfiguration._meta.get_field(n).help_text
            for n in limit_fields},
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
            configuration.extraction_concurrency = int(
                request.POST.get('extraction_concurrency') or 1)
            model_max_tokens_raw = request.POST.get('model_max_tokens', '').strip()
            configuration.model_max_tokens = int(model_max_tokens_raw) if model_max_tokens_raw else None
        except ValueError:
            messages.error(request, "Timeout, context size, concurrency and max tokens must be numbers.")
            return redirect('extractor:client_configuration_edit', config_id=configuration.id)

        new_api_key = request.POST.get('model_api_key')
        if new_api_key:
            configuration.model_api_key = new_api_key
        
        new_refresh_key = request.POST.get('model_api_refresh_key')
        if new_refresh_key:
            configuration.model_api_refresh_key = new_refresh_key

        configuration.model_type = request.POST.get('model_type') or 'system2'
        configuration.deid_local_certified = request.POST.get('deid_local_certified') == 'on'
        
        try:
            configuration.full_clean()
            configuration.save()
            messages.success(request, f"Client configuration '{configuration.llm_model_name}' updated successfully!")
            return redirect('extractor:client_configuration_detail', config_id=configuration.id)
            
        except Exception as e:
            log.error(f"Error updating client configuration: {e}")
            messages.error(request, f"Error updating configuration: {str(e)}")
    
    limit_fields = ('request_timeout', 'context_size', 'model_max_tokens',
                    'extraction_concurrency')
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
        ],
        'field_help': {
            n: ClientConfiguration._meta.get_field(n).help_text
            for n in limit_fields},
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

        if configuration.model_type == 'system1':
            # System-1 decision models expose /v1/systemone, not chat. Ping the
            # judge endpoint with a trivial question instead of a chat call.
            from extractor.services import system1_judge
            start_time = datetime.now()
            prob = system1_judge.judge_span(
                configuration, 'system one connectivity check', 0, 4,
                threshold=0.0, window=40)
            response_time = (datetime.now() - start_time).total_seconds()
            return JsonResponse({
                'success': True,
                'message': 'System-1 decision endpoint reachable.',
                'details': {
                    'status_code': 200,
                    'response_time': f'{response_time:.2f}s',
                    'model': configuration.llm_model_name,
                    'provider': configuration.model_provider,
                    'is_phi_probability': round(float(prob), 4),
                },
            })

        client = OpenAI(
            base_url=base_url,
            api_key=configuration.model_api_key or 'not-needed',
            timeout=configuration.request_timeout,
            max_retries=0,
        )

        start_time = datetime.now()
        # Reasoning models consume tokens on thinking before the visible
        # reply — 5 is too tight for them, 64 still keeps the ping cheap.
        response = client.chat.completions.create(
            model=configuration.llm_model_name,
            messages=[{'role': 'user', 'content': 'Reply with the word "ok".'}],
            max_tokens=64,
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


@login_required
@permission_required('extractor.change_clientconfiguration', raise_exception=True)
@require_http_methods(["POST"])
def client_configuration_discover_capabilities(request, config_id):
    """
    Discover model capabilities by querying the provider API.
    Stores the result on the configuration and returns it as JSON.
    """
    configuration = get_object_or_404(ClientConfiguration, id=config_id)

    if configuration.api_key_expired():
        return JsonResponse({
            'success': False,
            'message': f"API key expired on {configuration.model_api_key_validity:%Y-%m-%d}. Update the key first.",
        }, status=400)

    try:
        if configuration.model_type == 'system1':
            # System-1 decision models have no chat capabilities; confirm the
            # judge endpoint is reachable and record a decision-model profile.
            from extractor.services import system1_judge
            prob = system1_judge.judge_span(
                configuration, 'system one capability probe', 0, 4,
                threshold=0.0, window=40)
            capabilities = {
                'reasoning': False, 'reasoning_levels': [], 'reasoning_default': None,
                'vision': False, 'tools': False, 'context_length': None,
                'model_details': {'family': 'decision-model',
                                  'note': 'System-1 judge (no chat capabilities)'},
                'provider_hint': configuration.model_provider,
                'is_phi_probability': round(float(prob), 4),
            }
            configuration.model_capabilities = capabilities
            configuration.save(update_fields=['model_capabilities', 'updated_at'])
            return JsonResponse({
                'success': True,
                'message': 'System-1 decision model confirmed reachable.',
                'capabilities': capabilities,
            })

        from extractor.services.model_capabilities import discover_capabilities

        capabilities = discover_capabilities(
            model_provider=configuration.model_provider,
            model_name=configuration.llm_model_name,
            model_base_url=configuration.model_base_url,
            model_api_key=configuration.model_api_key,
            request_timeout=configuration.request_timeout,
        )

        # Store on the model
        configuration.model_capabilities = capabilities
        configuration.save(update_fields=['model_capabilities', 'updated_at'])

        return JsonResponse({
            'success': True,
            'message': 'Capabilities discovered successfully.',
            'capabilities': capabilities,
        })

    except Exception as e:
        log.error(f"Capability discovery failed for config {config_id}: {type(e).__name__}: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Discovery failed: {type(e).__name__}: {str(e)[:200]}',
            'details': {'error': str(e)[:300]},
        }, status=500)


@login_required
@permission_required('extractor.change_clientconfiguration', raise_exception=True)
@require_http_methods(["POST"])
def client_configuration_set_reasoning(request, config_id):
    """
    Set the reasoning effort/level for a configuration.
    Accepts POST JSON: {"reasoning_effort": "medium"}
    """
    configuration = get_object_or_404(ClientConfiguration, id=config_id)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        body = {}

    reasoning_effort = body.get('reasoning_effort', '').strip()

    # Validate against discovered capabilities if available
    caps = configuration.model_capabilities or {}
    valid_levels = caps.get('reasoning_levels', [])
    if valid_levels and reasoning_effort:
        # Allow both string levels and boolean values
        allowed = [str(v).lower() for v in valid_levels]
        if reasoning_effort.lower() not in allowed:
            return JsonResponse({
                'success': False,
                'message': f"Invalid reasoning level '{reasoning_effort}'. "
                           f"Valid options: {', '.join(allowed)}",
            }, status=400)

    configuration.reasoning_effort = reasoning_effort
    configuration.save(update_fields=['reasoning_effort', 'updated_at'])

    return JsonResponse({
        'success': True,
        'message': f"Reasoning effort set to: {reasoning_effort or 'model default'}",
    })


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
        'deid_enabled': getattr(settings, 'EXTRACTOR_DEID_ENABLED', True),
    }
    if file_upload.file_type == 'csv':
        from client_app.models import Patient
        from extractor.services.csv_rows import (
            csv_header_names, is_row_document, row_number)
        context['csv_headers'] = csv_header_names(file_upload)
        context['response_models'] = list(ResponseModel.objects.all().order_by('name'))

        # Present the CSV as one entry per patient row (its latest working
        # version) plus the raw source alias — not a wall of per-row versions.
        latest_by_row = {}
        source_alias = None
        for p in processed_files:
            if is_row_document(p):
                n = row_number(p.source_sheet)
                cur = latest_by_row.get(n)
                if cur is None or p.version > cur.version:
                    latest_by_row[n] = p
            elif not p.source_sheet:
                source_alias = p
        csv_rows = [(n, latest_by_row[n]) for n in sorted(latest_by_row)]
        context['csv_rows'] = csv_rows
        context['csv_source_alias'] = source_alias
        context['csv_rows_processed'] = bool(csv_rows)
        context['csv_row_count'] = len(csv_rows)
        # Distinct patients matched across the row documents (exact match on
        # the chosen patient-id column), so the page shows who was linked.
        matched_pks = sorted({pt.effective_patient_pk for _, pt in csv_rows
                              if pt.effective_patient_pk})
        context['csv_matched_patients'] = (list(
            Patient.objects.filter(pk__in=matched_pks).order_by('patient_id'))
            if matched_pks else [])
    deid_enabled = context['deid_enabled']
    context['deid_openmed_enabled'] = bool(getattr(
        settings, 'EXTRACTOR_DEID_OPENMED_ENABLED', True))
    if deid_enabled:
        from extractor.models import ClientConfiguration
        context['deid_llm_configs'] = list(
            ClientConfiguration.objects.filter(
                model_type='system2', deid_local_certified=True))
        context['deid_pipelines'] = list(
            TextDeidentificationPipelineConfig.objects.order_by('name'))
        context['deid_default_is_llm'] = False
    else:
        context['deid_llm_configs'] = []
        context['deid_pipelines'] = []
        context['deid_default_is_llm'] = False

    return render(request, 'extractor/file_upload_detail.html', context)


@login_required
@permission_required('extractor.change_fileupload', raise_exception=True)
@require_http_methods(["POST"])
def file_upload_process(request, file_id):
    """
    Process an uploaded file (convert PDF to markdown, Excel to CSV, etc.).
    CSV uploads take a dedicated row pipeline: each data row becomes a
    per-row patient document that flows through the same deid + extraction
    chain as a PDF, fanned out one Celery task per row.
    """
    file_upload = get_object_or_404(FileUpload, id=file_id)

    try:
        if file_upload.file_type == FileTypeChoices.CSV:
            return _process_csv_rows(file_upload, request)

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

        if result['success'] or result.get('processed_files'):
            _dispatch_deid_tasks(result.get('processed_files', []), request)

    except Exception as e:
        log.error(f"File processing error: {e}")
        messages.error(request, f"Processing failed: {str(e)}")

    return redirect('extractor:file_upload_detail', file_id=file_upload.id)


def _process_csv_rows(file_upload, request):
    """CSV row pipeline: register the source alias, expand each data row into
    a per-row patient document, and fan out one task per row.

    POST fields: csv_patient_id_column (header name), csv_response_model
    (optional id), csv_deid_review_required (checkbox), csv_auto_extract
    (checkbox).
    """
    from extractor.services.csv_rows import expand_csv_to_row_documents

    patient_id_column = request.POST.get('csv_patient_id_column', '').strip()
    review_required = request.POST.get('csv_deid_review_required') == 'on'
    auto_extract = request.POST.get('csv_auto_extract') == 'on'
    response_model_id = request.POST.get('csv_response_model', '').strip()
    response_model = (ResponseModel.objects.filter(id=response_model_id).first()
                      if response_model_id else None)

    # Persist the row-pipeline configuration on the upload.
    file_upload.csv_patient_id_column = patient_id_column
    file_upload.csv_deid_review_required = review_required
    file_upload.csv_auto_extract = auto_extract
    file_upload.csv_response_model = response_model

    # Register the raw CSV as a source alias (no deid on it) and read headers.
    FileProcessorService.process_file(file_upload, user=request.user)

    # Guard against reprocessing: don't create a second batch of row
    # documents (same source_sheet keys) over an existing one.
    from extractor.services.csv_rows import _ROW_SHEET_RE
    if any(_ROW_SHEET_RE.match(p.source_sheet or '')
           for p in ProcessedText.objects.filter(file_upload=file_upload)):
        messages.warning(
            request,
            "This CSV has already been expanded into row documents. Delete "
            "the upload and re-upload to reprocess it as rows.")
        return redirect('extractor:file_upload_detail', file_id=file_upload.id)

    row_pts, unmatched = expand_csv_to_row_documents(
        file_upload, request.user, patient_id_column, review_required)
    file_upload.csv_unmatched_rows = unmatched
    file_upload.save()

    if not row_pts:
        messages.error(
            request,
            "No CSV data rows found to process. Check that the file has a "
            "header row and at least one data row.")
        return redirect('extractor:file_upload_detail', file_id=file_upload.id)

    if unmatched:
        sample = ', '.join(
            f"row {u['row']} ({u['value']!r})" for u in unmatched[:5])
        more = f" and {len(unmatched) - 5} more" if len(unmatched) > 5 else ""
        messages.warning(
            request,
            f"{len(unmatched)} CSV row(s) had no exact patient match and are "
            f"unlinked: {sample}{more}. They will still be processed.")

    _dispatch_csv_row_tasks(row_pts, request)
    messages.success(
        request,
        f"Processed {len(row_pts)} CSV row(s), one task per row.")
    return redirect('extractor:file_upload_detail', file_id=file_upload.id)


def _dispatch_csv_row_tasks(row_pts, request):
    """One Celery task per CSV row document; deid (and optional auto-
    extraction when a response model is set) runs inside each task."""
    if not getattr(settings, 'EXTRACTOR_DEID_ENABLED', True):
        # Deid disabled: nothing to run per row.
        return
    if not getattr(settings, 'EXTRACTOR_DEID_AUTO_RUN', True):
        return
    from extractor.tasks import process_csv_row_task
    dispatched = 0
    for pt in row_pts:
        running = BackgroundTask.objects.filter(
            task_name__startswith=f"CSV row {pt.id}",
            status__in=['pending', 'running']
        ).exists()
        if running:
            continue
        task = BackgroundTask.objects.create(
            task_id=f"csvrow-{pt.id}-{int(timezone.now().timestamp())}",
            task_name=f"CSV row {pt.id}",
            status='pending',
        )
        process_csv_row_task.delay(
            task.task_id, pt.id, user_id=request.user.id)
        dispatched += 1
    if dispatched:
        messages.info(
            request,
            f"{dispatched} CSV row task(s) started.")


def _dispatch_deid_tasks(processed_files, request):
    """Auto-dispatch deidentification for each produced ProcessedText row
    when EXTRACTOR_DEID_AUTO_RUN is on. Mirrors the OCR dispatch pattern."""
    if not getattr(settings, 'EXTRACTOR_DEID_ENABLED', True):
        return
    if not getattr(settings, 'EXTRACTOR_DEID_AUTO_RUN', True):
        return
    from extractor.tasks import deidentify_processed_text_task
    dispatched = 0
    for entry in processed_files:
        pt_id = entry.get('id')
        if not pt_id:
            continue
        running = BackgroundTask.objects.filter(
            task_name__startswith=f"Deidentify processed file {pt_id}",
            status__in=['pending', 'running']
        ).exists()
        if running:
            continue
        task = BackgroundTask.objects.create(
            task_id=f"deid-{pt_id}-{int(timezone.now().timestamp())}",
            task_name=f"Deidentify processed file {pt_id}",
            status='pending',
        )
        deidentify_processed_text_task.delay(
            task.task_id, pt_id, user_id=request.user.id)
        dispatched += 1
    if dispatched:
        messages.info(
            request,
            f"Deidentification started for {dispatched} file(s); "
            "review each deidentified version before extraction.")


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
    )
    from extractor.tasks import ocr_processed_text_task
    ocr_processed_text_task.delay(task.task_id, processed_text_id, request.user.id)

    messages.success(request, f"OCR started for '{processed_text.file_upload.original_filename}'.")
    return redirect(next_url)


@login_required
@permission_required('extractor.view_textdeidentificationpipelineconfig', raise_exception=True)
def pipeline_list(request):
    from extractor.models import TextDeidentificationPipelineConfig
    pipelines = TextDeidentificationPipelineConfig.objects.order_by('name')
    return render(request, 'extractor/pipeline_list.html', {'pipelines': pipelines})


@login_required
@permission_required('extractor.add_textdeidentificationpipelineconfig', raise_exception=True)
def pipeline_create(request):
    from extractor.forms import TextDeidentificationPipelineConfigForm
    form = TextDeidentificationPipelineConfigForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        pipeline = form.save()
        messages.success(request, f"Pipeline '{pipeline.display_name}' created.")
        return redirect('extractor:pipeline_detail', pipeline_id=pipeline.id)
    return render(request, 'extractor/pipeline_create.html', {'form': form})


@login_required
@permission_required('extractor.view_textdeidentificationpipelineconfig', raise_exception=True)
def pipeline_detail(request, pipeline_id):
    from extractor.models import TextDeidentificationPipelineConfig
    from django.conf import settings
    pipeline = get_object_or_404(TextDeidentificationPipelineConfig, id=pipeline_id)
    context = {
        'pipeline': pipeline,
        'default_date_shift': getattr(settings, 'EXTRACTOR_DEID_DATE_SHIFT_RANGE', 90),
    }
    return render(request, 'extractor/pipeline_detail.html', context)


@login_required
@permission_required('extractor.change_textdeidentificationpipelineconfig', raise_exception=True)
def pipeline_edit(request, pipeline_id):
    from extractor.models import TextDeidentificationPipelineConfig
    from extractor.forms import TextDeidentificationPipelineConfigForm
    pipeline = get_object_or_404(TextDeidentificationPipelineConfig, id=pipeline_id)
    form = TextDeidentificationPipelineConfigForm(request.POST or None, instance=pipeline)
    if request.method == 'POST' and form.is_valid():
        pipeline = form.save()
        messages.success(request, f"Pipeline '{pipeline.display_name}' updated.")
        return redirect('extractor:pipeline_detail', pipeline_id=pipeline.id)
    return render(request, 'extractor/pipeline_edit.html',
                  {'form': form, 'pipeline': pipeline})


@login_required
@permission_required('extractor.delete_textdeidentificationpipelineconfig', raise_exception=True)
def pipeline_delete(request, pipeline_id):
    from extractor.models import TextDeidentificationPipelineConfig
    pipeline = get_object_or_404(TextDeidentificationPipelineConfig, id=pipeline_id)
    if request.method == 'POST':
        name = pipeline.display_name
        pipeline.delete()
        messages.success(request, f"Pipeline '{name}' deleted.")
        return redirect('extractor:pipeline_list')
    return render(request, 'extractor/pipeline_delete.html', {'pipeline': pipeline})


@login_required
@permission_required('extractor.change_processedtext', raise_exception=True)
@require_http_methods(["POST"])
def processed_text_deidentify(request, processed_text_id):
    """
    Dispatch deidentification for a processed text version (manual action —
    backfill for files processed before deid existed, or retries after a
    failed run). Creates a BackgroundTask and returns to the referring page.
    """
    processed_text = get_object_or_404(ProcessedText, id=processed_text_id)
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'extractor:extraction_dashboard'

    if processed_text.deidentified:
        messages.info(request, "This version was already produced by deidentification.")
        return redirect(next_url)

    running = BackgroundTask.objects.filter(
        task_name__startswith=f"Deidentify processed file {processed_text_id}",
        status__in=['pending', 'running']
    ).exists()
    if running:
        messages.warning(request, "Deidentification is already in progress for this file.")
        return redirect(next_url)

    backend = (request.POST.get('backend') or 'default').strip()
    client_config_id = request.POST.get('client_config_id') or None
    pipeline_id = request.POST.get('pipeline_id') or None
    # The UI encodes engine choices as 'llm:<config_id>' / 'pipeline:<id>'
    # in a single select.
    if ':' in backend:
        backend, _, encoded_id = backend.partition(':')
        if encoded_id:
            if backend == 'pipeline':
                pipeline_id = encoded_id
            else:  # 'llm:<id>'
                client_config_id = encoded_id or client_config_id
    if client_config_id:
        if not str(client_config_id).isdigit():
            messages.error(request, "Invalid deidentification configuration choice.")
            return redirect(next_url)
        client_config_id = int(client_config_id)
    if pipeline_id:
        if not str(pipeline_id).isdigit():
            messages.error(request, "Invalid deidentification pipeline choice.")
            return redirect(next_url)
        pipeline_id = int(pipeline_id)
    if backend not in ('default', 'presidio', 'llm', 'openmed', 'pipeline'):
        messages.error(request, "Unknown deidentification engine.")
        return redirect(next_url)
    from extractor.services.text_deidentification import (
        LlmDeidConfigurationError, TextDeidentificationService)
    try:
        if pipeline_id:
            if not TextDeidentificationPipelineConfig.objects.filter(
                    id=pipeline_id).exists():
                messages.error(request, "Deidentification pipeline not found.")
                return redirect(next_url)
        else:
            TextDeidentificationService._resolve_pipeline(
                None, backend, client_config_id)
    except LlmDeidConfigurationError as e:
        messages.error(request, str(e))
        return redirect(next_url)

    task = BackgroundTask.objects.create(
        task_id=f"deid-{processed_text_id}-{int(timezone.now().timestamp())}",
        task_name=f"Deidentify processed file {processed_text_id}",
        status='pending',
    )
    from extractor.tasks import deidentify_processed_text_task
    deidentify_processed_text_task.delay(
        task.task_id, processed_text_id, user_id=request.user.id,
        backend=backend, client_config_id=client_config_id,
        pipeline_id=pipeline_id)

    engine_label = 'pipeline' if pipeline_id else backend
    messages.success(
        request,
        f"Deidentification started for "
        f"'{processed_text.file_upload.original_filename}' "
        f"(engine: {engine_label}).")
    return redirect(next_url)


@login_required
@permission_required('extractor.view_processedtext', raise_exception=True)
def processed_text_deid_review(request, processed_id):
    """
    Review page for a deidentified processed text version: highlighted tags,
    search, textarea edit + select-to-redact, save, and mark-reviewed.
    """
    from extractor.services.text_deidentification import (
        TextDeidentificationService, PHI_ENTITY_TYPES, PHI_ENTITY_LABELS,
    )

    processed_text = get_object_or_404(ProcessedText, id=processed_id)
    next_url = request.POST.get('next') or request.GET.get('next') or 'extractor:extraction_dashboard'

    if not processed_text.deidentified:
        messages.warning(request, "This version is not deidentified.")
        return redirect('extractor:processed_text_view', processed_id=processed_id)

    if request.method == 'POST':
        if not request.user.has_perm('extractor.change_processedtext'):
            messages.error(request, "You do not have permission to edit deidentified text.")
            return redirect(next_url)
        action = request.POST.get('action')
        try:
            if action == 'save':
                new_content = request.POST.get('content', '')
                TextDeidentificationService.save_manual_edit(
                    processed_text, new_content, user=request.user)
                messages.success(request, "Deidentified text updated.")
            elif action == 'review':
                TextDeidentificationService.mark_reviewed(
                    processed_text, user=request.user)
                messages.success(request, "Deidentified text marked as reviewed.")
                return redirect(next_url)
            elif action == 'restore':
                tag = request.POST.get('tag', '').strip()
                n = TextDeidentificationService.restore_tag(
                    processed_text, tag)
                if n:
                    messages.success(
                        request,
                        f"Restored {tag} to its original value "
                        f"({n} occurrence(s)).")
                else:
                    messages.warning(
                        request, f"No occurrences of {tag} found to restore.")
        except Exception as e:
            log.error(f"Deid review save failed: {e}", exc_info=True)
            messages.error(request, f"Save failed: {e}")

    content = FileProcessorService.get_processed_content(processed_text)

    # Original (pre-deid) source text, for side-by-side verification.
    original_content = ''
    source = processed_text.deidentified_source
    if source is not None:
        original_content = FileProcessorService.get_processed_content(source)

    # Live tag inventory: regex over the current content so manual edits are
    # reflected without storing spans.
    tag_counts = {}
    for t in re.findall(r'<[A-Z_]+(?:_\d+)?>', content):
        tag_counts[t] = tag_counts.get(t, 0) + 1

    # Redaction map limited to tags actually present in the current text —
    # restored or manually removed entries disappear once gone.
    deid_map = [
        e for e in (processed_text.deid_map or [])
        if e.get('tag') and e['tag'] in content]

    # Unified redaction list: every tag present in the current text, with its
    # original (from the deid map) when known. Tags added manually in the
    # editor have no recorded original and are flagged so the reviewer knows
    # Restore is unavailable for them.
    deid_map_by_tag = {}
    for e in deid_map:
        deid_map_by_tag.setdefault(e['tag'], e)
    redactions = []
    for tag, count in tag_counts.items():
        e = deid_map_by_tag.get(tag)
        original = e.get('original') if e else None
        redactions.append({
            'tag': tag,
            'count': count,
            'original': original,
            'manual': e is None,
            # Filter haystack: tag name (brackets stripped) + original text.
            'search': (tag.strip('<>') + ' ' + (original or '')).strip(),
        })
    # Known-original tags first (the actionable ones), then manual tags.
    redactions.sort(key=lambda r: (r['manual'], r['tag']))

    # Redact-type dropdown: every PHI type the pipeline can emit, plus any
    # type already present in this document (detections, map, or live tags)
    # so manual/legacy tags stay selectable.
    doc_types = set(processed_text.deid_entities or {})
    doc_types |= {e.get('type') for e in (processed_text.deid_map or [])
                  if e.get('type')}
    doc_types |= {re.sub(r'_\d+$', '', t.strip('<>')) for t in tag_counts}
    redact_types = PHI_ENTITY_TYPES + sorted(doc_types - set(PHI_ENTITY_TYPES))
    redact_options = [
        {'value': t, 'label': PHI_ENTITY_LABELS.get(t, t)} for t in redact_types
    ]

    context = {
        'processed_text': processed_text,
        'content': content,
        'original_content': original_content,
        'tag_counts': tag_counts,
        'deid_map': deid_map,
        'redactions': redactions,
        'redact_options': redact_options,
        'next': next_url,
    }
    return render(request, 'extractor/processed_text_deid_review.html', context)


def _patient_dashboard_stats(pks):
    """Per-patient dashboard stats keyed by *effective* patient (the row
    patient for CSV row documents, else the upload's patient).

    Returns {patient_pk: {file_count, processed_count, jobs_completed,
    jobs_failed, jobs_active, deid_pending_review, any_job}}.
    """
    from extractor.models import ProcessedText, ExtractionJob
    stats = {pk: {'file_count': 0, 'processed_count': 0, 'jobs_completed': 0,
                  'jobs_failed': 0, 'jobs_active': 0, 'deid_pending_review': 0,
                  'any_job': False} for pk in pks}
    if not pks:
        return stats

    def _doc_owner(d):
        return d['patient_id'] or d['file_upload__patient_id']

    doc_filter = (Q(patient_id__in=pks)
                  | (Q(patient_id__isnull=True)
                     & Q(file_upload__patient_id__in=pks)))
    uploads = {pk: set() for pk in pks}
    for d in ProcessedText.objects.filter(
            doc_filter).values('patient_id', 'file_upload__patient_id',
                               'file_upload_id', 'deidentified', 'deid_reviewed'):
        pk = _doc_owner(d)
        s = stats.get(pk)
        if s is None:
            continue
        s['processed_count'] += 1
        uploads.setdefault(pk, set()).add(d['file_upload_id'])
        if d['deidentified'] and not d['deid_reviewed']:
            s['deid_pending_review'] += 1
    for pk, ups in uploads.items():
        if pk in stats:
            stats[pk]['file_count'] = len(ups)

    job_filter = (Q(processed_file__patient_id__in=pks)
                  | (Q(processed_file__patient_id__isnull=True)
                     & Q(processed_file__file_upload__patient_id__in=pks)))
    for j in ExtractionJob.objects.filter(job_filter).values(
            'processed_file__patient_id', 'processed_file__file_upload__patient_id',
            'extraction_status'):
        pk = (j['processed_file__patient_id']
              or j['processed_file__file_upload__patient_id'])
        s = stats.get(pk)
        if s is None:
            continue
        s['any_job'] = True
        st = j['extraction_status']
        if st == 'completed':
            s['jobs_completed'] += 1
        elif st == 'failed':
            s['jobs_failed'] += 1
        elif st in ('pending', 'processing'):
            s['jobs_active'] += 1
    return stats


@login_required
@permission_required('extractor.view_processedtext', raise_exception=True)
def extraction_dashboard(request):
    """
    Patient-centric dashboard: one row per patient with processed files,
    job-status summary, search/filters, and pagination. Patients are listed
    by *effective* patient — a patient owning CSV row documents appears even
    when no upload is linked to them directly.
    """
    from client_app.models import Patient

    patients = (Patient.objects
                .filter(Q(fileupload__isnull=False)
                        | Q(processed_texts__patient_id__isnull=False))
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
    if file_type:
        patients = patients.filter(fileupload__file_type=file_type)
    if date_from:
        patients = patients.filter(fileupload__created_at__date__gte=date_from)
    if date_to:
        patients = patients.filter(fileupload__created_at__date__lte=date_to)

    # Job-status filter is applied against per-patient effective-patient stats.
    pks = list(patients.values_list('pk', flat=True))
    stats = _patient_dashboard_stats(pks)
    if status:
        if status == 'none':
            pks = [pk for pk in pks if not stats[pk]['any_job']]
        else:
            pks = [pk for pk in pks if stats[pk].get(f'jobs_{status}', 0) > 0]
        patients = patients.filter(pk__in=pks)

    paginator = Paginator(patients, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Attach stats as instance attributes so the template reads them directly.
    for p in page_obj.object_list:
        s = stats.get(p.pk, {})
        p.file_count = s.get('file_count', 0)
        p.processed_count = s.get('processed_count', 0)
        p.jobs_completed = s.get('jobs_completed', 0)
        p.jobs_failed = s.get('jobs_failed', 0)
        p.jobs_active = s.get('jobs_active', 0)
        p.deid_pending_review = s.get('deid_pending_review', 0)

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

    # Documents belonging to this patient: row documents carry their own
    # patient; whole-file documents use the upload's patient.
    pt_for_patient = (Q(patient_id=patient)
                      | (Q(patient_id__isnull=True)
                         & Q(file_upload__patient_id=patient)))

    processed_files = (ProcessedText.objects
                       .select_related('file_upload', 'patient_id')
                       .filter(pt_for_patient,
                               file_upload__processing_status='completed')
                       .order_by('file_upload_id', '-version'))

    file_rows = []
    for pf in processed_files:
        latest_job = (ExtractionJob.objects
                      .filter(processed_file=pf)
                      .order_by('-created_at').first())
        file_rows.append({'processed_file': pf, 'latest_job': latest_job})

    jobs = (ExtractionJob.objects
            .filter(Q(processed_file__patient_id=patient)
                    | (Q(processed_file__patient_id__isnull=True)
                       & Q(processed_file__file_upload__patient_id=patient)))
            .select_related('response_model__client', 'processed_file__file_upload',
                           'processed_file__patient_id')
            .order_by('-created_at')[:50])

    context = {
        'patient': patient,
        'file_rows': file_rows,
        'jobs': jobs,
        'response_models': ResponseModel.objects.filter(is_complete=True).select_related('client'),
        'deid_enabled': getattr(settings, 'EXTRACTOR_DEID_ENABLED', True),
        'deid_require_review': getattr(settings, 'EXTRACTOR_DEID_REQUIRE_REVIEW', True),
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

        # Deidentification gate: only reviewed, deidentified versions may be
        # sent to the extraction provider.
        if getattr(settings, 'EXTRACTOR_DEID_ENABLED', True):
            not_deid = processed_files.filter(deidentified=False)
            if not_deid.exists():
                names = ', '.join(
                    pf.file_upload.original_filename or str(pf.id)
                    for pf in not_deid[:5])
                messages.error(
                    request,
                    f"Extraction blocked: {not_deid.count()} file(s) are not "
                    f"deidentified ({names}). Deidentification runs after "
                    "processing — retry once it completes.")
                return redirect(back)
            if getattr(settings, 'EXTRACTOR_DEID_REQUIRE_REVIEW', True):
                # Per-row review gate: whole-file documents require review
                # (global setting); CSV row documents require review only
                # when their row was flagged review-required (optional).
                from extractor.services.csv_rows import is_row_document
                unreviewed = []
                for pf in processed_files:
                    needs_review = (pf.deid_review_required
                                    if is_row_document(pf) else True)
                    if needs_review and not pf.deid_reviewed:
                        unreviewed.append(pf)
                if unreviewed:
                    names = ', '.join(
                        pf.file_upload.original_filename or str(pf.id)
                        for pf in unreviewed[:5])
                    messages.error(
                        request,
                        f"Extraction blocked: {len(unreviewed)} file(s) "
                        f"await deidentification review ({names}). Open each "
                        "deidentified version and mark it reviewed first.")
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
        from extractor.services.csv_rows import is_row_document
        queued = 0
        reused = 0
        single_job = None
        for processed_file in processed_files:
            job, created = InstructorExtractionService.get_or_create_job(
                processed_file, response_model, request.user
            )
            single_job = job
            # CSV row documents honour the upload's auto-extract preference
            # (e.g. resuming after a manual deid review); whole-file docs
            # keep the manual, click-through staged flow.
            auto = (bool(processed_file.file_upload.csv_auto_extract)
                    if is_row_document(processed_file) else False)
            if job.auto_extract != auto:
                job.auto_extract = auto
                job.save(update_fields=['auto_extract'])
            if created:
                advance_extraction_job.delay(job.id, auto_extract=auto)
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
        'processed_file__patient_id',
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
def extraction_job_detail(request, job_id, review_errors=None, review_field_errors=None,
                          posted_payload=None, status=200):
    """
    View details of a specific extraction job and its results.
    """
    extraction_job = get_object_or_404(
        ExtractionJob.objects.select_related(
            'response_model',
            'processed_file__file_upload__patient_id',
            'processed_file__patient_id',
            'processed_file__deidentified_source',
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

    # Reviewers verify extracted values against the real document — when the
    # job ran on a deidentified version, show the original text; the
    # deidentified text the LLM saw stays available alongside.
    processed_file = extraction_job.processed_file
    source_file = processed_file.deidentified_source \
        if processed_file.deidentified and processed_file.deidentified_source \
        else processed_file
    content = FileProcessorService.get_processed_content(source_file)
    deid_content = (FileProcessorService.get_processed_content(processed_file)
                    if source_file is not processed_file else None)

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

    # Coverage: extracted / not_found / unresolved counts for review
    coverage = {
        row['result_state']: row['n']
        for row in ExtractionResult.objects.filter(extraction_job=extraction_job)
        .values('result_state').annotate(n=Count('id'))
    }

    review_context = get_review_context(extraction_job, request.user, posted_payload)
    approval_history = ExtractionReviewBatch.objects.filter(
        extraction_job=extraction_job).select_related('prepared_by', 'approved_by')
    context = {
        'extraction_job': extraction_job,
        'extraction_results': extraction_results,
        'data_tree': data_tree,
        'processed_content': content,
        'deid_content': deid_content,
        'total_results': extraction_results.count(),
        'stage_entries': stage_entries,
        'stage_running': extraction_job.extraction_status in (
            ExtractionStatusChoices.PENDING, ExtractionStatusChoices.PROCESSING),
        'coverage': coverage,
        'review': review_context,
        'review_errors': review_errors or {},
        'review_field_errors': review_field_errors or {},
        'posted_payload': posted_payload,
        'approval_history': approval_history,
        'can_review': request.user.has_perm('extractor.change_extractionresult'),
    }

    return render(request, 'extractor/extraction_job_detail.html', context, status=status)


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

    # Claim the stage before dispatching — the job flips to processing now,
    # so the Approve button dies with the first click and a duplicate POST
    # or queued task can't re-dispatch (or leapfrog the next approval gate).
    approved_status = extraction_job.extraction_status
    claimed = ExtractionJob.objects.filter(
        id=extraction_job.id,
        extraction_status__in=awaiting,
    ).update(extraction_status=ExtractionStatusChoices.PROCESSING)
    if not claimed:
        messages.error(request, "This job is not waiting for approval.")
        return back
    try:
        advance_extraction_job.delay(
            extraction_job.id, approved_status=approved_status)
    except Exception:
        ExtractionJob.objects.filter(
            id=extraction_job.id,
            extraction_status=ExtractionStatusChoices.PROCESSING,
        ).update(extraction_status=approved_status)
        raise
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
    messages.info(request, "Field changes are reviewed and approved together from the extraction job page.")
    return redirect('extractor:extraction_job_detail', job_id=extraction_result.extraction_job.id)

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
    patient = record.extraction_job.processed_file.effective_patient
    messages.info(request, "Records are created through the job-wide preview and approval workflow.")
    return redirect('extractor:extraction_job_detail', job_id=record.extraction_job_id)

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


@login_required
@permission_required('extractor.change_extractionresult', raise_exception=True)
@require_http_methods(["POST"])
def extraction_review_preview(request, job_id):
    job = get_object_or_404(ExtractionJob, id=job_id)
    try:
        payload = json.loads(request.POST.get('payload') or '{}')
        request_key = uuid.UUID(request.POST.get('request_key') or '')
        batch = prepare_review(job, request.user, payload, request_key)
    except ReviewValidationError as exc:
        try:
            posted_payload = json.loads(request.POST.get('payload') or '{}')
        except json.JSONDecodeError:
            posted_payload = None
        messages.error(request, 'Please correct the review errors shown below.')
        return extraction_job_detail(request, job_id, review_errors=exc.errors,
                                     review_field_errors=exc.field_errors,
                                     posted_payload=posted_payload, status=422)
    except ReviewConflictError as exc:
        messages.error(request, str(exc))
        return extraction_job_detail(request, job_id, status=409)
    except (ValueError, json.JSONDecodeError, TypeError):
        messages.error(request, 'The review submission was incomplete or invalid.')
        return extraction_job_detail(request, job_id, status=422)
    return redirect('extractor:extraction_review_detail', job_id=job_id, batch_id=batch.id)


@login_required
@permission_required('extractor.view_extractionjob', raise_exception=True)
@require_http_methods(["GET"])
def extraction_review_detail(request, job_id, batch_id):
    batch = get_object_or_404(
        ExtractionReviewBatch.objects.select_related('prepared_by', 'approved_by'),
        id=batch_id, extraction_job_id=job_id)
    can_approve = (
        batch.status == 'pending' and batch.prepared_by_id == request.user.id
        and batch.expires_at > timezone.now()
        and request.user.has_perm('extractor.change_extractionresult')
        and request.user.has_perm('extractor.add_recordcreation')
    )
    form = ReviewApprovalForm()
    response = render(request, 'extractor/extraction_review_preview.html', {
        'batch': batch,
        'extraction_job': batch.extraction_job,
        'snapshot': json.loads(batch.snapshot),
        'receipt': json.loads(batch.receipt) if batch.receipt else None,
        'form': form,
        'can_approve': can_approve,
    })
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@permission_required('extractor.change_extractionresult', raise_exception=True)
@require_http_methods(["GET"])
def extraction_review_edit(request, job_id, batch_id):
    batch = get_object_or_404(ExtractionReviewBatch, id=batch_id, extraction_job_id=job_id,
                            prepared_by=request.user)
    snapshot = json.loads(batch.snapshot)
    return extraction_job_detail(request, job_id, posted_payload=snapshot.get('input'))


@login_required
@permission_required('extractor.add_recordcreation', raise_exception=True)
@require_http_methods(["POST"])
def extraction_review_approve(request, job_id, batch_id):
    batch = get_object_or_404(ExtractionReviewBatch, id=batch_id, extraction_job_id=job_id)
    form = ReviewApprovalForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Confirm the preview before saving.')
        return redirect('extractor:extraction_review_detail', job_id=job_id, batch_id=batch_id)
    try:
        batch = approve_review(
            batch.id, request.user,
            confirm=form.cleaned_data['confirm'],
            acknowledge_duplicates=form.cleaned_data['acknowledge_duplicates'])
        messages.success(request, 'Review approved and records saved.')
    except ReviewValidationError as exc:
        for field_errors in exc.errors.values():
            for error in (field_errors if isinstance(field_errors, list) else [field_errors]):
                messages.error(request, str(error))
    except ReviewConflictError as exc:
        messages.error(request, str(exc))
    return redirect('extractor:extraction_review_detail', job_id=job_id, batch_id=batch.id)


@login_required
@permission_required('extractor.view_extractionjob', raise_exception=True)
@require_http_methods(["GET"])
def extraction_review_options(request, job_id):
    job = get_object_or_404(ExtractionJob, id=job_id)
    try:
        data = review_options(
            job, request.user,
            record_id=request.GET.get('record_id'),
            kind=request.GET.get('kind'),
            field_id=request.GET.get('field_id'),
            query=request.GET.get('q', ''),
            page=int(request.GET.get('page') or 1),
            selected_pk=request.GET.get('selected_pk'))
    except (ExtractedRecord.DoesNotExist, DatabaseField.DoesNotExist, ValueError):
        return JsonResponse({'results': [], 'pagination': {'more': False}}, status=404)
    except ReviewValidationError:
        return JsonResponse({'results': [], 'pagination': {'more': False}}, status=400)
    response = JsonResponse(data)
    response['Cache-Control'] = 'no-store'
    return response


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


# Import lookup embedding views
from extractor.views_lookup_embeddings import (
    lookup_embeddings,
    embedding_config_create,
    embedding_config_edit,
    embedding_config_delete,
    embedding_config_activate,
    compute_embeddings,
    get_embedding_progress,
)

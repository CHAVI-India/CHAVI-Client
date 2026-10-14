"""
Views for semantic search configuration and embedding management.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Count
from logging import getLogger
import uuid

from extractor.models import EmbeddingConfiguration, LookupEmbedding, DatabaseField, BackgroundTask
from extractor.services.semantic_search import SemanticSearchService

log = getLogger(__name__)


def _inflight_embedding_tasks_alive(task_ids):
    """
    Ask live Celery workers whether any of these tracked BackgroundTasks is
    actually executing or queued. Returns False when no worker reports it —
    meaning the DB row is stale (e.g. worker restarted mid-task). Our
    BackgroundTask task_id travels in the celery task's args, so a substring
    match on the args repr is enough to correlate.
    """
    try:
        from chavi_client.celery import app as celery_app
        inspector = celery_app.control.inspect(timeout=2.0)
        for query in (inspector.active, inspector.reserved, inspector.scheduled):
            for tasks in (query() or {}).values():
                for t in tasks:
                    if any(tid in (t.get('args') or '') for tid in task_ids):
                        return True
    except Exception as e:
        # Broker/worker unreachable — nothing can be running against it.
        log.warning(f"Celery inspect failed; treating in-flight embedding tasks as stale: {e}")
    return False


@login_required
@permission_required('extractor.view_embeddingconfiguration', raise_exception=True)
def semantic_search_settings(request):
    """
    Main page for semantic search settings - shows configurations and embeddings status.
    """
    # Get all configurations
    configs = EmbeddingConfiguration.objects.all().order_by('-is_active', '-created_at')
    active_config = configs.filter(is_active=True).first()
    
    # Get embedding statistics
    embedding_stats = None
    if active_config:
        total_embeddings = LookupEmbedding.objects.filter(embedding_config=active_config).count()
        
        # Get embeddings grouped by table and field
        by_table_field = LookupEmbedding.objects.filter(
            embedding_config=active_config
        ).values(
            'content_type__model', 
            'field_name'
        ).annotate(
            count=Count('id')
        ).order_by('content_type__model', 'field_name')
        
        # Group by table
        table_stats = {}
        for item in by_table_field:
            table = item['content_type__model']
            if table not in table_stats:
                table_stats[table] = {
                    'total': 0,
                    'fields': []
                }
            table_stats[table]['total'] += item['count']
            table_stats[table]['fields'].append({
                'name': item['field_name'],
                'count': item['count']
            })
        
        embedding_stats = {
            'total': total_embeddings,
            'by_table': table_stats
        }
    
    context = {
        'configs': configs,
        'active_config': active_config,
        'embedding_stats': embedding_stats,
    }
    
    return render(request, 'extractor/semantic_search_settings.html', context)


@login_required
@permission_required('extractor.add_embeddingconfiguration', raise_exception=True)
@require_http_methods(["GET", "POST"])
def embedding_config_create(request):
    """
    Create a new embedding configuration.
    """
    if request.method == 'POST':
        try:
            # Create configuration
            config = EmbeddingConfiguration(
                model_name=request.POST.get('model_name'),
                model_provider=request.POST.get('model_provider'),
                embedding_dimension=int(request.POST.get('embedding_dimension')),
                api_key=request.POST.get('api_key', ''),
                base_url=request.POST.get('base_url', '') or None,
                is_active=request.POST.get('is_active') == 'on',
                similarity_threshold=float(request.POST.get('similarity_threshold', 0.7)),
                candidate_threshold=float(request.POST.get('candidate_threshold', 0.5)),
                top_k_results=int(request.POST.get('top_k_results', 5))
            )
            config.full_clean()
            config.save()
            
            # If set as active, deactivate others
            if config.is_active:
                EmbeddingConfiguration.objects.exclude(pk=config.pk).update(is_active=False)
            
            messages.success(request, f"Embedding configuration '{config.model_name}' created successfully!")
            return redirect('extractor:semantic_search_settings')
            
        except Exception as e:
            log.error(f"Error creating embedding configuration: {e}")
            messages.error(request, f"Error creating configuration: {str(e)}")
    
    # Predefined model options — any dimension works; the vector column is
    # dimensionless and providers verify the model's real output against the
    # declared embedding_dimension.
    model_options = [
        {
            'name': 'NeuML/pubmedbert-base-embeddings',
            'provider': 'sentence-transformers',
            'dimension': 768,
            'description': 'PubMed biomedical embeddings, local'
        },
        {
            'name': 'FremyCompany/BioLORD-2023',
            'provider': 'sentence-transformers',
            'dimension': 768,
            'description': 'UMLS/SNOMED clinical terminology embeddings, local'
        },
        {
            'name': 'abhinand/MedEmbed-large-v0.1',
            'provider': 'sentence-transformers',
            'dimension': 1024,
            'description': 'Medical retrieval embeddings, local'
        },
        {
            'name': 'Alibaba-NLP/gte-Qwen2-1.5B-instruct',
            'provider': 'sentence-transformers',
            'dimension': 1536,
            'description': 'General-purpose, strong on medical terms, local (~3GB)'
        },
        {
            'name': 'text-embedding-3-small',
            'provider': 'openai',
            'dimension': 1536,
            'description': 'OpenAI embedding (requires API key)'
        },
        {
            'name': 'text-embedding-3-large',
            'provider': 'openai',
            'dimension': 1536,
            'description': 'OpenAI embedding, higher quality (requires API key)'
        },
    ]
    
    context = {
        'model_options': model_options,
    }
    
    return render(request, 'extractor/embedding_config_form.html', context)


@login_required
@permission_required('extractor.change_embeddingconfiguration', raise_exception=True)
@require_http_methods(["GET", "POST"])
def embedding_config_edit(request, config_id):
    """
    Edit an existing embedding configuration.
    """
    config = get_object_or_404(EmbeddingConfiguration, id=config_id)
    
    if request.method == 'POST':
        try:
            config.model_name = request.POST.get('model_name')
            config.model_provider = request.POST.get('model_provider')
            config.embedding_dimension = int(request.POST.get('embedding_dimension'))
            # Blank keeps the existing key — the form never echoes it back
            posted_key = request.POST.get('api_key', '')
            if posted_key:
                config.api_key = posted_key
            config.base_url = request.POST.get('base_url', '') or None
            config.is_active = request.POST.get('is_active') == 'on'
            config.similarity_threshold = float(request.POST.get('similarity_threshold', 0.7))
            config.candidate_threshold = float(request.POST.get('candidate_threshold', 0.5))
            config.top_k_results = int(request.POST.get('top_k_results', 5))
            config.full_clean()
            config.save()
            
            # If set as active, deactivate others
            if config.is_active:
                EmbeddingConfiguration.objects.exclude(pk=config.pk).update(is_active=False)
            
            messages.success(request, f"Configuration '{config.model_name}' updated successfully!")
            return redirect('extractor:semantic_search_settings')
            
        except Exception as e:
            log.error(f"Error updating embedding configuration: {e}")
            messages.error(request, f"Error updating configuration: {str(e)}")
    
    context = {
        'config': config,
        'is_edit': True,
    }
    
    return render(request, 'extractor/embedding_config_form.html', context)


@login_required
@permission_required('extractor.delete_embeddingconfiguration', raise_exception=True)
@require_http_methods(["POST"])
def embedding_config_delete(request, config_id):
    """
    Delete an embedding configuration.
    """
    config = get_object_or_404(EmbeddingConfiguration, id=config_id)
    config_name = config.model_name
    
    # Delete associated embeddings
    LookupEmbedding.objects.filter(embedding_config=config).delete()
    
    config.delete()
    messages.success(request, f"Configuration '{config_name}' and its embeddings deleted successfully!")
    
    return redirect('extractor:semantic_search_settings')


@login_required
@permission_required('extractor.change_embeddingconfiguration', raise_exception=True)
@require_http_methods(["POST"])
def embedding_config_activate(request, config_id):
    """
    Activate a specific embedding configuration.
    """
    config = get_object_or_404(EmbeddingConfiguration, id=config_id)
    
    # Deactivate all others
    EmbeddingConfiguration.objects.update(is_active=False)
    
    # Activate this one
    config.is_active = True
    config.save()
    
    messages.success(request, f"Configuration '{config.model_name}' is now active!")
    
    return redirect('extractor:semantic_search_settings')


@login_required
@permission_required('extractor.change_embeddingconfiguration', raise_exception=True)
@require_http_methods(["POST"])
def compute_embeddings(request):
    """
    Start embedding computation using threading + database tracking.
    """
    from extractor.tasks import compute_lookup_embeddings_task
    
    refresh = request.POST.get('refresh') == 'true'

    # Check if active config exists
    active_config = EmbeddingConfiguration.objects.filter(is_active=True).first()
    if not active_config:
        return JsonResponse({
            'success': False,
            'error': 'No active embedding configuration found. Please create and activate a configuration first.'
        })

    # Refuse a second run while one is in flight — but first sweep rows left
    # pending/running by a dead worker (e.g. after a Celery restart), which
    # would otherwise block every future run forever.
    inflight = BackgroundTask.objects.filter(
        task_name='Compute Lookup Embeddings', status__in=['pending', 'running']
    )
    if inflight.exists():
        if _inflight_embedding_tasks_alive(list(inflight.values_list('task_id', flat=True))):
            return JsonResponse({
                'success': False,
                'error': 'An embedding computation is already running.'
            })
        for stale in inflight:
            stale.mark_failed('Superseded: worker restarted or task lost before completing')

    try:
        # Create task tracker (progress UI polls this row)
        task_id = str(uuid.uuid4())
        BackgroundTask.objects.create(
            task_id=task_id,
            task_name='Compute Lookup Embeddings',
            status='pending'
        )

        # Dispatch to Celery
        compute_lookup_embeddings_task.delay(task_id, active_config.id, refresh)

        return JsonResponse({
            'success': True,
            'task_id': task_id,
            'message': 'Embedding computation started'
        })
        
    except Exception as e:
        log.error(f"Error starting embedding task: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@permission_required('extractor.view_backgroundtask', raise_exception=True)
def get_embedding_progress(request, task_id):
    """
    Get current progress of embedding computation task.
    """
    try:
        task = BackgroundTask.objects.get(task_id=task_id)
        
        response = {
            'status': task.status,
            'task_id': task.task_id,
            'current_step': task.current_step,
            'progress_percent': task.progress_percent,
            'processed_items': task.processed_items,
            'total_items': task.total_items,
        }
        
        if task.status == 'complete':
            response['result'] = task.result_data
            if task.result_data:
                response['message'] = f"Completed! Processed {task.result_data.get('total_processed', 0)} embeddings"
            else:
                response['message'] = 'Completed!'
        elif task.status == 'failed':
            response['error'] = task.error_message
            response['message'] = f'Failed: {task.error_message}'
        elif task.status == 'running':
            response['message'] = task.current_step or 'Computing embeddings...'
        else:
            response['message'] = 'Task pending...'
        
        return JsonResponse(response)
        
    except BackgroundTask.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'error': 'Task not found'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': str(e)
        })

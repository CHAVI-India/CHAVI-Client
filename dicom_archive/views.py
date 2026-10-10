"""Permission-scoped frontend views for the DICOM archive (plan 03).

Mirrors dicom_server/views.py: every view gates through
ArchivePermissionRequiredMixin on plain Django model permissions.
"""
import json
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from client_app.models import DICOMStudy, TaskRun
from dicom_archive.forms import ArchiveConfigurationForm, ArchiveLocationForm
from dicom_archive.models import ArchiveConfiguration, ArchiveLocation, ArchivedStudy
from dicom_archive.services.locations import test_location
from dicom_archive.tasks import archive_studies_task, dearchive_studies_task

logger = logging.getLogger(__name__)


class ArchivePermissionRequiredMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Anonymous -> login redirect; authenticated without the permission -> 403.

    Mirrors dicom_server.views.DicomPermissionRequiredMixin.
    """
    raise_exception = True

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect_to_login(
            self.request.get_full_path(),
            self.get_login_url(),
            self.get_redirect_field_name(),
        )


class ArchiveDashboardView(ArchivePermissionRequiredMixin, TemplateView):
    """Landing page: configuration status, default location, per-status
    counts, recent archived studies."""
    template_name = 'dicom_archive/dashboard.html'
    permission_required = 'dicom_archive.view_archiveconfiguration'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['config'] = ArchiveConfiguration.load()
        context['default_location'] = ArchiveLocation.objects.filter(
            is_active=True, is_default=True,
        ).order_by('-updated_at').first()
        counts = dict(ArchivedStudy.objects.values_list('status')
                      .annotate(count=Count('id'))
                      .values_list('status', 'count'))
        context['status_counts'] = counts
        context['total_records'] = sum(counts.values())
        context['in_flight_count'] = (
            counts.get(ArchivedStudy.Status.ARCHIVING, 0)
            + counts.get(ArchivedStudy.Status.DEARCHIVING, 0)
        )
        context['recent_archived'] = ArchivedStudy.objects.select_related(
            'study__patient', 'location', 'archived_by',
        )[:10]
        return context


class LocalStudyBrowserView(ArchivePermissionRequiredMixin, ListView):
    """Local DICOM studies (folder_path set) with their archive status
    (archive_record) and checkbox selection; ?q= filters patient ID or
    study UID."""
    model = DICOMStudy
    template_name = 'dicom_archive/browse.html'
    context_object_name = 'studies'
    permission_required = 'dicom_archive.view_archivedstudy'
    paginate_by = 25

    def get_queryset(self):
        qs = (
            DICOMStudy.objects.filter(folder_path__isnull=False)
            .select_related('patient', 'archive_record__location')
            .order_by('-created_at')
        )
        q = (self.request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(
                Q(patient__patient_id__icontains=q)
                | Q(study_instance_uid__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['locations'] = ArchiveLocation.objects.filter(is_active=True)
        context['query_string'] = self.request.GET.urlencode()
        return context


class ArchivedStudyListView(ArchivePermissionRequiredMixin, ListView):
    """Studies currently in an archive location, filterable by ?status=
    and ?location_id;. With no explicit ?status= the list defaults to
    ARCHIVED only (de-archived studies live locally again); picking
    "All statuses" (?status=) or a concrete status shows those records.
    Rows with status ARCHIVED carry a de-archive checkbox."""
    model = ArchivedStudy
    template_name = 'dicom_archive/archived_list.html'
    context_object_name = 'records'
    permission_required = 'dicom_archive.view_archivedstudy'
    paginate_by = 25

    def get_queryset(self):
        qs = ArchivedStudy.objects.select_related(
            'study__patient', 'location', 'archived_by',
        )
        if 'status' in self.request.GET:
            status = self.request.GET['status']
            if status in ArchivedStudy.Status.values:
                qs = qs.filter(status=status)
        else:
            qs = qs.filter(status=ArchivedStudy.Status.ARCHIVED)
        location_id = self.request.GET.get('location_id')
        if location_id:
            qs = qs.filter(location_id=location_id)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_choices'] = ArchivedStudy.Status.choices
        context['locations'] = ArchiveLocation.objects.all()
        context['active_status'] = (
            self.request.GET['status']
            if 'status' in self.request.GET
            else ArchivedStudy.Status.ARCHIVED
        )
        context['query_string'] = self.request.GET.urlencode()
        return context


# --- Configuration (archive config permission) ---

class ArchiveConfigUpdateView(ArchivePermissionRequiredMixin, UpdateView):
    model = ArchiveConfiguration
    form_class = ArchiveConfigurationForm
    template_name = 'dicom_archive/config_edit.html'
    permission_required = 'dicom_archive.change_archiveconfiguration'
    success_url = reverse_lazy('dicom_archive:dashboard')

    def get_object(self, queryset=None):
        return ArchiveConfiguration.load()

    def form_valid(self, form):
        messages.success(self.request, 'DICOM archive configuration saved.')
        return super().form_valid(form)


# --- Locations (location permissions) ---

class ArchiveLocationListView(ArchivePermissionRequiredMixin, ListView):
    model = ArchiveLocation
    template_name = 'dicom_archive/location_list.html'
    context_object_name = 'locations'
    permission_required = 'dicom_archive.view_archivelocation'

    def get_queryset(self):
        return ArchiveLocation.objects.annotate(
            study_count=Count('archived_studies'),
        ).order_by('name')


class ArchiveLocationCreateView(ArchivePermissionRequiredMixin, CreateView):
    model = ArchiveLocation
    form_class = ArchiveLocationForm
    template_name = 'dicom_archive/location_form.html'
    permission_required = 'dicom_archive.add_archivelocation'
    success_url = reverse_lazy('dicom_archive:location_list')

    def form_valid(self, form):
        messages.success(
            self.request,
            f'Archive location "{form.instance.name}" created.')
        return super().form_valid(form)


class ArchiveLocationUpdateView(ArchivePermissionRequiredMixin, UpdateView):
    model = ArchiveLocation
    form_class = ArchiveLocationForm
    template_name = 'dicom_archive/location_form.html'
    permission_required = 'dicom_archive.change_archivelocation'
    success_url = reverse_lazy('dicom_archive:location_list')

    def form_valid(self, form):
        messages.success(
            self.request,
            f'Archive location "{form.instance.name}" updated.')
        return super().form_valid(form)


class ArchiveLocationDeleteView(ArchivePermissionRequiredMixin, View):
    """POST-only delete (the list page confirms client-side; the contract's
    template set has no delete-confirm page). A location that still holds
    ArchivedStudy rows is refused with a flash instead of a PROTECT error."""
    permission_required = 'dicom_archive.delete_archivelocation'

    def get(self, request, pk):
        return redirect('dicom_archive:location_list')

    def post(self, request, pk):
        location = get_object_or_404(ArchiveLocation, pk=pk)
        if ArchivedStudy.objects.filter(location=location).exists():
            messages.error(request, (
                f'"{location.name}" still holds archived studies and cannot '
                'be deleted. De-archive or move them first.'
            ))
        else:
            name = location.name
            location.delete()
            messages.success(
                request, f'Archive location "{name}" deleted.')
        return redirect('dicom_archive:location_list')


class LocationTestView(ArchivePermissionRequiredMixin, View):
    """POST JSON — live probe of an archive location (no Celery, no status
    changes). Accepts ``{location_id}`` (saved location) or
    ``{storage_type, path}`` (unsaved form values). Writes a small
    persistent verification file into the location so the user can confirm
    on the share that the write really landed there."""
    permission_required = 'dicom_archive.view_archivelocation'

    def post(self, request):
        payload, error = _json_payload(request)
        if error:
            return error
        location_id = payload.get('location_id')
        if location_id is not None:
            location = ArchiveLocation.objects.filter(pk=location_id).first()
            if location is None:
                return JsonResponse(
                    {'error': f'unknown location_id {location_id!r}'},
                    status=404,
                )
        else:
            storage_type = (payload.get('storage_type') or '').strip()
            path = (payload.get('path') or '').strip()
            if storage_type not in ArchiveLocation.StorageType.values or not path:
                return JsonResponse({
                    'error': 'Provide location_id, or storage_type and path.',
                }, status=400)
            location = ArchiveLocation(
                storage_type=storage_type, path=path, name='_probe_',
            )
        return JsonResponse(test_location(location))


# --- Manual triggers (JSON dispatch, BulkDeidentifyView response shape) ---

def _json_payload(request):
    """(payload, error_response) — same helper shape as dicom_server.views."""
    try:
        return json.loads(request.body or '{}'), None
    except json.JSONDecodeError:
        return None, JsonResponse({'error': 'Invalid JSON body'}, status=400)


class ManualArchiveView(ArchivePermissionRequiredMixin, View):
    """POST JSON {study_uids: [...], location_id: int} ->
    archive_studies_task.delay; response {task_id, redirect_url, message}."""
    permission_required = 'dicom_archive.add_archivedstudy'

    def post(self, request):
        payload, error = _json_payload(request)
        if error:
            return error
        study_uids = payload.get('study_uids')
        if not isinstance(study_uids, list) or not study_uids:
            return JsonResponse(
                {'error': 'study_uids must be a non-empty list'}, status=400)
        location = ArchiveLocation.objects.filter(
            pk=payload.get('location_id'), is_active=True,
        ).first()
        if location is None:
            return JsonResponse(
                {'error': 'location_id must reference an active '
                          'archive location'},
                status=400,
            )
        known = set(DICOMStudy.objects.filter(
            study_instance_uid__in=study_uids, folder_path__isnull=False,
        ).values_list('study_instance_uid', flat=True))
        unknown = [u for u in study_uids if u not in known]
        if unknown:
            return JsonResponse(
                {'error': 'unknown or non-local study UID(s): '
                           + ', '.join(unknown[:5])},
                status=400,
            )
        try:
            result = archive_studies_task.delay(
                study_uids, location.pk,
                user_id=request.user.pk, reason='MANUAL',
            )
        except Exception:
            logger.exception('Failed to dispatch archive_studies_task')
            return JsonResponse(
                {'error': 'Could not dispatch archive task'}, status=500)
        return JsonResponse({
            'task_id': result.id,
            'redirect_url': reverse('client_app:taskrun_list'),
            'message': f'Archiving {len(study_uids)} study(s) to '
                       f'"{location.name}" in the background.',
        })


class ManualDearchiveView(ArchivePermissionRequiredMixin, View):
    """POST JSON {study_uids: [...]} -> dearchive_studies_task.delay;
    every UID must have an ArchivedStudy in status ARCHIVED."""
    permission_required = 'dicom_archive.add_archivedstudy'

    def post(self, request):
        payload, error = _json_payload(request)
        if error:
            return error
        study_uids = payload.get('study_uids')
        if not isinstance(study_uids, list) or not study_uids:
            return JsonResponse(
                {'error': 'study_uids must be a non-empty list'}, status=400)
        archived = set(ArchivedStudy.objects.filter(
            study__study_instance_uid__in=study_uids,
            status=ArchivedStudy.Status.ARCHIVED,
        ).values_list('study__study_instance_uid', flat=True))
        unknown = [u for u in study_uids if u not in archived]
        if unknown:
            return JsonResponse(
                {'error': 'no archived study found for UID(s): '
                           + ', '.join(unknown[:5])},
                status=400,
            )
        try:
            result = dearchive_studies_task.delay(
                study_uids, user_id=request.user.pk,
            )
        except Exception:
            logger.exception('Failed to dispatch dearchive_studies_task')
            return JsonResponse(
                {'error': 'Could not dispatch de-archive task'}, status=500)
        return JsonResponse({
            'task_id': result.id,
            'redirect_url': reverse('client_app:taskrun_list'),
            'message': f'De-archiving {len(study_uids)} study(s) in the '
                       'background.',
        })


class TaskStatusView(ArchivePermissionRequiredMixin, View):
    """GET — poll endpoint over client_app.TaskRun. task_run_id may be a
    TaskRun pk or the celery task id (TaskRun.task_id) returned by the
    trigger views; 404 until the task has created its TaskRun row."""
    permission_required = 'dicom_archive.view_archivedstudy'

    def get(self, request, task_run_id):
        try:
            run = TaskRun.objects.filter(pk=task_run_id).first()
        except ValueError:
            run = None  # task_run_id is not an integer pk
        if run is None:
            run = TaskRun.objects.filter(task_id=task_run_id).first()
        if run is None:
            return JsonResponse({'error': 'task run not found'}, status=404)
        return JsonResponse({
            'task_run_id': run.pk,
            'task_id': run.task_id,
            'task_name': run.task_name,
            'task_type': run.task_type,
            'status': run.status,
            'progress_current': run.progress_current,
            'progress_total': run.progress_total,
            'progress_percent': run.progress_percent,
            'progress_description': run.progress_description,
            'result_summary': run.result_summary,
            'error_log': run.error_log or '',
            'completed_at': (
                run.completed_at.isoformat() if run.completed_at else None
            ),
        })

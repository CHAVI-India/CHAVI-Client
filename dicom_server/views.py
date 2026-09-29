import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import (
    TemplateView, ListView, CreateView, UpdateView, DeleteView,
    DetailView, FormView,
)

from dicom_server.forms import (
    DICOMServerConfigForm, RemoteDICOMNodeForm, RetrieveStudiesForm,
)
from dicom_server.models import (
    DICOMServerConfiguration, RemoteDICOMNode, InboundDICOMInstance,
    PatientIDAlias, RetrievalJob,
)
from dicom_server.services import qr_client
from dicom_server.tasks import task_retrieve_studies

logger = logging.getLogger(__name__)


class DicomPermissionRequiredMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Anonymous → login redirect; authenticated without the permission → 403."""
    raise_exception = True

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect_to_login(
            self.request.get_full_path(),
            self.get_login_url(),
            self.get_redirect_field_name(),
        )


class DashboardView(DicomPermissionRequiredMixin, TemplateView):
    template_name = 'dicom_server/dashboard.html'
    permission_required = 'dicom_server.view_remotedicomnode'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['config'] = DICOMServerConfiguration.load()
        context['nodes'] = RemoteDICOMNode.objects.all()[:10]
        context['recent_inbound'] = (
            InboundDICOMInstance.objects.select_related('matched_patient')[:20]
        )
        context['recent_jobs'] = (
            RetrievalJob.objects.select_related('node', 'patient', 'created_by')[:10]
        )
        return context


# --- Configuration (server config permission) ---

class ConfigUpdateView(DicomPermissionRequiredMixin, UpdateView):
    model = DICOMServerConfiguration
    form_class = DICOMServerConfigForm
    template_name = 'dicom_server/config_form.html'
    permission_required = 'dicom_server.change_dicomserverconfiguration'
    success_url = reverse_lazy('dicom_server:dashboard')

    def get_object(self, queryset=None):
        return DICOMServerConfiguration.load()

    def form_valid(self, form):
        messages.success(self.request, 'DICOM server configuration saved.')
        return super().form_valid(form)


class RemoteNodeListView(DicomPermissionRequiredMixin, ListView):
    model = RemoteDICOMNode
    template_name = 'dicom_server/node_list.html'
    permission_required = 'dicom_server.view_remotedicomnode'
    context_object_name = 'nodes'


class RemoteNodeCreateView(DicomPermissionRequiredMixin, CreateView):
    model = RemoteDICOMNode
    form_class = RemoteDICOMNodeForm
    template_name = 'dicom_server/node_form.html'
    permission_required = 'dicom_server.add_remotedicomnode'
    success_url = reverse_lazy('dicom_server:node_list')

    def form_valid(self, form):
        messages.success(self.request, 'Remote node created.')
        return super().form_valid(form)


class RemoteNodeUpdateView(DicomPermissionRequiredMixin, UpdateView):
    model = RemoteDICOMNode
    form_class = RemoteDICOMNodeForm
    template_name = 'dicom_server/node_form.html'
    permission_required = 'dicom_server.change_remotedicomnode'
    success_url = reverse_lazy('dicom_server:node_list')

    def form_valid(self, form):
        messages.success(self.request, 'Remote node updated.')
        return super().form_valid(form)


class RemoteNodeDeleteView(DicomPermissionRequiredMixin, DeleteView):
    model = RemoteDICOMNode
    template_name = 'dicom_server/node_confirm_delete.html'
    permission_required = 'dicom_server.delete_remotedicomnode'
    success_url = reverse_lazy('dicom_server:node_list')

    def form_valid(self, form):
        messages.success(self.request, 'Remote node deleted.')
        return super().form_valid(form)


class RemoteNodeEchoView(DicomPermissionRequiredMixin, View):
    permission_required = 'dicom_server.view_remotedicomnode'

    def post(self, request, pk):
        node = get_object_or_404(RemoteDICOMNode, pk=pk)
        try:
            ok, reason = qr_client.echo(node)
        except Exception as e:
            logger.exception('C-ECHO to %s failed', node)
            messages.error(request, f'{node}: C-ECHO failed — {e}')
        else:
            if ok:
                messages.success(request, f'{node}: C-ECHO succeeded')
            else:
                messages.error(request, f'{node}: C-ECHO failed — {reason}')
        return redirect('dicom_server:node_list')


class RemoteNodeCapabilitiesView(DicomPermissionRequiredMixin, View):
    """POST: probe which Q/R services (C-FIND/C-MOVE/C-GET) a remote node
    actually supports, then report the result as a flash message."""
    permission_required = 'dicom_server.view_remotedicomnode'

    def post(self, request, pk):
        node = get_object_or_404(RemoteDICOMNode, pk=pk)
        try:
            caps = qr_client.probe_qr_capabilities(node)
        except Exception as e:
            logger.exception('Q/R capability probe of %s failed', node)
            messages.error(request, f'{node}: capability check failed — {e}')
            return redirect('dicom_server:node_list')
        if caps.get('error'):
            messages.error(request, f'{node}: {caps["error"]}')
            return redirect('dicom_server:node_list')

        def _fmt(value):
            return {
                'study': '✓',
                'patient': '✓ (Patient Root)',
                'broken': 'negotiated but aborts queries',
            }.get(value, '✗')

        summary = (
            f'C-FIND {_fmt(caps["find"])} · '
            f'C-MOVE {_fmt(caps["move"])} · '
            f'C-GET {_fmt(caps["get"])}'
        )
        if caps['find'] == 'broken':
            hint = (
                ' — it negotiates C-FIND but aborts queries: likely a '
                'storage-only node (e.g. a treatment machine); it can '
                'receive pushed studies but cannot be queried'
            )
        elif node.prefer_c_get and not caps['get']:
            hint = (
                ' — this node is set to C-GET but the peer does not support '
                'it; switch the node to C-MOVE or retrieval will fail'
            )
        elif not node.prefer_c_get and not caps['move']:
            hint = (
                ' — this node is set to C-MOVE but the peer does not support '
                'it; enable "Prefer C-GET" or retrieval will fail'
            )
        elif caps['get'] and not caps['get_storage']:
            hint = (
                ' — the peer accepts C-GET but no storage contexts with us '
                'as receiver; C-GET delivery may still fail'
            )
        else:
            hint = ''
        messages.info(request, f'{node}: {summary}{hint}')
        return redirect('dicom_server:node_list')


# --- Query/Retrieve (retrieval job permissions) ---

class RetrieveStudiesView(DicomPermissionRequiredMixin, FormView):
    template_name = 'dicom_server/retrieve.html'
    form_class = RetrieveStudiesForm
    permission_required = 'dicom_server.add_retrievaljob'

    def form_valid(self, form):
        node = form.cleaned_data['node']
        patient = form.cleaned_data['patient']
        job = RetrievalJob.objects.create(
            node=node, patient=patient, created_by=self.request.user,
        )
        aliases = list(
            PatientIDAlias.objects.filter(node=node, patient=patient)
            .values_list('remote_patient_id', flat=True)
        )
        try:
            result = task_retrieve_studies.delay(
                node.pk, patient.patient_id, self.request.user.pk, job.pk,
                patient_id_aliases=aliases,
            )
            job.celery_task_id = result.id or ''
            job.save(update_fields=['celery_task_id'])
            messages.success(self.request, f'Retrieval job {job.pk} started.')
        except Exception as e:
            logger.exception('Failed to dispatch retrieval task')
            job.status = RetrievalJob.Status.FAILED
            job.error_log = f'Failed to dispatch task: {e}'
            job.save(update_fields=['status', 'error_log'])
            messages.error(self.request, f'Could not dispatch retrieval task: {e}')
        return redirect('dicom_server:job_detail', pk=job.pk)


class RetrievalJobListView(DicomPermissionRequiredMixin, ListView):
    model = RetrievalJob
    template_name = 'dicom_server/job_list.html'
    permission_required = 'dicom_server.view_retrievaljob'
    context_object_name = 'jobs'
    paginate_by = 25


class RetrievalJobDetailView(DicomPermissionRequiredMixin, DetailView):
    model = RetrievalJob
    template_name = 'dicom_server/job_detail.html'
    permission_required = 'dicom_server.view_retrievaljob'
    context_object_name = 'job'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        uids = []
        if self.object.studies_found:
            uids = [
                s.get('study_instance_uid')
                for s in self.object.studies_found
                if s.get('study_instance_uid')
            ]
        context['instances'] = (
            InboundDICOMInstance.objects.filter(study_instance_uid__in=uids)
            if uids else []
        )
        return context

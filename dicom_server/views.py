import logging

from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
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


class StaffRequiredMixin(AccessMixin):
    """Staff-only pages: anonymous → login redirect; non-staff → 403."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_staff:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class QRPermissionMixin(AccessMixin):
    """Q/R pages: login + client_app.add_dicomstudy permission."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.has_perm('client_app.add_dicomstudy'):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class DashboardView(QRPermissionMixin, TemplateView):
    template_name = 'dicom_server/dashboard.html'

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


# --- Configuration (staff only) ---

class ConfigUpdateView(StaffRequiredMixin, UpdateView):
    model = DICOMServerConfiguration
    form_class = DICOMServerConfigForm
    template_name = 'dicom_server/config_form.html'
    success_url = reverse_lazy('dicom_server:dashboard')

    def get_object(self, queryset=None):
        return DICOMServerConfiguration.load()

    def form_valid(self, form):
        messages.success(self.request, 'DICOM server configuration saved.')
        return super().form_valid(form)


class RemoteNodeListView(StaffRequiredMixin, ListView):
    model = RemoteDICOMNode
    template_name = 'dicom_server/node_list.html'
    context_object_name = 'nodes'


class RemoteNodeCreateView(StaffRequiredMixin, CreateView):
    model = RemoteDICOMNode
    form_class = RemoteDICOMNodeForm
    template_name = 'dicom_server/node_form.html'
    success_url = reverse_lazy('dicom_server:node_list')

    def form_valid(self, form):
        messages.success(self.request, 'Remote node created.')
        return super().form_valid(form)


class RemoteNodeUpdateView(StaffRequiredMixin, UpdateView):
    model = RemoteDICOMNode
    form_class = RemoteDICOMNodeForm
    template_name = 'dicom_server/node_form.html'
    success_url = reverse_lazy('dicom_server:node_list')

    def form_valid(self, form):
        messages.success(self.request, 'Remote node updated.')
        return super().form_valid(form)


class RemoteNodeDeleteView(StaffRequiredMixin, DeleteView):
    model = RemoteDICOMNode
    template_name = 'dicom_server/node_confirm_delete.html'
    success_url = reverse_lazy('dicom_server:node_list')

    def form_valid(self, form):
        messages.success(self.request, 'Remote node deleted.')
        return super().form_valid(form)


class RemoteNodeEchoView(StaffRequiredMixin, View):
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


# --- Query/Retrieve (add_dicomstudy permission) ---

class RetrieveStudiesView(QRPermissionMixin, FormView):
    template_name = 'dicom_server/retrieve.html'
    form_class = RetrieveStudiesForm

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


class RetrievalJobListView(QRPermissionMixin, ListView):
    model = RetrievalJob
    template_name = 'dicom_server/job_list.html'
    context_object_name = 'jobs'
    paginate_by = 25


class RetrievalJobDetailView(QRPermissionMixin, DetailView):
    model = RetrievalJob
    template_name = 'dicom_server/job_detail.html'
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

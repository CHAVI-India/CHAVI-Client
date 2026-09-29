import json
import logging

from celery import chord, group
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Q, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.datastructures import MultiValueDict
from django.views import View
from django.views.generic import (
    TemplateView, ListView, CreateView, UpdateView, DeleteView,
    DetailView, FormView,
)

from client_app.models import Diagnosis, Patient, Project
from dicom_server.forms import (
    BulkRetrieveForm, DICOMServerConfigForm, RemoteDICOMNodeForm,
    RetrieveStudiesForm,
)
from dicom_server.models import (
    DICOMServerConfiguration, RemoteDICOMNode, InboundDICOMInstance,
    PatientIDAlias, RetrievalBatch, RetrievalBatchPatient, RetrievalJob,
)
from dicom_server.services import patient_ids, qr_client
from lookup.models import (
    LookupDiagnosticModality, LookupFMACode, LookupICDCode,
    LookupLaterality, LookupMajorCancerCategory, LookupPresentation,
)
from dicom_server.tasks import (
    task_finalize_batch_query, task_finalize_retrieval_batch,
    task_query_patient_studies, task_retrieve_patient_selection,
    task_retrieve_studies,
)

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
        aliases = node.remote_patient_ids_for(patient)
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


# --- Bulk retrieval (multi-patient query + chord retrieval) ---

def _json_payload(request):
    try:
        return json.loads(request.body or '{}'), None
    except json.JSONDecodeError:
        return None, JsonResponse({'error': 'Invalid JSON body'}, status=400)


class BulkRetrieveView(DicomPermissionRequiredMixin, FormView):
    """Multi-patient bulk retrieval UI: node + patients -> background C-FIND
    -> study/series selection tree -> chord of per-patient retrieval jobs."""
    template_name = 'dicom_server/retrieve_bulk.html'
    form_class = BulkRetrieveForm
    permission_required = 'dicom_server.add_retrievaljob'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['node_transforms'] = json.dumps({
            str(n.pk): n.patient_id_transforms or []
            for n in context['form'].fields['node'].queryset
        })
        context['genders'] = Patient.Gender.choices
        context['projects'] = (
            Project.objects.order_by('project_name')
            .values_list('chavi_project_id', 'project_name')
        )
        context['cancer_systems'] = (
            LookupMajorCancerCategory.objects.order_by('label')
            .values_list('code', 'label')
        )
        context['sides'] = (
            LookupLaterality.objects.order_by('label')
            .values_list('code', 'label')
        )
        context['presentations'] = (
            LookupPresentation.objects.order_by('label')
            .values_list('code', 'label')
        )
        context['diag_modalities'] = (
            LookupDiagnosticModality.objects.order_by('label')
            .values_list('code', 'label')
        )
        return context


class BulkLookupSearchView(DicomPermissionRequiredMixin, View):
    """GET — select2-compatible lookup search for large lookup tables.
    ?kind=icd|site&q=<term>&page=<n> -> {results, pagination:{more}}"""
    permission_required = 'dicom_server.add_retrievaljob'
    per_page = 30

    MODELS = {
        'icd': LookupICDCode,
        'site': LookupFMACode,
    }

    def get(self, request):
        model = self.MODELS.get(request.GET.get('kind'))
        if model is None:
            return JsonResponse({'error': 'unknown lookup kind'}, status=400)
        qs = model.objects.order_by('label')
        q = (request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(label__icontains=q) | Q(code__icontains=q))
        try:
            page_no = max(1, int(request.GET.get('page', 1)))
        except (TypeError, ValueError):
            page_no = 1
        start = (page_no - 1) * self.per_page
        rows = list(qs[start:start + self.per_page])
        return JsonResponse({
            'results': [
                {'id': r.code, 'text': f'{r.code} — {r.label}'}
                for r in rows
            ],
            'pagination': {'more': qs.count() > start + len(rows)},
        })


class BulkPatientListView(DicomPermissionRequiredMixin, View):
    """GET — paginated patient table for the bulk picker.

    Params: q, gender, project, diagnosis (ICD code), cancer_system (code),
    cancer_site (FMA code), cancer_side (code), presentation (code),
    modality (code), created_from/to, updated_from/to, consented,
    ids_only=1, page. Lookup-backed filters take exact codes selected via
    select2 so labels map precisely. Rows carry per-diagnosis detail so
    every listed field is both displayable and filterable."""
    permission_required = 'dicom_server.add_retrievaljob'
    per_page = 20

    def get(self, request):
        qs = Patient.objects.all()

        q = (request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(
                Q(patient_id__icontains=q)
                | Q(canonical_patient_id__icontains=q)
            )
        if request.GET.get('gender'):
            qs = qs.filter(gender=request.GET['gender'])
        if request.GET.get('project'):
            qs = qs.filter(patient_project__pk=request.GET['project'])
        if request.GET.get('diagnosis'):
            qs = qs.filter(diagnosis__diagnosis__code=request.GET['diagnosis'])
        if request.GET.get('cancer_system'):
            qs = qs.filter(
                diagnosis__cancer_system__code=request.GET['cancer_system'])
        if request.GET.get('cancer_site'):
            qs = qs.filter(
                diagnosis__cancer_site__code=request.GET['cancer_site'])
        if request.GET.get('cancer_side'):
            qs = qs.filter(diagnosis__cancer_side__code=request.GET['cancer_side'])
        if request.GET.get('presentation'):
            qs = qs.filter(
                diagnosis__presentation_type__code=request.GET['presentation'])
        if request.GET.get('modality'):
            qs = qs.filter(
                diagnosis__diagnostic_modality__code=request.GET['modality'])
        if request.GET.get('created_from'):
            qs = qs.filter(created_at__date__gte=request.GET['created_from'])
        if request.GET.get('created_to'):
            qs = qs.filter(created_at__date__lte=request.GET['created_to'])
        if request.GET.get('updated_from'):
            qs = qs.filter(updated_at__date__gte=request.GET['updated_from'])
        if request.GET.get('updated_to'):
            qs = qs.filter(updated_at__date__lte=request.GET['updated_to'])
        if request.GET.get('consented') != '0':
            qs = qs.filter(chavi_consent=True)

        qs = qs.distinct().order_by('patient_id')
        if request.GET.get('ids_only') == '1':
            # Bulk-select helper — only consented patients are selectable.
            return JsonResponse({'ids': list(
                qs.filter(chavi_consent=True)
                .values_list('patient_id', flat=True)
            )})

        qs = qs.prefetch_related(
            'patient_project',
            Prefetch(
                'diagnosis_set',
                queryset=Diagnosis.objects.select_related(
                    'cancer_system', 'diagnosis', 'presentation_type',
                    'cancer_site', 'cancer_side', 'diagnostic_modality',
                ),
            ),
        )

        paginator = Paginator(qs, self.per_page)
        try:
            page = paginator.page(request.GET.get('page', 1))
        except (PageNotAnInteger, EmptyPage):
            page = paginator.page(1)

        rows = []
        for p in page.object_list:
            rows.append({
                'patient_id': p.patient_id,
                'gender': p.gender or '',
                'consented': bool(p.chavi_consent),
                'projects': [pr.project_name for pr in p.patient_project.all()],
                'created_at': p.created_at.strftime('%Y-%m-%d'),
                'updated_at': p.updated_at.strftime('%Y-%m-%d'),
                'diagnoses': [{
                    'system': d.cancer_system.label if d.cancer_system else '',
                    'icd': d.diagnosis.label if d.diagnosis else '',
                    'icd_code': d.diagnosis.code if d.diagnosis else '',
                    'site': d.cancer_site.label if d.cancer_site else '',
                    'side': d.cancer_side.label if d.cancer_side else '',
                    'presentation': (
                        d.presentation_type.label if d.presentation_type else ''
                    ),
                    'modality': (
                        d.diagnostic_modality.label
                        if d.diagnostic_modality else ''
                    ),
                    'date': str(d.diagnosis_date or ''),
                } for d in p.diagnosis_set.all()],
            })
        return JsonResponse({
            'results': rows,
            'page': page.number,
            'pages': paginator.num_pages,
            'total': paginator.count,
        })


class BatchQueryView(DicomPermissionRequiredMixin, View):
    """POST {node, patients[], extra_transforms} — create a RetrievalBatch and
    dispatch the per-patient C-FIND task group."""
    permission_required = 'dicom_server.add_retrievaljob'

    def post(self, request):
        payload, error = _json_payload(request)
        if error:
            return error
        data = MultiValueDict()
        if payload.get('node') is not None:
            data['node'] = str(payload['node'])
        data.setlist('patients', [str(p) for p in payload.get('patients', [])])
        data['extra_transforms'] = payload.get('extra_transforms', '') or ''
        form = BulkRetrieveForm(data)
        if not form.is_valid():
            return JsonResponse({'error': '; '.join(
                f'{k}: {", ".join(map(str, v))}'
                for k, v in form.errors.items()
            )}, status=400)

        batch = RetrievalBatch.objects.create(
            node=form.cleaned_data['node'],
            created_by=request.user,
            extra_transforms=form.cleaned_data['extra_transforms'],
        )
        patients = list(form.cleaned_data['patients'])
        RetrievalBatchPatient.objects.bulk_create(
            RetrievalBatchPatient(batch=batch, patient=p) for p in patients
        )
        try:
            header = group(
                task_query_patient_studies.s(batch.pk, p.patient_id)
                for p in patients
            )
            result = chord(header)(task_finalize_batch_query.s(batch.pk))
            batch.query_group_id = str(result.id or '')
            batch.save(update_fields=['query_group_id'])
        except Exception as e:
            logger.exception('Failed to dispatch bulk query tasks')
            batch.status = RetrievalBatch.Status.FAILED
            batch.summary = {'error': f'Failed to dispatch query tasks: {e}'}
            batch.completed_at = timezone.now()
            batch.save(update_fields=['status', 'summary', 'completed_at'])
            return JsonResponse(
                {'error': f'Could not dispatch query tasks: {e}'}, status=500,
            )
        return JsonResponse({'batch_id': batch.pk})


class BatchStatusView(DicomPermissionRequiredMixin, View):
    """GET — poll endpoint for the query phase; returns batch status plus the
    per-patient query results tree the page re-renders each poll."""
    permission_required = 'dicom_server.view_retrievaljob'

    def get(self, request, pk):
        batch = get_object_or_404(RetrievalBatch, pk=pk)
        patients = [{
            'id': item.pk,
            'patient_id': item.patient_id,
            'query_status': item.query_status,
            'error': item.error,
            'remote_patient_ids': item.remote_patient_ids,
            'studies': item.studies or [],
        } for item in batch.patients.all()]
        return JsonResponse({'status': batch.status, 'patients': patients})


class PatientAliasCreateView(DicomPermissionRequiredMixin, View):
    """POST {patient_id, remote_patient_id} — save a remote-ID alias for this
    batch's node (usable by this query, auto-retrieval and ingest matching)."""
    permission_required = 'dicom_server.add_retrievaljob'

    def post(self, request, pk):
        batch = get_object_or_404(RetrievalBatch, pk=pk)
        payload, error = _json_payload(request)
        if error:
            return error
        remote_id = (payload.get('remote_patient_id') or '').strip()
        if not remote_id:
            return JsonResponse(
                {'error': 'remote_patient_id is required'}, status=400,
            )
        patient = get_object_or_404(Patient, patient_id=payload.get('patient_id'))
        existing = PatientIDAlias.objects.filter(
            node=batch.node, remote_patient_id=remote_id,
        ).first()
        if existing and existing.patient_id != patient.patient_id:
            return JsonResponse({'error': (
                f'{remote_id} is already an alias for '
                f'{existing.patient_id} on this node'
            )}, status=409)
        PatientIDAlias.objects.get_or_create(
            node=batch.node, patient=patient, remote_patient_id=remote_id,
        )
        return JsonResponse({'ok': True})


class PatientRequeryView(DicomPermissionRequiredMixin, View):
    """POST {patient_id} — re-run the C-FIND task for one batch patient
    (e.g. after adding an alias)."""
    permission_required = 'dicom_server.add_retrievaljob'

    def post(self, request, pk):
        batch = get_object_or_404(RetrievalBatch, pk=pk)
        payload, error = _json_payload(request)
        if error:
            return error
        item = get_object_or_404(
            RetrievalBatchPatient, batch=batch,
            patient_id=payload.get('patient_id'),
        )
        item.query_status = RetrievalBatchPatient.QueryStatus.PENDING
        item.error = ''
        item.studies = None
        item.save(update_fields=['query_status', 'error', 'studies'])
        batch.status = RetrievalBatch.Status.QUERYING
        batch.save(update_fields=['status'])
        try:
            header = group([task_query_patient_studies.s(batch.pk, item.patient_id)])
            chord(header)(task_finalize_batch_query.s(batch.pk))
        except Exception as e:
            logger.exception('Failed to dispatch re-query task')
            return JsonResponse(
                {'error': f'Could not dispatch query task: {e}'}, status=500,
            )
        return JsonResponse({'ok': True})


class BatchRetrieveView(DicomPermissionRequiredMixin, View):
    """POST {selections: {patient_id: [{study_instance_uid,
    series_instance_uids|null}]}} — create one RetrievalJob per selected
    patient and dispatch the retrieval chord."""
    permission_required = 'dicom_server.add_retrievaljob'

    def post(self, request, pk):
        batch = get_object_or_404(RetrievalBatch, pk=pk)
        if batch.status != RetrievalBatch.Status.AWAITING_SELECTION:
            return JsonResponse({'error': (
                f'Batch is not awaiting selection (status: {batch.get_status_display()})'
            )}, status=409)
        payload, error = _json_payload(request)
        if error:
            return error
        selections = payload.get('selections') or {}
        items_by_pid = {
            item.patient_id: item
            for item in batch.patients.select_related('patient')
        }
        jobs = []
        for pid, sel in selections.items():
            item = items_by_pid.get(pid)
            if item is None or not sel:
                continue
            known = {
                s.get('study_instance_uid'): s
                for s in (item.studies or []) if s.get('study_instance_uid')
            }
            normalized = []
            found_subset = []
            for entry in sel:
                suid = (entry or {}).get('study_instance_uid')
                study = known.get(suid)
                if study is None:
                    return JsonResponse({'error': (
                        f'{pid}: unknown study UID {suid!r} — re-query first'
                    )}, status=400)
                series_req = entry.get('series_instance_uids')
                if series_req is not None:
                    if not isinstance(series_req, list) or not series_req:
                        return JsonResponse({'error': (
                            f'{pid}: series_instance_uids must be a non-empty '
                            'list or null'
                        )}, status=400)
                    known_series = {
                        s.get('series_instance_uid')
                        for s in (study.get('series') or [])
                    }
                    unknown = set(series_req) - known_series
                    if unknown:
                        return JsonResponse({'error': (
                            f'{pid}: unknown series UID(s) {sorted(unknown)} '
                            f'for study {suid}'
                        )}, status=400)
                normalized.append({
                    'study_instance_uid': suid,
                    'series_instance_uids': series_req,
                    'remote_patient_id': study.get('remote_patient_id'),
                })
                found_subset.append(study)
            if not normalized:
                continue
            job = RetrievalJob.objects.create(
                node=batch.node, patient=item.patient,
                created_by=request.user, selections=normalized,
                studies_found=found_subset, batch=batch,
            )
            item.selected = True
            item.job = job
            item.save(update_fields=['selected', 'job'])
            jobs.append(job)
        if not jobs:
            return JsonResponse({'error': 'Nothing selected'}, status=400)

        batch.status = RetrievalBatch.Status.RETRIEVING
        batch.save(update_fields=['status'])
        try:
            header = group(
                task_retrieve_patient_selection.s(j.pk) for j in jobs
            )
            result = chord(header)(task_finalize_retrieval_batch.s(batch.pk))
            batch.retrieve_group_id = str(result.id or '')
            batch.save(update_fields=['retrieve_group_id'])
        except Exception as e:
            logger.exception('Failed to dispatch bulk retrieval chord')
            batch.status = RetrievalBatch.Status.FAILED
            batch.summary = {'error': f'Failed to dispatch retrieval tasks: {e}'}
            batch.completed_at = timezone.now()
            batch.save(update_fields=['status', 'summary', 'completed_at'])
            return JsonResponse(
                {'error': f'Could not dispatch retrieval tasks: {e}'},
                status=500,
            )
        return JsonResponse({
            'ok': True,
            'detail_url': reverse('dicom_server:batch_detail', args=[batch.pk]),
        })


class BatchListView(DicomPermissionRequiredMixin, ListView):
    model = RetrievalBatch
    template_name = 'dicom_server/batch_list.html'
    permission_required = 'dicom_server.view_retrievaljob'
    context_object_name = 'batches'
    paginate_by = 25


class BatchDetailView(DicomPermissionRequiredMixin, DetailView):
    model = RetrievalBatch
    template_name = 'dicom_server/batch_detail.html'
    permission_required = 'dicom_server.view_retrievaljob'
    context_object_name = 'batch'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['patients'] = self.object.patients.select_related('patient', 'job')
        return context


class NodeIDRulesView(DicomPermissionRequiredMixin, View):
    """POST {transforms: [...] | 'pattern => repl\\n...'} — update a node's
    patient-ID transform rules (also editable via the node form)."""
    permission_required = 'dicom_server.change_remotedicomnode'

    def post(self, request, pk):
        node = get_object_or_404(RemoteDICOMNode, pk=pk)
        payload, error = _json_payload(request)
        if error:
            return error
        transforms = payload.get('transforms')
        if isinstance(transforms, str):
            transforms = patient_ids.parse_transform_lines(transforms)
        errors = patient_ids.validate_transforms(transforms)
        if errors:
            return JsonResponse({'error': ' '.join(errors)}, status=400)
        node.patient_id_transforms = transforms or []
        node.save(update_fields=['patient_id_transforms', 'updated_at'])
        return JsonResponse({'ok': True})

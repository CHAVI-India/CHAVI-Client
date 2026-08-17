import json
import logging
import os
import shutil
import tempfile
import urllib.parse
import zipfile

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin, UserPassesTestMixin
from django.conf import settings
from django.http import JsonResponse, Http404, FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import ListView, View

from client_app.models import Patient, DICOMStudy, DICOMSeries, DICOMInstance
from deidentification.models import DeidPatient, DeidentificationJob

logger = logging.getLogger(__name__)


class StaffPermissionRequiredMixin(LoginRequiredMixin, UserPassesTestMixin, PermissionRequiredMixin):
    """Base mixin: requires authenticated + is_staff + the specified Django model permission."""

    def test_func(self):
        return self.request.user.is_staff


class DeidPatientListView(StaffPermissionRequiredMixin, ListView):
    model = Patient
    template_name = 'deidentification/patient_list.html'
    context_object_name = 'patients'
    paginate_by = 25
    permission_required = 'deidentification.view_deidpatient'

    def get_queryset(self):
        qs = Patient.objects.all().order_by('patient_id')

        # --- Text search by patient_id ---
        search = self.request.GET.get('search', '').strip()
        if search:
            qs = qs.filter(patient_id__icontains=search)

        # --- Deid status filter ---
        deid_status = self.request.GET.get('deid_status', 'all')
        if deid_status == 'deidentified':
            qs = qs.filter(
                pk__in=DeidPatient.objects.values_list('patient_id', flat=True)
            )
        elif deid_status == 'not_deidentified':
            qs = qs.exclude(
                pk__in=DeidPatient.objects.values_list('patient_id', flat=True)
            )

        # --- Gender filter ---
        gender = self.request.GET.get('gender', 'all')
        if gender and gender != 'all':
            qs = qs.filter(gender=gender)

        # --- Job status filter ---
        job_status = self.request.GET.get('job_status', 'all')
        if job_status and job_status != 'all':
            patient_ids_with_status = DeidentificationJob.objects.filter(
                status=job_status
            ).values_list('study__patient_id', flat=True)
            qs = qs.filter(pk__in=patient_ids_with_status)

        # --- Created date range ---
        created_from = self.request.GET.get('created_from', '').strip()
        created_to = self.request.GET.get('created_to', '').strip()
        if created_from:
            qs = qs.filter(created_at__date__gte=created_from)
        if created_to:
            qs = qs.filter(created_at__date__lte=created_to)

        # --- Updated date range ---
        updated_from = self.request.GET.get('updated_from', '').strip()
        updated_to = self.request.GET.get('updated_to', '').strip()
        if updated_from:
            qs = qs.filter(updated_at__date__gte=updated_from)
        if updated_to:
            qs = qs.filter(updated_at__date__lte=updated_to)

        return qs

    def paginate_queryset(self, queryset, page_size):
        paginator, page, object_list, is_paginated = super().paginate_queryset(queryset, page_size)
        # Annotate only the page items for performance
        for p in object_list:
            studies = DICOMStudy.objects.filter(patient=p)
            p.study_count = studies.count()
            p.has_deid = DeidPatient.objects.filter(patient=p).exists()

            series_ids = DICOMSeries.objects.filter(study__in=studies).values_list('pk', flat=True)
            p.series_count = len(series_ids)
            p.instance_count = DICOMInstance.objects.filter(series_id__in=series_ids).count()

            jobs = DeidentificationJob.objects.filter(study__in=studies)
            p.deid_jobs_total = jobs.count()
            p.deid_jobs_success = jobs.filter(status=DeidentificationJob.Status.SUCCESS).count()
            p.deid_jobs_failed = jobs.filter(status=DeidentificationJob.Status.FAILURE).count()
            p.deid_jobs_processing = jobs.filter(status=DeidentificationJob.Status.PROCESSING).count()
            p.deid_jobs_pending = jobs.filter(status=DeidentificationJob.Status.PENDING).count()

        return paginator, page, object_list, is_paginated

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Deidentification — Patient List'
        # Pass filter values back to template for form state retention
        context['search'] = self.request.GET.get('search', '')
        context['deid_status'] = self.request.GET.get('deid_status', 'all')
        context['gender'] = self.request.GET.get('gender', 'all')
        context['job_status'] = self.request.GET.get('job_status', 'all')
        context['created_from'] = self.request.GET.get('created_from', '')
        context['created_to'] = self.request.GET.get('created_to', '')
        context['updated_from'] = self.request.GET.get('updated_from', '')
        context['updated_to'] = self.request.GET.get('updated_to', '')
        # Build query string without page for pagination links
        get_params = self.request.GET.copy()
        get_params.pop('page', None)
        context['query_string'] = get_params.urlencode()
        return context


class DeidPatientDetailView(StaffPermissionRequiredMixin, View):
    template_name = 'deidentification/patient_detail.html'
    permission_required = 'deidentification.view_deidpatient'

    def get(self, request, patient_id):
        patient = get_object_or_404(Patient, patient_id=patient_id)
        studies = DICOMStudy.objects.filter(patient=patient).order_by('-study_date')
        deid_patient = DeidPatient.objects.filter(patient=patient).first()

        study_jobs = []
        for study in studies:
            jobs = DeidentificationJob.objects.filter(study=study).order_by('-created_at')
            study_jobs.append({
                'study': study,
                'jobs': jobs,
                'latest_job': jobs.first(),
            })

        return render(request, self.template_name, {
            'patient': patient,
            'deid_patient': deid_patient,
            'study_jobs': study_jobs,
            'page_title': f'Deidentification — {patient.patient_id}',
        })


class TriggerDeidentificationView(StaffPermissionRequiredMixin, View):
    permission_required = 'deidentification.add_deidentificationjob'

    def post(self, request, patient_id):
        patient = get_object_or_404(Patient, patient_id=patient_id)
        study_ids = request.POST.getlist('study_ids')

        if not study_ids:
            studies = DICOMStudy.objects.filter(patient=patient)
            study_ids = list(studies.values_list('study_instance_uid', flat=True))

        if not study_ids:
            return JsonResponse({'error': 'No studies found for this patient'}, status=400)

        from deidentification.tasks import deidentify_dicom_studies_bulk_task
        result = deidentify_dicom_studies_bulk_task.delay(study_ids, user_id=request.user.id)

        return JsonResponse({
            'task_id': result.id,
            'study_count': len(study_ids),
            'redirect_url': reverse('client_app:taskrun_list'),
        })


class JobStatusView(StaffPermissionRequiredMixin, View):
    permission_required = 'deidentification.view_deidentificationjob'

    def get(self, request, job_id):
        job = get_object_or_404(DeidentificationJob, id=job_id)
        return JsonResponse({
            'id': job.id,
            'status': job.status,
            'total_file_count': job.total_file_count,
            'processed_count': job.processed_count,
            'failed_count': job.failed_count,
            'failed_series_count': job.failed_series_count,
            'error_log': job.error_log,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
        })


class LegacyImportView(StaffPermissionRequiredMixin, View):
    template_name = 'deidentification/legacy_import.html'
    permission_required = 'deidentification.add_deidpatient'

    def get(self, request):
        return render(request, self.template_name, {
            'page_title': 'Legacy Mapping Import',
        })

    def post(self, request):
        db_file = request.FILES.get('db_file')
        key_file = request.FILES.get('key_file')

        if not db_file or not key_file:
            return JsonResponse({'error': 'Both db_file and key_file are required'}, status=400)

        import uuid as _uuid
        tmp_dir = os.path.join(settings.MEDIA_ROOT, 'legacy_import_tmp')
        os.makedirs(tmp_dir, exist_ok=True)
        unique = _uuid.uuid4().hex

        db_tmp_path = os.path.join(tmp_dir, f"{unique}.db")
        with open(db_tmp_path, 'wb') as db_tmp:
            for chunk in db_file.chunks():
                db_tmp.write(chunk)

        key_tmp_path = os.path.join(tmp_dir, f"{unique}.key")
        with open(key_tmp_path, 'wb') as key_tmp:
            for chunk in key_file.chunks():
                key_tmp.write(chunk)

        from deidentification.tasks import import_legacy_mapping_task
        result = import_legacy_mapping_task.delay(db_tmp_path, key_tmp_path, user_id=request.user.id)

        return JsonResponse({
            'task_id': result.id,
            'redirect_url': reverse('client_app:taskrun_list'),
        })


class LegacyImportResultsView(StaffPermissionRequiredMixin, View):
    """Show unmatched rows from a completed legacy import task for manual reconciliation."""
    template_name = 'deidentification/legacy_import_results.html'
    permission_required = 'deidentification.add_deidpatient'

    PAGE_SIZE = 25

    def get(self, request, task_id):
        from client_app.models import TaskRun
        from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
        task_run = get_object_or_404(TaskRun, id=task_id)

        unmatched_rows = []
        result_data = {}

        if task_run.status == TaskRun.Status.SUCCESS and task_run.result_summary:
            result_data = task_run.result_summary
            unmatched_rows = result_data.get('unmatched_rows', [])

        # Filter by type if requested
        filter_type = request.GET.get('type', 'all')
        if filter_type and filter_type != 'all':
            unmatched_rows = [r for r in unmatched_rows if r.get('type') == filter_type]

        # Group rows hierarchically: patient → studies → series → instances
        hierarchy = _build_unmatched_hierarchy(unmatched_rows)

        # Paginate at the patient level to avoid rendering thousands of rows at once
        hierarchy_items = list(hierarchy.items())
        paginator = Paginator(hierarchy_items, self.PAGE_SIZE)
        page_num = request.GET.get('page', 1)
        try:
            page_obj = paginator.page(page_num)
        except (EmptyPage, PageNotAnInteger):
            page_obj = paginator.page(1)

        page_hierarchy = dict(page_obj.object_list)

        return render(request, self.template_name, {
            'page_title': 'Legacy Import Results',
            'task_run': task_run,
            'unmatched_rows': unmatched_rows,
            'hierarchy': page_hierarchy,
            'stats': result_data,
            'filter_type': filter_type,
            'page_obj': page_obj,
        })


def _build_unmatched_hierarchy(rows):
    """Group flat unmatched rows into a nested patient → study → series → instance tree."""
    patients = {}  # key: patient_id (or '__orphan__' for rows with no parent)
    studies = {}
    series_map = {}

    for row in rows:
        rtype = row.get('type', '')

        if rtype == 'patient':
            pid = row.get('original_id', '')
            if pid not in patients:
                patients[pid] = {
                    'patient_row': row,
                    'studies': [],
                }
            else:
                patients[pid]['patient_row'] = row

        elif rtype == 'study':
            pid = row.get('parent_patient_id', '') or '__orphan__'
            if pid not in patients:
                patients[pid] = {'patient_row': None, 'studies': []}
            study_entry = {
                'study_row': row,
                'original_id': row.get('original_id', ''),
                'series': [],
            }
            patients[pid]['studies'].append(study_entry)
            studies[row.get('original_id', '')] = study_entry

        elif rtype == 'series':
            study_uid = row.get('parent_study_uid', '')
            if study_uid and study_uid in studies:
                series_entry = {
                    'series_row': row,
                    'original_id': row.get('original_id', ''),
                    'instances': [],
                }
                studies[study_uid]['series'].append(series_entry)
                series_map[row.get('original_id', '')] = series_entry
            else:
                # Orphan series - add to orphan patient
                pid = '__orphan__'
                if pid not in patients:
                    patients[pid] = {'patient_row': None, 'studies': []}
                orphan_study = {
                    'study_row': None,
                    'original_id': '',
                    'series': [],
                }
                patients[pid]['studies'].append(orphan_study)
                orphan_study['series'].append({
                    'series_row': row,
                    'original_id': row.get('original_id', ''),
                    'instances': [],
                })
                series_map[row.get('original_id', '')] = orphan_study['series'][-1]

        elif rtype == 'instance':
            series_uid = row.get('parent_series_uid', '')
            if series_uid and series_uid in series_map:
                series_map[series_uid]['instances'].append({
                    'instance_row': row,
                })
            else:
                # Orphan instance
                pid = '__orphan__'
                if pid not in patients:
                    patients[pid] = {'patient_row': None, 'studies': []}
                orphan_study = {
                    'study_row': None,
                    'original_id': '',
                    'series': [],
                }
                patients[pid]['studies'].append(orphan_study)
                orphan_series = {
                    'series_row': None,
                    'original_id': '',
                    'instances': [],
                }
                orphan_study['series'].append(orphan_series)
                orphan_series['instances'].append({
                    'instance_row': row,
                })

    return patients


class CreateMissingPatientView(StaffPermissionRequiredMixin, View):
    """Create a new client_app.Patient from unmatched legacy data."""
    permission_required = 'deidentification.add_deidpatient'

    def post(self, request):
        patient_id = request.POST.get('patient_id', '').strip()
        date_of_birth = request.POST.get('date_of_birth', '').strip() or None

        if not patient_id:
            return JsonResponse({'error': 'patient_id is required'}, status=400)

        from client_app.models import Patient
        if Patient.objects.filter(patient_id=patient_id).exists():
            return JsonResponse({'error': f'Patient {patient_id} already exists'}, status=400)

        Patient.objects.create(
            patient_id=patient_id,
            date_of_birth=date_of_birth,
        )
        return JsonResponse({'success': True, 'patient_id': patient_id})


class CreateMissingStudyView(StaffPermissionRequiredMixin, View):
    """Create a new client_app.DICOMStudy from unmatched legacy data."""
    permission_required = 'deidentification.add_deidpatient'

    def post(self, request):
        study_instance_uid = request.POST.get('study_instance_uid', '').strip()
        patient_id = request.POST.get('patient_id', '').strip()
        study_date = request.POST.get('study_date', '').strip() or None

        if not study_instance_uid or not patient_id:
            return JsonResponse({'error': 'study_instance_uid and patient_id are required'}, status=400)

        from client_app.models import Patient, DICOMStudy
        patient = Patient.objects.filter(patient_id=patient_id).first()
        if not patient:
            return JsonResponse({'error': f'Patient {patient_id} not found'}, status=404)

        if DICOMStudy.objects.filter(study_instance_uid=study_instance_uid).exists():
            return JsonResponse({'error': f'Study {study_instance_uid} already exists'}, status=400)

        DICOMStudy.objects.create(
            study_instance_uid=study_instance_uid,
            patient=patient,
            study_date=study_date,
        )
        return JsonResponse({'success': True, 'study_instance_uid': study_instance_uid})


class CreateMissingSeriesView(StaffPermissionRequiredMixin, View):
    """Create a new client_app.DICOMSeries from unmatched legacy data."""
    permission_required = 'deidentification.add_deidpatient'

    def post(self, request):
        series_instance_uid = request.POST.get('series_instance_uid', '').strip()
        study_instance_uid = request.POST.get('study_instance_uid', '').strip()
        modality = request.POST.get('modality', '').strip() or 'CT'
        series_date = request.POST.get('series_date', '').strip() or None
        frame_of_reference_uid = request.POST.get('frame_of_reference_uid', '').strip() or None

        if not series_instance_uid or not study_instance_uid:
            return JsonResponse({'error': 'series_instance_uid and study_instance_uid are required'}, status=400)

        from client_app.models import DICOMStudy, DICOMSeries
        study = DICOMStudy.objects.filter(study_instance_uid=study_instance_uid).first()
        if not study:
            return JsonResponse({'error': f'Study {study_instance_uid} not found'}, status=404)

        if DICOMSeries.objects.filter(series_instance_uid=series_instance_uid).exists():
            return JsonResponse({'error': f'Series {series_instance_uid} already exists'}, status=400)

        DICOMSeries.objects.create(
            study=study,
            series_instance_uid=series_instance_uid,
            modality=modality,
            series_date=series_date,
            frame_of_reference_uid=frame_of_reference_uid,
        )

        # Store deidentified mapping if parent deid study exists and deid values provided
        deid_series_uid = request.POST.get('deidentified_series_instance_uid', '').strip()
        deid_series_date = request.POST.get('deidentified_series_date', '').strip() or None
        deid_frame_uid = request.POST.get('deidentified_frame_of_reference_uid', '').strip() or None

        if deid_series_uid:
            from deidentification.models import DeidStudy, DeidSeries
            deid_study = DeidStudy.objects.filter(study=study).first()
            if deid_study:
                series = DICOMSeries.objects.get(series_instance_uid=series_instance_uid)
                DeidSeries.objects.update_or_create(
                    series=series,
                    defaults={
                        'deid_study': deid_study,
                        'deidentified_series_instance_uid': deid_series_uid,
                        'deidentified_series_date': deid_series_date,
                        'deidentified_frame_of_reference_uid': deid_frame_uid,
                    },
                )

        return JsonResponse({'success': True, 'series_instance_uid': series_instance_uid})


class CreateMissingInstanceView(StaffPermissionRequiredMixin, View):
    """Create a new client_app.DICOMInstance from unmatched legacy data."""
    permission_required = 'deidentification.add_deidpatient'

    def post(self, request):
        sop_instance_uid = request.POST.get('sop_instance_uid', '').strip()
        series_instance_uid = request.POST.get('series_instance_uid', '').strip()

        if not sop_instance_uid or not series_instance_uid:
            return JsonResponse({'error': 'sop_instance_uid and series_instance_uid are required'}, status=400)

        from client_app.models import DICOMSeries, DICOMInstance
        series = DICOMSeries.objects.filter(series_instance_uid=series_instance_uid).first()
        if not series:
            return JsonResponse({'error': f'Series {series_instance_uid} not found'}, status=404)

        if DICOMInstance.objects.filter(sop_instance_uid=sop_instance_uid).exists():
            return JsonResponse({'error': f'Instance {sop_instance_uid} already exists'}, status=400)

        DICOMInstance.objects.create(
            series=series,
            sop_instance_uid=sop_instance_uid,
        )

        # Store deidentified mapping if parent deid series exists and deid value provided
        deid_sop_uid = request.POST.get('deidentified_sop_instance_uid', '').strip()

        if deid_sop_uid:
            from deidentification.models import DeidSeries, DeidInstance
            deid_series = DeidSeries.objects.filter(series=series).first()
            if deid_series:
                instance = DICOMInstance.objects.get(sop_instance_uid=sop_instance_uid)
                DeidInstance.objects.update_or_create(
                    instance=instance,
                    defaults={
                        'deid_series': deid_series,
                        'deidentified_sop_instance_uid': deid_sop_uid,
                    },
                )

        return JsonResponse({'success': True, 'sop_instance_uid': sop_instance_uid})


class BulkCreateMissingView(StaffPermissionRequiredMixin, View):
    """Bulk create multiple missing records from unmatched legacy data.

    Accepts either:
    - JSON body with ``records`` list (used by per-patient bulk create, synchronous)
    - ``task_id`` POST param (used by 'Create All' button, dispatches async Celery task)
    """
    permission_required = 'deidentification.add_deidpatient'

    def post(self, request, task_id=None):
        # If task_id is provided (from URL kwarg or POST/GET), dispatch async Celery task with ALL unmatched rows
        task_id = task_id or request.POST.get('task_id') or request.GET.get('task_id')
        if task_id:
            from client_app.models import TaskRun
            task_run = get_object_or_404(TaskRun, id=task_id)
            if not task_run.result_summary:
                return JsonResponse({'error': 'No result data found for this task'}, status=400)

            records = task_run.result_summary.get('unmatched_rows', [])
            if not records:
                return JsonResponse({'error': 'No unmatched records to create'}, status=400)

            from deidentification.tasks import create_missing_records_task
            result = create_missing_records_task.delay(records, user_id=request.user.id)
            return JsonResponse({
                'task_id': result.id,
                'redirect_url': reverse('client_app:taskrun_list'),
            })

        # Otherwise, synchronous per-patient bulk create from JSON body
        import json as _json
        try:
            data = _json.loads(request.body)
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Invalid JSON body'}, status=400)

        records = data.get('records', [])
        if not records:
            return JsonResponse({'error': 'No records provided'}, status=400)

        from client_app.models import Patient, DICOMStudy, DICOMSeries, DICOMInstance
        from deidentification.models import DeidPatient, DeidStudy, DeidSeries, DeidInstance
        from datetime import datetime

        def _parse_date(val):
            """Parse a date string in common formats, return None if blank or unparseable."""
            if not val or not str(val).strip():
                return None
            val = str(val).strip()
            for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y%m%d', '%d-%m-%Y'):
                try:
                    return datetime.strptime(val, fmt).date()
                except (ValueError, TypeError):
                    continue
            return None

        # Sort records by type so parents are always created before children:
        #   patient → study → series → instance
        type_order = {'patient': 0, 'study': 1, 'series': 2, 'instance': 3}
        records.sort(key=lambda r: type_order.get(r.get('type', ''), 9))

        created = []
        errors = []
        skipped = []
        auto_patients = set()  # track patients we auto-create

        for rec in records:
            rtype = rec.get('type', '')
            try:
                if rtype == 'patient':
                    pid = rec.get('original_id', '').strip()
                    if not pid or pid == '__orphan__':
                        errors.append({'id': pid, 'error': 'patient_id required'})
                        continue
                    if Patient.objects.filter(patient_id=pid).exists():
                        skipped.append({'type': 'patient', 'id': pid, 'reason': 'already exists'})
                        continue
                    dob = _parse_date(rec.get('date_of_birth', ''))
                    Patient.objects.create(patient_id=pid, date_of_birth=dob)
                    created.append({'type': 'patient', 'id': pid, 'dob': str(dob) if dob else None})

                elif rtype == 'study':
                    study_uid = rec.get('original_id', '').strip()
                    patient_id = rec.get('parent_patient_id', '').strip()
                    if not study_uid or not patient_id or patient_id == '__orphan__':
                        errors.append({'id': study_uid, 'error': 'study_instance_uid and parent_patient_id required'})
                        continue
                    patient = Patient.objects.filter(patient_id=patient_id).first()
                    if not patient:
                        # Auto-create missing parent patient (no DOB available)
                        patient = Patient.objects.create(patient_id=patient_id, date_of_birth=None)
                        auto_patients.add(patient_id)
                        created.append({'type': 'patient', 'id': patient_id, 'auto': True})
                    if DICOMStudy.objects.filter(study_instance_uid=study_uid).exists():
                        skipped.append({'type': 'study', 'id': study_uid, 'reason': 'already exists'})
                        continue
                    study_date = _parse_date(rec.get('deidentified_date', ''))
                    DICOMStudy.objects.create(
                        study_instance_uid=study_uid, patient=patient, study_date=study_date,
                    )
                    created.append({'type': 'study', 'id': study_uid})

                elif rtype == 'series':
                    series_uid = rec.get('original_id', '').strip()
                    study_uid = rec.get('parent_study_uid', '').strip()
                    if not series_uid or not study_uid:
                        errors.append({'id': series_uid, 'error': 'series_instance_uid and parent_study_uid required'})
                        continue
                    study = DICOMStudy.objects.filter(study_instance_uid=study_uid).first()
                    if not study:
                        errors.append({'id': series_uid, 'error': f'Study {study_uid} not found'})
                        continue
                    if DICOMSeries.objects.filter(series_instance_uid=series_uid).exists():
                        skipped.append({'type': 'series', 'id': series_uid, 'reason': 'already exists'})
                        continue
                    modality = rec.get('modality', 'CT') or 'CT'
                    series_date = _parse_date(rec.get('deidentified_series_date', ''))
                    frame_uid = rec.get('deidentified_frame_of_reference_uid', '').strip() or None
                    series = DICOMSeries.objects.create(
                        study=study, series_instance_uid=series_uid,
                        modality=modality, series_date=series_date,
                        frame_of_reference_uid=frame_uid,
                    )
                    # Store deidentified mapping if parent deid study exists
                    deid_series_uid = rec.get('deidentified_id', '').strip()
                    if deid_series_uid:
                        deid_study = DeidStudy.objects.filter(study=study).first()
                        if deid_study:
                            DeidSeries.objects.update_or_create(
                                series=series,
                                defaults={
                                    'deid_study': deid_study,
                                    'deidentified_series_instance_uid': deid_series_uid,
                                    'deidentified_series_date': series_date,
                                    'deidentified_frame_of_reference_uid': frame_uid,
                                },
                            )
                    created.append({'type': 'series', 'id': series_uid, 'for_uid': frame_uid})

                elif rtype == 'instance':
                    sop_uid = rec.get('original_id', '').strip()
                    series_uid = rec.get('parent_series_uid', '').strip()
                    if not sop_uid or not series_uid:
                        errors.append({'id': sop_uid, 'error': 'sop_instance_uid and parent_series_uid required'})
                        continue
                    series = DICOMSeries.objects.filter(series_instance_uid=series_uid).first()
                    if not series:
                        errors.append({'id': sop_uid, 'error': f'Series {series_uid} not found'})
                        continue
                    if DICOMInstance.objects.filter(sop_instance_uid=sop_uid).exists():
                        skipped.append({'type': 'instance', 'id': sop_uid, 'reason': 'already exists'})
                        continue
                    instance = DICOMInstance.objects.create(series=series, sop_instance_uid=sop_uid)
                    # Store deidentified mapping if parent deid series exists
                    deid_sop_uid = rec.get('deidentified_id', '').strip()
                    if deid_sop_uid:
                        deid_series = DeidSeries.objects.filter(series=series).first()
                        if deid_series:
                            DeidInstance.objects.update_or_create(
                                instance=instance,
                                defaults={
                                    'deid_series': deid_series,
                                    'deidentified_sop_instance_uid': deid_sop_uid,
                                },
                            )
                    created.append({'type': 'instance', 'id': sop_uid})

            except Exception as e:
                errors.append({'id': rec.get('original_id', ''), 'error': str(e)})

        return JsonResponse({
            'success': True,
            'created_count': len(created),
            'error_count': len(errors),
            'skipped_count': len(skipped),
            'created': created,
            'errors': errors,
            'skipped': skipped,
        })


class BulkDeidentifyView(StaffPermissionRequiredMixin, View):
    permission_required = 'deidentification.add_deidentificationjob'

    def post(self, request):
        try:
            data = json.loads(request.body)
            patient_ids = data.get('patient_ids', [])
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({'error': 'Invalid JSON body'}, status=400)

        if not patient_ids:
            patients = Patient.objects.all()
        else:
            patients = Patient.objects.filter(patient_id__in=patient_ids)

        if not patients.exists():
            return JsonResponse({'error': 'No patients found'}, status=400)

        study_ids = list(
            DICOMStudy.objects.filter(patient__in=patients)
            .values_list('study_instance_uid', flat=True)
        )

        if not study_ids:
            return JsonResponse({'error': 'No DICOM studies found for selected patients'}, status=400)

        from deidentification.tasks import deidentify_dicom_studies_bulk_task
        result = deidentify_dicom_studies_bulk_task.delay(study_ids, user_id=request.user.id)

        return JsonResponse({
            'task_id': result.id,
            'patient_count': patients.count(),
            'study_count': len(study_ids),
            'redirect_url': reverse('client_app:taskrun_list'),
        })


class DeidDownloadView(StaffPermissionRequiredMixin, View):
    """Download deidentified DICOM files as a ZIP.

    Single-patient and single-job downloads are served synchronously.
    Bulk downloads (all patients or many selected) are dispatched as
    background Celery tasks to avoid HTTP request timeouts.
    """
    permission_required = 'deidentification.view_deidpatient'

    def get(self, request, job_id=None, patient_id=None):
        import hashlib

        # Determine which patients to include
        if job_id:
            job = get_object_or_404(DeidentificationJob, id=job_id)
            if job.status not in (DeidentificationJob.Status.SUCCESS, DeidentificationJob.Status.PARTIAL):
                return JsonResponse({'error': 'Deidentification not complete or failed'}, status=400)
            patients = [job.study.patient]
        elif patient_id:
            patient = get_object_or_404(Patient, patient_id=patient_id)
            patients = [patient]
        else:
            # Bulk download — get patient_ids from query param
            patient_ids = request.GET.get('patient_ids', '')
            if patient_ids:
                patients = list(Patient.objects.filter(patient_id__in=patient_ids.split(',')))
            else:
                patients = list(Patient.objects.all())

        if not patients:
            return JsonResponse({'error': 'No patients found'}, status=400)

        # For bulk downloads (more than 3 patients), use async Celery task
        if len(patients) > 3 and not job_id and not patient_id:
            from deidentification.tasks import build_dicom_download_zip_task
            pid_list = [p.patient_id for p in patients]
            result = build_dicom_download_zip_task.delay(pid_list, user_id=request.user.id)
            return JsonResponse({
                'task_id': result.id,
                'redirect_url': reverse('client_app:taskrun_list'),
                'message': 'Building DICOM ZIP in background. You will be notified when it is ready.',
            })

        # Synchronous download for small sets
        temp_zip = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
        temp_zip.close()

        try:
            with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zf:
                for patient in patients:
                    deid_patient = DeidPatient.objects.filter(patient=patient).first()
                    if not deid_patient:
                        continue

                    patient_hash = hashlib.sha256(str(patient.patient_id).encode()).hexdigest()[:16]
                    patient_folder = f"patient_{patient_hash}"

                    # Add deidentified DICOM files only
                    output_base = os.path.join(settings.MEDIA_ROOT, 'deidentification', 'output')
                    deid_patient_dir = os.path.join(output_base, deid_patient.deidentified_patient_id)
                    if os.path.isdir(deid_patient_dir):
                        for deid_study in deid_patient.deid_studies.all():
                            study_dir = os.path.join(deid_patient_dir, deid_study.deidentified_study_instance_uid)
                            if not os.path.isdir(study_dir):
                                continue
                            for filename in os.listdir(study_dir):
                                if filename.endswith('.dcm'):
                                    file_path = os.path.join(study_dir, filename)
                                    arcname = f"{patient_folder}/dicom/{deid_study.deidentified_study_instance_uid}/{filename}"
                                    zf.write(file_path, arcname)

            if job_id:
                zip_name = f"deidentified_dicom_job_{job_id}.zip"
            elif patient_id:
                zip_name = f"deidentified_dicom_{patient_id}.zip"
            else:
                zip_name = f"deidentified_dicom_{len(patients)}_patients.zip"

            response = FileResponse(open(temp_zip.name, 'rb'), content_type='application/zip')
            response['Content-Disposition'] = f'attachment; filename={zip_name}'
            return response
        except Exception as e:
            logger.error(f"Deid DICOM download failed: {e}", exc_info=True)
            if os.path.exists(temp_zip.name):
                os.unlink(temp_zip.name)
            return JsonResponse({'error': f'Download failed: {str(e)}'}, status=500)


def _serialize_patient_clinical_data(patient, request):
    """Serialize all clinical data for a patient into a dict (same structure as patient_data_export)."""
    from client_app.serializers import (
        PatientSerializer, DICOMStudySerializer, DICOMStudyProjectSerializer,
        DiagnosisSerializer, OutcomeSerializer, LesionSerializer, LesionResponseSerializer,
        GermlineGenomicAlterationsSerializer, PathologySerializer, ImmunohistochemistrySerializer,
        CytogeneticsSerializer, SomaticGenomicAlterationsSerializer, GeneExpressionDataSerializer,
        EpigeneticDataSerializer, OtherTreatmentSerializer, RadiotherapySerializer,
        RadiotherapyVolumeSerializer, RadiotherapyDoseVolumeDataSerializer, SurgerySerializer,
        ConcomitantMedicationsSerializer, SystemicTherapySerializer, SystemicTherapyScheduleSerializer,
        AdverseEffectsSerializer, StageInformationSerializer, PatientReportedOutcomeSerializer,
        PatientOutcomeSerializer, ComorbiditySerializer, SymptomSerializer,
        PatientAssessmentSerializer, LaboratoryResultsSerializer,
    )
    from client_app.models import (
        DICOMStudy, DICOMStudyProject, Diagnosis, Outcome, Lesion, LesionResponse,
        GermlineGenomicAlterations, Pathology, Immunohistochemistry, Cytogenetics,
        SomaticGenomicAlterations, GeneExpressionData, EpigeneticData, OtherTreatment,
        Radiotherapy, RadiotherapyVolume, RadiotherapyDoseVolumeData, Surgery,
        ConcomitantMedications, SystemicTherapy, SystemicTherapySchedule,
        AdverseEffects, StageInformation, PatientReportedOutcome, PatientOutcome,
        Comorbidity, Symptom, PatientAssessment, LaboratoryResults,
    )

    context = {'request': request}
    patient_data = {
        'patients': [], 'dicom_studies': [], 'diagnoses': [], 'outcomes': [],
        'lesions': [], 'lesion_responses': [], 'germline_genomic_alterations': [],
        'pathologies': [], 'immunohistochemistries': [], 'cytogenetics': [],
        'somatic_genomic_alterations': [], 'gene_expression_data': [], 'epigenetic_data': [],
        'other_treatments': [], 'radiotherapies': [], 'radiotherapy_volumes': [],
        'radiotherapy_dose_volume_data': [], 'surgeries': [], 'concomitant_medications': [],
        'systemic_therapies': [], 'systemic_therapy_schedules': [], 'adverse_effects': [],
        'pro_instruments': [], 'pro_domains': [], 'pro_questions': [],
        'patient_reported_outcomes': [], 'patient_outcomes': [], 'comorbidities': [],
        'stage_information': [], 'laboratory_results': [], 'symptoms': [],
        'patient_assessments': [], 'dicom_study_projects': []
    }

    patient_data['patients'].append(PatientSerializer(patient, context=context).data)
    dicom_studies = DICOMStudy.objects.filter(patient=patient)
    patient_data['dicom_studies'].extend(DICOMStudySerializer(dicom_studies, many=True, context=context).data)
    dicom_study_projects = DICOMStudyProject.objects.filter(study_instance_uid__patient=patient)
    patient_data['dicom_study_projects'].extend(DICOMStudyProjectSerializer(dicom_study_projects, many=True, context=context).data)
    diagnoses = Diagnosis.objects.filter(patient=patient)
    patient_data['diagnoses'].extend(DiagnosisSerializer(diagnoses, many=True, context=context).data)

    for diagnosis in diagnoses:
        patient_data['outcomes'].extend(OutcomeSerializer(Outcome.objects.filter(diagnosis=diagnosis), many=True, context=context).data)
        lesions = Lesion.objects.filter(diagnosis=diagnosis)
        patient_data['lesions'].extend(LesionSerializer(lesions, many=True, context=context).data)
        for lesion in lesions:
            patient_data['lesion_responses'].extend(LesionResponseSerializer(LesionResponse.objects.filter(lesion=lesion), many=True, context=context).data)
        pathologies = Pathology.objects.filter(diagnosis=diagnosis)
        patient_data['pathologies'].extend(PathologySerializer(pathologies, many=True, context=context).data)
        for pathology in pathologies:
            patient_data['immunohistochemistries'].extend(ImmunohistochemistrySerializer(Immunohistochemistry.objects.filter(pathology=pathology), many=True, context=context).data)
            patient_data['cytogenetics'].extend(CytogeneticsSerializer(Cytogenetics.objects.filter(pathology=pathology), many=True, context=context).data)
            patient_data['somatic_genomic_alterations'].extend(SomaticGenomicAlterationsSerializer(SomaticGenomicAlterations.objects.filter(pathology=pathology), many=True, context=context).data)
            patient_data['gene_expression_data'].extend(GeneExpressionDataSerializer(GeneExpressionData.objects.filter(pathology=pathology), many=True, context=context).data)
            patient_data['epigenetic_data'].extend(EpigeneticDataSerializer(EpigeneticData.objects.filter(pathology=pathology), many=True, context=context).data)
        patient_data['other_treatments'].extend(OtherTreatmentSerializer(OtherTreatment.objects.filter(diagnosis=diagnosis), many=True, context=context).data)
        radiotherapies = Radiotherapy.objects.filter(diagnosis=diagnosis)
        patient_data['radiotherapies'].extend(RadiotherapySerializer(radiotherapies, many=True, context=context).data)
        for rt in radiotherapies:
            patient_data['radiotherapy_volumes'].extend(RadiotherapyVolumeSerializer(RadiotherapyVolume.objects.filter(radiotherapy=rt), many=True, context=context).data)
            patient_data['radiotherapy_dose_volume_data'].extend(RadiotherapyDoseVolumeDataSerializer(RadiotherapyDoseVolumeData.objects.filter(radiotherapy=rt), many=True, context=context).data)
        patient_data['surgeries'].extend(SurgerySerializer(Surgery.objects.filter(diagnosis=diagnosis), many=True, context=context).data)
        patient_data['concomitant_medications'].extend(ConcomitantMedicationsSerializer(ConcomitantMedications.objects.filter(diagnosis=diagnosis), many=True, context=context).data)
        systemic_therapies = SystemicTherapy.objects.filter(diagnosis=diagnosis)
        patient_data['systemic_therapies'].extend(SystemicTherapySerializer(systemic_therapies, many=True, context=context).data)
        for st in systemic_therapies:
            patient_data['systemic_therapy_schedules'].extend(SystemicTherapyScheduleSerializer(SystemicTherapySchedule.objects.filter(systemic_therapy=st), many=True, context=context).data)
        patient_data['adverse_effects'].extend(AdverseEffectsSerializer(AdverseEffects.objects.filter(diagnosis=diagnosis), many=True, context=context).data)
        patient_data['stage_information'].extend(StageInformationSerializer(StageInformation.objects.filter(diagnosis=diagnosis), many=True, context=context).data)

    patient_data['patient_reported_outcomes'].extend(PatientReportedOutcomeSerializer(PatientReportedOutcome.objects.filter(patient=patient), many=True, context=context).data)
    patient_data['patient_outcomes'].extend(PatientOutcomeSerializer(PatientOutcome.objects.filter(patient=patient), many=True, context=context).data)
    patient_data['comorbidities'].extend(ComorbiditySerializer(Comorbidity.objects.filter(patient=patient), many=True, context=context).data)
    patient_data['germline_genomic_alterations'].extend(GermlineGenomicAlterationsSerializer(GermlineGenomicAlterations.objects.filter(patient=patient), many=True, context=context).data)
    patient_data['symptoms'].extend(SymptomSerializer(Symptom.objects.filter(patient=patient), many=True, context=context).data)
    patient_data['patient_assessments'].extend(PatientAssessmentSerializer(PatientAssessment.objects.filter(patient=patient), many=True, context=context).data)
    patient_data['laboratory_results'].extend(LaboratoryResultsSerializer(LaboratoryResults.objects.filter(patient=patient), many=True, context=context).data)

    return patient_data


class DeidClinicalDownloadView(StaffPermissionRequiredMixin, View):
    """Download deidentified clinical data as a ZIP of per-patient JSON files.

    Single-patient downloads are served synchronously.
    Bulk downloads are dispatched as background Celery tasks.
    """
    permission_required = 'deidentification.view_deidpatient'

    def get(self, request, patient_id=None):
        import hashlib
        from client_app.services.patient_data_export import UUIDEncoder
        from deidentification.services.clinical_data_deidentification import deidentify_clinical_data

        # Determine which patients to include
        if patient_id:
            patient = get_object_or_404(Patient, patient_id=patient_id)
            patients = [patient]
        else:
            # Bulk download — get patient_ids from query param
            patient_ids = request.GET.get('patient_ids', '')
            if patient_ids:
                patients = list(Patient.objects.filter(patient_id__in=patient_ids.split(',')))
            else:
                patients = list(Patient.objects.all())

        if not patients:
            return JsonResponse({'error': 'No patients found'}, status=400)

        # For bulk downloads (more than 3 patients), use async Celery task
        if len(patients) > 3 and not patient_id:
            from deidentification.tasks import build_clinical_download_zip_task
            pid_list = [p.patient_id for p in patients]
            result = build_clinical_download_zip_task.delay(pid_list, user_id=request.user.id)
            return JsonResponse({
                'task_id': result.id,
                'redirect_url': reverse('client_app:taskrun_list'),
                'message': 'Building clinical data ZIP in background. You will be notified when it is ready.',
            })

        # Synchronous download for small sets
        temp_zip = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
        temp_zip.close()

        try:
            included_count = 0
            with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zf:
                for patient in patients:
                    deid_patient = DeidPatient.objects.filter(patient=patient).first()
                    if not deid_patient:
                        continue

                    patient_data = _serialize_patient_clinical_data(patient, request)
                    try:
                        deidentified_clinical = deidentify_clinical_data(patient, patient_data)
                    except ValueError as e:
                        logger.warning(f"Skipping clinical data for {patient.patient_id}: {e}")
                        continue

                    patient_hash = hashlib.sha256(str(patient.patient_id).encode()).hexdigest()[:16]
                    json_filename = f"patient_{patient_hash}_clinical_data.json"
                    clinical_json = json.dumps(deidentified_clinical, indent=2, cls=UUIDEncoder)
                    zf.writestr(json_filename, clinical_json)
                    included_count += 1

            if patient_id:
                zip_name = f"deidentified_clinical_{patient_id}.zip"
            else:
                zip_name = f"deidentified_clinical_{included_count}_patients.zip"

            response = FileResponse(open(temp_zip.name, 'rb'), content_type='application/zip')
            response['Content-Disposition'] = f'attachment; filename={zip_name}'
            return response
        except Exception as e:
            logger.error(f"Deid clinical download failed: {e}", exc_info=True)
            if os.path.exists(temp_zip.name):
                os.unlink(temp_zip.name)
            return JsonResponse({'error': f'Download failed: {str(e)}'}, status=500)


class DownloadResultView(StaffPermissionRequiredMixin, View):
    """Serve a ZIP file produced by a completed async download task."""
    permission_required = 'deidentification.view_deidpatient'

    def get(self, request, task_id):
        from client_app.models import TaskRun
        task_run = get_object_or_404(TaskRun, id=task_id)

        if task_run.status != TaskRun.Status.SUCCESS:
            return JsonResponse({'error': f'Task not complete (status: {task_run.status})'}, status=400)

        result = task_run.result_summary or {}
        zip_rel_path = result.get('zip_path')
        if not zip_rel_path:
            return JsonResponse({'error': 'No file available for this task'}, status=400)

        zip_abs_path = os.path.join(settings.MEDIA_ROOT, zip_rel_path)
        if not os.path.exists(zip_abs_path):
            return JsonResponse({'error': 'File no longer exists'}, status=404)

        filename = os.path.basename(zip_abs_path)
        response = FileResponse(open(zip_abs_path, 'rb'), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename={filename}'
        return response

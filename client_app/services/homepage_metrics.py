from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from client_app.models import (
    BulkDICOMUploadSession,
    DICOMStudy,
    Diagnosis,
    Patient,
    Project,
    TaskRun,
)
from data_import.models import FileImportSession
from deidentification.models import DeidPatient, DeidStudy, DeidentificationJob
from extractor.models import ExtractionJob, ExtractionStatusChoices


def build_homepage_metrics(user, *, now=None):
    now = now or timezone.now()
    period_start = now - timedelta(days=30)

    can_view_extractions = user.has_perm("extractor.view_extractionjob")
    can_view_deidentification = user.has_perm(
        "deidentification.view_deidpatient"
    )
    can_view_deidentification_jobs = user.has_perm(
        "deidentification.view_deidentificationjob"
    )

    task_counts = {
        row["status"]: row["total"]
        for row in TaskRun.objects.filter(user=user)
        .values("status")
        .annotate(total=Count("id"))
    }

    extraction_jobs = None
    extraction_waiting = None
    if can_view_extractions:
        extraction_jobs = ExtractionJob.objects.filter(
            created_at__gte=period_start
        ).count()
        extraction_waiting = ExtractionJob.objects.filter(
            extraction_status__in=(
                ExtractionStatusChoices.AWAITING_MINING,
                ExtractionStatusChoices.AWAITING_EXTRACTION,
                ExtractionStatusChoices.PARTIAL,
            )
        ).count()

    deidentification_jobs = None
    deidentification_exceptions = None
    if can_view_deidentification_jobs:
        deidentification_jobs = DeidentificationJob.objects.filter(
            created_at__gte=period_start
        ).count()
        deidentification_exceptions = DeidentificationJob.objects.filter(
            status__in=(
                DeidentificationJob.Status.FAILURE,
                DeidentificationJob.Status.PARTIAL,
            )
        ).count()

    failed_or_stalled = sum(
        task_counts.get(status, 0)
        for status in (TaskRun.Status.FAILURE, TaskRun.Status.STALLED)
    )
    active_tasks = sum(
        task_counts.get(status, 0)
        for status in (
            TaskRun.Status.PENDING,
            TaskRun.Status.STARTED,
            TaskRun.Status.PROGRESS,
        )
    )

    return {
        "period": {"days": 30, "start": period_start},
        "totals": {
            "patients": Patient.objects.count(),
            "projects": Project.objects.count(),
            "diagnoses": Diagnosis.objects.count(),
            "dicom_studies": DICOMStudy.objects.count(),
            "deidentified_patients": (
                DeidPatient.objects.count() if can_view_deidentification else None
            ),
            "deidentified_dicom_studies": (
                DeidStudy.objects.count() if can_view_deidentification else None
            ),
        },
        "activity": {
            "new_patients": Patient.objects.filter(
                created_at__gte=period_start
            ).count(),
            "csv_sessions": FileImportSession.objects.filter(
                created_at__gte=period_start
            ).count(),
            "dicom_sessions": BulkDICOMUploadSession.objects.filter(
                created_at__gte=period_start
            ).count(),
            "extraction_jobs": extraction_jobs,
            "deidentification_jobs": deidentification_jobs,
        },
        "attention": {
            "unfinished_csv_imports": FileImportSession.objects.filter(
                data_imported=False
            ).count(),
            "dicom_matching": BulkDICOMUploadSession.objects.filter(
                status=BulkDICOMUploadSession.StatusChoices.MATCHING
            ).count(),
            "extraction_waiting": extraction_waiting,
            "failed_or_stalled_user_tasks": failed_or_stalled,
            "deidentification_exceptions": deidentification_exceptions,
        },
        "task_health": {
            "active": active_tasks,
            "successful_30d": TaskRun.objects.filter(
                user=user,
                status=TaskRun.Status.SUCCESS,
                created_at__gte=period_start,
            ).count(),
            "failed_or_stalled": failed_or_stalled,
        },
        "permissions": {
            "patient_search": user.has_perm("client_app.view_patient"),
            "patient_add": user.has_perm("client_app.add_patient"),
            "csv_import": user.has_perm("data_import.view_fileimportsession"),
            "dicom_upload": user.has_perm("client_app.add_bulkdicomuploadsession"),
            "dicom_sessions": user.has_perm("client_app.view_bulkdicomuploadsession"),
            "dicom_retrieve": user.has_perm("dicom_server.add_retrievaljob"),
            "extraction_dashboard": user.has_perm("extractor.view_processedtext"),
            "file_upload": user.has_perm("extractor.add_fileupload"),
            "deidentification": can_view_deidentification,
            "task_runs": user.has_perm("client_app.view_taskrun"),
            "admin": user.is_staff,
        },
    }

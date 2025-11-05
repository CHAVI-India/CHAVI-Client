from django.urls import path, include
from . import views

app_name = 'client_app'  # This defines the namespace

urlpatterns = [
    path('', views.HomePageView.as_view(), name='homepage'),
    path('patient-search/', views.PatientSearchView.as_view(), name='patient_search'),
    path('patient-summary/', views.PatientSummaryView.as_view(), name='patient_summary'),
    path('patient-data-export/', views.PatientDataExportView.as_view(), name='patient_data_export'),
    path('dicom-data-export/', views.DICOMDataExportView.as_view(), name='dicom_data_export'),
    path('dicom-export-progress/<str:task_id>/', views.DICOMExportProgressView.as_view(), name='dicom_export_progress'),
    path('dicom-export-download/<str:task_id>/', views.DICOMExportDownloadView.as_view(), name='dicom_export_download'),
    
    # Bulk DICOM Upload URLs
    path('bulk-dicom-upload/', views.BulkDICOMUploadView.as_view(), name='bulk_dicom_upload'),
    path('bulk-dicom-matching/<uuid:session_id>/', views.BulkDICOMMatchingView.as_view(), name='bulk_dicom_matching'),
    path('bulk-dicom-confirmation/<uuid:session_id>/', views.BulkDICOMConfirmationView.as_view(), name='bulk_dicom_confirmation'),
    path('bulk-dicom-complete/<uuid:session_id>/', views.BulkDICOMCompleteView.as_view(), name='bulk_dicom_complete'),
    
    # API endpoint for patient search (Select2)
    path('api/patient-search/', views.PatientSearchAPIView.as_view(), name='api_patient_search'),
    
    # Lookup API endpoints
    path('api/lookup_data/', include('lookup.urls')),
]


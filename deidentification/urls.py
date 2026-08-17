from django.urls import path, re_path

from . import views

app_name = 'deidentification'

urlpatterns = [
    path('', views.DeidPatientListView.as_view(), name='patient_list'),
    path('bulk-deidentify/', views.BulkDeidentifyView.as_view(), name='bulk_deidentify'),
    path('download/', views.DeidDownloadView.as_view(), name='bulk_download'),
    re_path(r'^patient/(?P<patient_id>.+)/deidentify/$', views.TriggerDeidentificationView.as_view(), name='trigger_deidentify'),
    re_path(r'^patient/(?P<patient_id>.+)/download/$', views.DeidDownloadView.as_view(), name='download'),
    re_path(r'^patient/(?P<patient_id>.+)/download-clinical/$', views.DeidClinicalDownloadView.as_view(), name='download_clinical'),
    re_path(r'^patient/(?P<patient_id>.+)/$', views.DeidPatientDetailView.as_view(), name='patient_detail'),
    path('download-clinical/', views.DeidClinicalDownloadView.as_view(), name='bulk_download_clinical'),
    path('job/<int:job_id>/status/', views.JobStatusView.as_view(), name='job_status'),
    path('job/<int:job_id>/download/', views.DeidDownloadView.as_view(), name='download'),
    path('legacy-import/', views.LegacyImportView.as_view(), name='legacy_import'),
    path('legacy-import/<int:task_id>/results/', views.LegacyImportResultsView.as_view(), name='legacy_import_results'),
    path('legacy-import/create-patient/', views.CreateMissingPatientView.as_view(), name='create_patient'),
    path('legacy-import/create-study/', views.CreateMissingStudyView.as_view(), name='create_study'),
    path('legacy-import/create-series/', views.CreateMissingSeriesView.as_view(), name='create_series'),
    path('legacy-import/create-instance/', views.CreateMissingInstanceView.as_view(), name='create_instance'),
    path('legacy-import/bulk-create/', views.BulkCreateMissingView.as_view(), name='bulk_create'),
    path('legacy-import/<int:task_id>/create-all/', views.BulkCreateMissingView.as_view(), name='create_all'),
    path('download-result/<int:task_id>/', views.DownloadResultView.as_view(), name='download_result'),
]

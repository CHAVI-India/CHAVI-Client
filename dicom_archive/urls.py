from django.urls import path

from dicom_archive import views

app_name = 'dicom_archive'

urlpatterns = [
    path('', views.ArchiveDashboardView.as_view(), name='dashboard'),
    path('config/', views.ArchiveConfigUpdateView.as_view(), name='config_edit'),
    path('locations/', views.ArchiveLocationListView.as_view(), name='location_list'),
    path('locations/test/', views.LocationTestView.as_view(), name='location_test'),
    path('locations/add/', views.ArchiveLocationCreateView.as_view(), name='location_create'),
    path('locations/<int:pk>/edit/', views.ArchiveLocationUpdateView.as_view(), name='location_update'),
    path('locations/<int:pk>/delete/', views.ArchiveLocationDeleteView.as_view(), name='location_delete'),
    path('browse/', views.LocalStudyBrowserView.as_view(), name='browse'),
    path('archived/', views.ArchivedStudyListView.as_view(), name='archived_list'),
    path('archive/', views.ManualArchiveView.as_view(), name='archive_trigger'),
    path('dearchive/', views.ManualDearchiveView.as_view(), name='dearchive_trigger'),
    path('task-status/<str:task_run_id>/', views.TaskStatusView.as_view(), name='task_status'),
]

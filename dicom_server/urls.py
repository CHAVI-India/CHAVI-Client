from django.urls import path

from dicom_server import views

app_name = 'dicom_server'

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('config/', views.ConfigUpdateView.as_view(), name='config_edit'),
    path('nodes/', views.RemoteNodeListView.as_view(), name='node_list'),
    path('nodes/add/', views.RemoteNodeCreateView.as_view(), name='node_create'),
    path('nodes/<int:pk>/edit/', views.RemoteNodeUpdateView.as_view(), name='node_update'),
    path('nodes/<int:pk>/delete/', views.RemoteNodeDeleteView.as_view(), name='node_delete'),
    path('nodes/<int:pk>/echo/', views.RemoteNodeEchoView.as_view(), name='node_echo'),
    path('nodes/<int:pk>/capabilities/', views.RemoteNodeCapabilitiesView.as_view(), name='node_capabilities'),
    path('retrieve/', views.RetrieveStudiesView.as_view(), name='retrieve'),
    path('retrieve/bulk/', views.BulkRetrieveView.as_view(), name='retrieve_bulk'),
    path('retrieve/bulk/patients/', views.BulkPatientListView.as_view(), name='bulk_patients'),
    path('retrieve/bulk/lookups/', views.BulkLookupSearchView.as_view(), name='bulk_lookups'),
    path('retrieve/bulk/query/', views.BatchQueryView.as_view(), name='batch_query'),
    path('retrieve/bulk/<int:pk>/select/', views.BatchSelectView.as_view(), name='batch_select'),
    path('retrieve/bulk/<int:pk>/status/', views.BatchStatusView.as_view(), name='batch_status'),
    path('retrieve/bulk/<int:pk>/alias/', views.PatientAliasCreateView.as_view(), name='batch_alias'),
    path('retrieve/bulk/<int:pk>/requery/', views.PatientRequeryView.as_view(), name='batch_requery'),
    path('retrieve/bulk/<int:pk>/retrieve/', views.BatchRetrieveView.as_view(), name='batch_retrieve'),
    path('nodes/<int:pk>/id-rules/', views.NodeIDRulesView.as_view(), name='node_id_rules'),
    path('batches/', views.BatchListView.as_view(), name='batch_list'),
    path('batches/<int:pk>/', views.BatchDetailView.as_view(), name='batch_detail'),
    path('jobs/', views.RetrievalJobListView.as_view(), name='job_list'),
    path('jobs/<int:pk>/', views.RetrievalJobDetailView.as_view(), name='job_detail'),
]

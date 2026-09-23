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
    path('retrieve/', views.RetrieveStudiesView.as_view(), name='retrieve'),
    path('jobs/', views.RetrievalJobListView.as_view(), name='job_list'),
    path('jobs/<int:pk>/', views.RetrievalJobDetailView.as_view(), name='job_detail'),
]

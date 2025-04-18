from django.urls import path
from . import views

app_name = 'client_app'  # This defines the namespace

urlpatterns = [
    path('patient-search/', views.PatientSearchView.as_view(), name='patient_search'),
    path('patient-summary/', views.PatientSummaryView.as_view(), name='patient_summary'),
]


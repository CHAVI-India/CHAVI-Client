"""
URL configuration for data import wizard.
"""
from django.urls import path
from data_import.views import (
    Step1UploadView,
    Step5ValidationView,
    Step6LookupMatchingView,
    Step7UUIDMappingView,
    Step8ImportView,
)
from data_import.views.step2_field_mapping import Step2FieldMappingView

app_name = 'data_import'

urlpatterns = [
    # Wizard steps
    path('', Step1UploadView.as_view(), name='import_step1_upload'),
    path('<int:import_id>/map-fields/', Step2FieldMappingView.as_view(), name='import_step2_field_mapping'),
    path('<int:import_id>/validate/', Step5ValidationView.as_view(), name='import_step3_validation'),
    path('<int:import_id>/lookup-matching/', Step6LookupMatchingView.as_view(), name='import_step4_lookup_matching'),
    path('<int:import_id>/uuid-mapping/', Step7UUIDMappingView.as_view(), name='import_step5_uuid_mapping'),
    path('<int:import_id>/import/', Step8ImportView.as_view(), name='import_step6_import'),
]

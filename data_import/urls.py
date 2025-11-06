"""
URL configuration for data import wizard.
"""
from django.urls import path
from data_import.views import (
    Step1UploadView,
    Step2FieldMappingView,
    Step3DateFormatConfigView,
    Step4DateIntervalConfigView,
    Step5ValidationView,
    Step6LookupMatchingView,
    Step7StaticMappingView,
    Step8UUIDMappingView,
    Step8_5UUIDMatchingView,
    Step9ImportView,
    Step10ExecuteView,
)

app_name = 'data_import'

urlpatterns = [
    # Wizard steps
    path('', Step1UploadView.as_view(), name='import_step1_upload'),
    path('<int:import_id>/map-fields/', Step2FieldMappingView.as_view(), name='import_step2_field_mapping'),
    path('<int:import_id>/date-formats/', Step3DateFormatConfigView.as_view(), name='import_step3_date_format_config'),
    path('<int:import_id>/date-intervals/', Step4DateIntervalConfigView.as_view(), name='import_step4_date_interval_config'),
    path('<int:import_id>/validate/', Step5ValidationView.as_view(), name='import_step5_validation'),
    path('<int:import_id>/lookup-matching/', Step6LookupMatchingView.as_view(), name='import_step6_lookup_matching'),
    path('<int:import_id>/static-mapping/', Step7StaticMappingView.as_view(), name='import_step7_static_mapping'),
    path('<int:import_id>/uuid-mapping/', Step8UUIDMappingView.as_view(), name='import_step8_uuid_mapping'),
    path('<int:import_id>/uuid-matching/', Step8_5UUIDMatchingView.as_view(), name='import_step8_5_uuid_matching'),
    path('<int:import_id>/json-preview/', Step9ImportView.as_view(), name='import_step9_json_preview'),
    path('<int:import_id>/execute/', Step10ExecuteView.as_view(), name='import_step10_execute'),
]

"""
URL configuration for data import wizard.
"""

from django.urls import path
from .views import (
    ImportSessionListView,
    Step1UploadCSVView,
    Step2PatientIDMappingView,
    Step3ModelSelectionView,
    Step4FieldMappingView,
    Step5ColumnValueMappingView,
    Step6DateFormatView,
    Step7DurationDateView,
    Step8LookupMappingView,
    Step9DefaultValuesView,
    Step10MissingRelationsView,
    Step11ReviewView,
    Step12ExecuteImportView,
)

app_name = 'data_import'

urlpatterns = [
    # List all import sessions
    path('', ImportSessionListView.as_view(), name='session_list'),
    
    # Step 1: Upload CSV
    path('step1/', Step1UploadCSVView.as_view(), name='step1'),
    path('step1/<int:session_id>/', Step1UploadCSVView.as_view(), name='step1_edit'),
    
    # Step 2: Patient ID Mapping
    path('step2/<int:session_id>/', Step2PatientIDMappingView.as_view(), name='step2'),
    
    # Step 3: Model Selection
    path('step3/<int:session_id>/', Step3ModelSelectionView.as_view(), name='step3'),
    
    # Step 4: Field Mapping
    path('step4/<int:session_id>/', Step4FieldMappingView.as_view(), name='step4'),
    
    # Step 5: Column Value Mapping
    path('step5/<int:session_id>/', Step5ColumnValueMappingView.as_view(), name='step5'),
    
    # Step 6: Date Format
    path('step6/<int:session_id>/', Step6DateFormatView.as_view(), name='step6'),
    
    # Step 7: Duration Date Calculation
    path('step7/<int:session_id>/', Step7DurationDateView.as_view(), name='step7'),
    
    # Step 8: Lookup Mapping
    path('step8/<int:session_id>/', Step8LookupMappingView.as_view(), name='step8'),
    
    # Step 9: Default Values
    path('step9/<int:session_id>/', Step9DefaultValuesView.as_view(), name='step9'),
    
    # Step 10: Missing Relations
    path('step10/<int:session_id>/', Step10MissingRelationsView.as_view(), name='step10'),
    
    # Step 11: Review JSON
    path('step11/<int:session_id>/', Step11ReviewView.as_view(), name='step11'),
    
    # Step 12: Execute Import
    path('step12/<int:session_id>/', Step12ExecuteImportView.as_view(), name='step12'),
]

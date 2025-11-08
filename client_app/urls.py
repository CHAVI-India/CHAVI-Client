from django.urls import path, include
from . import views
from . import form_views
from . import list_views

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
    
    # Patient-level form URLs
    path('comorbidity/add/', form_views.ComorbidityCreateView.as_view(), name='comorbidity_add'),
    path('symptom/add/', form_views.SymptomCreateView.as_view(), name='symptom_add'),
    path('patient-assessment/add/', form_views.PatientAssessmentCreateView.as_view(), name='patientassessment_add'),
    path('laboratory-results/add/', form_views.LaboratoryResultsCreateView.as_view(), name='laboratoryresults_add'),
    path('patient-outcome/add/', form_views.PatientOutcomeCreateView.as_view(), name='patientoutcome_add'),
    path('patient-reported-outcome/add/', form_views.PatientReportedOutcomeCreateView.as_view(), name='patientreportedoutcome_add'),
    path('germline-genomic-alterations/add/', form_views.GermlineGenomicAlterationsCreateView.as_view(), name='germlinegenomicalterations_add'),
    path('dicom-file/add/', form_views.PatientDicomFileCreateView.as_view(), name='patientdicomfile_add'),
    
    # Diagnosis-level form URLs
    path('diagnosis/add/', form_views.DiagnosisCreateView.as_view(), name='diagnosis_add'),
    path('diagnosis/<uuid:pk>/edit/', form_views.DiagnosisUpdateView.as_view(), name='diagnosis_edit'),
    path('pathology/add/', form_views.PathologyCreateView.as_view(), name='pathology_add'),
    path('stage-information/add/', form_views.StageInformationCreateView.as_view(), name='stageinformation_add'),
    path('lesion/add/', form_views.LesionCreateView.as_view(), name='lesion_add'),
    path('lesion-response/add/', form_views.LesionResponseCreateView.as_view(), name='lesionresponse_add'),
    path('surgery/add/', form_views.SurgeryCreateView.as_view(), name='surgery_add'),
    path('radiotherapy/add/', form_views.RadiotherapyCreateView.as_view(), name='radiotherapy_add'),
    path('systemic-therapy/add/', form_views.SystemicTherapyCreateView.as_view(), name='systemictherapy_add'),
    path('other-treatment/add/', form_views.OtherTreatmentCreateView.as_view(), name='othertreatment_add'),
    path('concomitant-medications/add/', form_views.ConcomitantMedicationsCreateView.as_view(), name='concomitantmedications_add'),
    path('outcome/add/', form_views.OutcomeCreateView.as_view(), name='outcome_add'),
    path('adverse-effects/add/', form_views.AdverseEffectsCreateView.as_view(), name='adverseeffects_add'),
    
    # Pathology sub-forms
    path('immunohistochemistry/add/', form_views.ImmunohistochemistryCreateView.as_view(), name='immunohistochemistry_add'),
    path('cytogenetics/add/', form_views.CytogeneticsCreateView.as_view(), name='cytogenetics_add'),
    path('somatic-genomic-alterations/add/', form_views.SomaticGenomicAlterationsCreateView.as_view(), name='somaticgenomicalterations_add'),
    path('gene-expression-data/add/', form_views.GeneExpressionDataCreateView.as_view(), name='geneexpressiondata_add'),
    path('epigenetic-data/add/', form_views.EpigeneticDataCreateView.as_view(), name='epigeneticdata_add'),
    
    # Radiotherapy sub-forms
    path('radiotherapy-volume/add/', form_views.RadiotherapyVolumeCreateView.as_view(), name='radiotherapyvolume_add'),
    path('radiotherapy-dose-volume-data/add/', form_views.RadiotherapyDoseVolumeDataCreateView.as_view(), name='radiotherapydosevolumedata_add'),
    
    # Systemic Therapy sub-forms
    path('systemic-therapy-schedule/add/', form_views.SystemicTherapyScheduleCreateView.as_view(), name='systemictherapyschedule_add'),
    
    # List and Edit URLs
    # Patient-level
    path('comorbidity/', list_views.ComorbidityListView.as_view(), name='comorbidity_list'),
    path('comorbidity/<uuid:pk>/edit/', list_views.ComorbidityUpdateView.as_view(), name='comorbidity_edit'),
    path('symptom/', list_views.SymptomListView.as_view(), name='symptom_list'),
    path('symptom/<uuid:pk>/edit/', list_views.SymptomUpdateView.as_view(), name='symptom_edit'),
    path('patient-assessment/', list_views.PatientAssessmentListView.as_view(), name='patientassessment_list'),
    path('patient-assessment/<uuid:pk>/edit/', list_views.PatientAssessmentUpdateView.as_view(), name='patientassessment_edit'),
    path('laboratory-results/', list_views.LaboratoryResultsListView.as_view(), name='laboratoryresults_list'),
    path('laboratory-results/<uuid:pk>/edit/', list_views.LaboratoryResultsUpdateView.as_view(), name='laboratoryresults_edit'),
    path('patient-outcome/', list_views.PatientOutcomeListView.as_view(), name='patientoutcome_list'),
    path('patient-outcome/<uuid:pk>/edit/', list_views.PatientOutcomeUpdateView.as_view(), name='patientoutcome_edit'),
    path('patient-reported-outcome/', list_views.PatientReportedOutcomeListView.as_view(), name='patientreportedoutcome_list'),
    path('patient-reported-outcome/<uuid:pk>/edit/', list_views.PatientReportedOutcomeUpdateView.as_view(), name='patientreportedoutcome_edit'),
    path('germline-genomic-alterations/', list_views.GermlineGenomicAlterationsListView.as_view(), name='germlinegenomicalterations_list'),
    path('germline-genomic-alterations/<uuid:pk>/edit/', list_views.GermlineGenomicAlterationsUpdateView.as_view(), name='germlinegenomicalterations_edit'),
    
    # Diagnosis-level
    path('diagnosis/', list_views.DiagnosisListView.as_view(), name='diagnosis_list'),
    path('pathology/', list_views.PathologyListView.as_view(), name='pathology_list'),
    path('pathology/<uuid:pk>/edit/', list_views.PathologyUpdateView.as_view(), name='pathology_edit'),
    path('stage-information/', list_views.StageInformationListView.as_view(), name='stageinformation_list'),
    path('stage-information/<uuid:pk>/edit/', list_views.StageInformationUpdateView.as_view(), name='stageinformation_edit'),
    path('lesion/', list_views.LesionListView.as_view(), name='lesion_list'),
    path('lesion/<uuid:pk>/edit/', list_views.LesionUpdateView.as_view(), name='lesion_edit'),
    path('surgery/', list_views.SurgeryListView.as_view(), name='surgery_list'),
    path('surgery/<uuid:pk>/edit/', list_views.SurgeryUpdateView.as_view(), name='surgery_edit'),
    path('radiotherapy/', list_views.RadiotherapyListView.as_view(), name='radiotherapy_list'),
    path('radiotherapy/<uuid:pk>/edit/', list_views.RadiotherapyUpdateView.as_view(), name='radiotherapy_edit'),
    path('systemic-therapy/', list_views.SystemicTherapyListView.as_view(), name='systemictherapy_list'),
    path('systemic-therapy/<uuid:pk>/edit/', list_views.SystemicTherapyUpdateView.as_view(), name='systemictherapy_edit'),
    path('other-treatment/', list_views.OtherTreatmentListView.as_view(), name='othertreatment_list'),
    path('other-treatment/<uuid:pk>/edit/', list_views.OtherTreatmentUpdateView.as_view(), name='othertreatment_edit'),
    path('concomitant-medications/', list_views.ConcomitantMedicationsListView.as_view(), name='concomitantmedications_list'),
    path('concomitant-medications/<uuid:pk>/edit/', list_views.ConcomitantMedicationsUpdateView.as_view(), name='concomitantmedications_edit'),
    path('outcome/', list_views.OutcomeListView.as_view(), name='outcome_list'),
    path('outcome/<uuid:pk>/edit/', list_views.OutcomeUpdateView.as_view(), name='outcome_edit'),
    path('adverse-effects/', list_views.AdverseEffectsListView.as_view(), name='adverseeffects_list'),
    path('adverse-effects/<uuid:pk>/edit/', list_views.AdverseEffectsUpdateView.as_view(), name='adverseeffects_edit'),
    path('lesion-response/', list_views.LesionResponseListView.as_view(), name='lesionresponse_list'),
    path('lesion-response/<uuid:pk>/edit/', list_views.LesionResponseUpdateView.as_view(), name='lesionresponse_edit'),
    
    # Pathology child models
    path('immunohistochemistry/', list_views.ImmunohistochemistryListView.as_view(), name='immunohistochemistry_list'),
    path('immunohistochemistry/<uuid:pk>/edit/', list_views.ImmunohistochemistryUpdateView.as_view(), name='immunohistochemistry_edit'),
    path('cytogenetics/', list_views.CytogeneticsListView.as_view(), name='cytogenetics_list'),
    path('cytogenetics/<uuid:pk>/edit/', list_views.CytogeneticsUpdateView.as_view(), name='cytogenetics_edit'),
    path('somatic-genomic-alterations/', list_views.SomaticGenomicAlterationsListView.as_view(), name='somaticgenomicalterations_list'),
    path('somatic-genomic-alterations/<uuid:pk>/edit/', list_views.SomaticGenomicAlterationsUpdateView.as_view(), name='somaticgenomicalterations_edit'),
    path('gene-expression-data/', list_views.GeneExpressionDataListView.as_view(), name='geneexpressiondata_list'),
    path('gene-expression-data/<uuid:pk>/edit/', list_views.GeneExpressionDataUpdateView.as_view(), name='geneexpressiondata_edit'),
    path('epigenetic-data/', list_views.EpigeneticDataListView.as_view(), name='epigeneticdata_list'),
    path('epigenetic-data/<uuid:pk>/edit/', list_views.EpigeneticDataUpdateView.as_view(), name='epigeneticdata_edit'),
    
    # Systemic Therapy child models
    path('systemic-therapy-schedule/', list_views.SystemicTherapyScheduleListView.as_view(), name='systemictherapyschedule_list'),
    path('systemic-therapy-schedule/<uuid:pk>/edit/', list_views.SystemicTherapyScheduleUpdateView.as_view(), name='systemictherapyschedule_edit'),
    
    # Radiotherapy child models
    path('radiotherapy-volume/', list_views.RadiotherapyVolumeListView.as_view(), name='radiotherapyvolume_list'),
    path('radiotherapy-volume/<uuid:pk>/edit/', list_views.RadiotherapyVolumeUpdateView.as_view(), name='radiotherapyvolume_edit'),
    path('radiotherapy-dose-volume/', list_views.RadiotherapyDoseVolumeDataListView.as_view(), name='radiotherapydosevolumedata_list'),
    path('radiotherapy-dose-volume/<uuid:pk>/edit/', list_views.RadiotherapyDoseVolumeDataUpdateView.as_view(), name='radiotherapydosevolumedata_edit'),
]


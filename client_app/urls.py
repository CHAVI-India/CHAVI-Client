from django.urls import path, include
from . import views
from . import form_views

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
]


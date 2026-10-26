# Graph Report - CHAVI-Client  (2026-10-25)

## Corpus Check
- 637 files · ~918,350 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 270 file(s) not represented in the graph (top: .doctree 152, .css 51, (none) 23)

## Summary
- 4960 nodes · 11556 edges · 277 communities (102 shown, 175 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 1292 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3b5cc7a6`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Extraction Mgmt Commands
- logging
- Extractor Forms & Deid Config
- ingest.py
- InstructorExtractionService
- Bulk Retrieval Scheduling
- SiteConfiguration
- DRF Serializers
- RbacPermissionRequiredMixin
- extractor/tests.py
- DICOM Server Forms & Views
- FileUpload
- DICOM QR Client (Query/Retrieve)
- Clinical Data Forms
- Extraction Review & Record Ops
- Celery Tasks & TaskRun
- Clinical List Views
- classifier.py
- Clinical Form Views (CRUD)
- Data Import Forms
- DICOM C-STORE Ingest & QR
- Data Import Model Writers
- Clinical Update Views
- django_db
- Bulk Patient Study Query
- EmbeddingConfiguration
- Data Import Field Introspection
- Extractor Admin
- Django Admin Registrations
- App Configs (ready hooks)
- django_db_models_deletion
- Admin Export Resources & Settings
- dicom_server/signals.py
- LLM Extraction UI Pages
- Bulk DICOM Selection Logic
- RemoteDICOMNodeForm
- DICOM Ingest Service
- ArchiveLocation
- Navbar Visibility Tests
- django_core_validators
- ModelAdmin
- BulkScheduleForm
- DICOM Instance Selection
- make_study
- Patient
- patient_data.py
- .stage_extract
- deid_meddeid_ab.py
- url_policy.py
- .get
- JSONGeneratorService
- SchemaDiscoveryService
- 0035_recover_archived_studies.py
- Allauth Auth UI
- encrypted_model_fields_fields
- ArchiveLocationForm
- RetrievalBatchPatient
- AutoRetrievalTaskTests
- EmbeddingIndexTests
- MigrationBase
- LlmNerClient
- InferenceContractTests
- OpenMedNerRecognizer
- ModelPermissionMixin
- query.py
- data_import/models.py
- Data Import Wizard
- ArchiveViewTestCase
- make_field
- Step1UploadCSVForm
- .deidentify
- Notification
- TemplateView
- llm_ner.py
- TestNodeCRUD
- StagedPipelineTests
- DurationFilterTests
- FileImportJSON
- LookupMiningTests
- TestPageRendering
- find_patient
- make_rt_dataset
- DICOM Server
- 0029_rbac_roles.py
- FolderPathMigrationTests
- LoopbackSCPTests
- model_capabilities.py
- ImportSessionListView
- DeidRecognizerTests
- SimpleTestCase
- LegacyImportServiceTests
- TestManualTriggers
- TaskRunListView
- deid_rules.py
- DICOM Archive
- qr_client.py
- deid_span_ab_test.py
- TextDeidentificationService
- RtInstanceSelectionE2ETests
- ForeignKeyInitMixin
- associate_dicom_files_to_project
- text_deidentification.py
- BulkDICOMMatchingView
- TestLocationTestView
- deidentify_processed_text_task
- resolve_spans
- ClientConfigurationDeidValidationTests
- LlmDeidEndToEndTests
- meddeid_pipeline_db_test.py
- DiagnosisImportSerializer
- PatientAutoRetrievalSignalTests
- .load
- import_filters.py
- TestLocationCrud
- _SourceIndex
- GapFillTests
- 0011_databasefield_relation_content_type_and_more.py
- DeidPipelineResolutionTests
- chunk_text
- system1_judge.py
- components
- 0034_fix_dicomstudy_folder_paths.py
- ClinicalAllowlistTests
- export_dicom_data
- DateFormatParser
- DICOMStudyListView
- BulkDICOMConfirmationView
- UUIDManager
- ExtractionPlanTests
- _StubRemotePACS
- DICOMDataExportView
- Django Admin UI
- AccountAdapter
- import_serializers.py
- PatientDataExportView
- Comorbidity
- _upsert_study
- Symptom
- DICOM Data Export
- EpigeneticData
- DicomFrontendTestCase
- extractor_filters.py
- PatientOutcome
- Bulk DICOM Import
- DICOMStudyAdmin
- RadiotherapyAdmin
- BulkDICOMUploadView
- PatientSearchView
- TestTaskStatusView
- deid_prefetch_model.py
- LlmNerRecognizer
- De-identification
- AdverseEffectsResource
- ComorbidityResource
- ConcomitantMedicationsResource
- CytogeneticsResource
- DiagnosisResource
- EpigeneticDataResource
- GeneExpressionDataResource
- GermlineGenomicAlterationsResource
- ImmnuohistochemistryResource
- LaboratoryResultsResource
- LesionResource
- LesionResponseResource
- OtherTreatmentResource
- OutcomeResource
- PathologyResource
- PatientAssessmentResource
- PatientOutcomeResource
- PatientReportedOutcomeResource
- RadiotherapyDoseVolumeDataResource
- RadiotherapyResource
- RadiotherapyVolumeResource
- SomaticGenomicAlterationsResource
- StageInformationResource
- SurgeryResource
- SymptomResource
- SystemicTherapyResource
- SystemicTherapyScheduleResource
- TaskResultAdmin
- LesionImportSerializer
- DateValidationMixin
- Cytogenetics
- resources.py
- TaskRegistryCoverageTests
- GermlineGenomicAlterations
- Lesion
- TestNavIntegration
- TestLocationTestButtons
- TestPermissionGating
- 0034_seed_default_pipeline.py
- DiagnosisListView
- Diagnosis
- EpigeneticDataListView
- SomaticGenomicAlterations
- CHAVI-Client
- PatientAssessmentListView
- StageInformation
- AppScaffoldTests
- 0028_backfill_canonical_patient_id.py
- Base Layout & Auth
- Patient Management
- Task Management
- AdverseEffectImportSerializer
- ComorbidityImportSerializer
- CytogeneticsImportSerializer
- EpigeneticDataImportSerializer
- GeneExpressionDataImportSerializer
- GermlineGenomicAlterationsImportSerializer
- ImmunohistochemistryImportSerializer
- LaboratoryResultsImportSerializer
- LesionResponseImportSerializer
- OtherTreatmentImportSerializer
- PatientAssessmentImportSerializer
- PatientOutcomeImportSerializer
- PatientReportedOutcomeImportSerializer
- RadiotherapyImportSerializer
- SurgeryImportSerializer
- SystemicTherapyImportSerializer
- SymptomImportSerializer
- SomaticGenomicAlterationsImportSerializer
- 0002_enable_pgvector.py
- 0002_comorbidity_comorbidity_resolved_and_more.py
- 0006_alter_symptom_duration_of_symptom.py
- 0009_patientdicomfile_processed_and_more.py
- 0010_dicomstudyproject_updated_at.py
- PathologyAdmin
- 0011_dicomstudy_study_type.py
- 0030_alter_taskrun_task_type.py
- 0007_databasetable_date_validation_pairs.py
- 0019_extractionjob_stage_trace_and_more.py
- 0022_remove_lookupembedding_unique_lookup_embedding_and_more.py
- 0024_processedtext_deid_map.py
- 0025_alter_clientconfiguration_context_size_and_more.py
- 0027_model_max_tokens_nullable.py
- FK Relationship Tracking
- Extractor App (LLM Extraction)
- Index (page)
- Indian Locations Reference Data
- Indian Names Reference Data
- API Connection Testing
- Pydantic Model Builder

## God Nodes (most connected - your core abstractions)
1. `Patient` - 108 edges
2. `DICOMStudy` - 90 edges
3. `RemoteDICOMNode` - 81 edges
4. `Base (page)` - 79 edges
5. `InstructorExtractionService` - 78 edges
6. `UnifiedClinicalDataResource` - 70 edges
7. `ArchiveLocation` - 59 edges
8. `TaskRun` - 56 edges
9. `SiteConfiguration` - 54 edges
10. `QRClientTests` - 53 edges

## Surprising Connections (you probably didn't know these)
- `Extractor App (LLM Extraction)` --conceptually_related_to--> `LLM-Powered Data Extraction`  [INFERRED]
  extractor/PROGRESS.md → templates/extractor/client_configuration_create.html
- `RetrieveStudiesForm` --uses--> `Patient`  [INFERRED]
  dicom_server/forms.py → client_app/models.py
- `StuckBatchRecoveryTests` --uses--> `RetrievalBatch`  [INFERRED]
  client_app/tests_task_resume.py → dicom_server/models.py
- `BulkPatientListView` --uses--> `Diagnosis`  [INFERRED]
  dicom_server/views.py → client_app/models.py
- `BulkPatientListView` --uses--> `Patient`  [INFERRED]
  dicom_server/views.py → client_app/models.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Data Import Wizard 12-Step Flow** — feature_data_import_wizard, data_import_workflow_csvimport, data_import_workflow_hierarchyconstraint, data_import_step10_missingfk [INFERRED 0.80]
- **DICOM Archive Access Control** — feature_dicom_archive, dicom_archive_permissions_modelperms, dicom_archive_permissions_dicomadminrole, dicom_archive_permissions_archiveoperator [INFERRED 0.80]
- **LLM Extraction Pipeline** — feature_llm_extraction, extractor_progress_schemadiscoveryservice, extractor_progress_pydanticbuilder, extractor_progress_stage2_extraction [INFERRED 0.80]

## Communities (277 total, 175 thin omitted)

### Community 0 - "Extraction Mgmt Commands"
Cohesion: 0.05
Nodes (12): ResponseModelTableField, Meta, PydanticModelBuilder, check(), build_node(), emit(), check(), validate_field_assessments() (+4 more)

### Community 1 - "logging"
Cohesion: 0.04
Nodes (25): Command, LookupEmbedding, Meta, collect_pending_rows(), compute_lookup_embeddings(), compute_lookup_table_embeddings(), embed_one_chunk(), finalize_lookup_index() (+17 more)

### Community 2 - "Extractor Forms & Deid Config"
Cohesion: 0.03
Nodes (70): ExtractionRecordReviewForm, ReviewApprovalForm, TextDeidentificationPipelineConfigForm, Meta, ClientConfiguration, Meta, ExtractionReviewBatch, Meta (+62 more)

### Community 3 - "ingest.py"
Cohesion: 0.06
Nodes (22): Migration, Migration, BulkDICOMStudyMatch, MatchStatus, Meta, DICOMInstance, Meta, DICOMSeries (+14 more)

### Community 4 - "InstructorExtractionService"
Cohesion: 0.08
Nodes (8): ExtractionJob, Meta, InstructorExtractionService, clean_records(), run_entry(), skip_descendants(), submit(), DeidUnshiftOnSaveTests

### Community 5 - "Bulk Retrieval Scheduling"
Cohesion: 0.05
Nodes (20): BulkRetrievalSchedule, Meta, Mode, _prepare_bulk_schedule_batch(), AggregateTests, BulkRetrievalScheduleModelTests, BulkScheduleTemplateTests, BulkScheduleViewTests (+12 more)

### Community 6 - "SiteConfiguration"
Cohesion: 0.05
Nodes (32): SiteConfiguration, Meta, RetrievalSkipDoneTests, PatientIDAliasInline, RetrievalBatchAdmin, RetrievalJobStudyInline, PatientIDAlias, Meta (+24 more)

### Community 7 - "DRF Serializers"
Cohesion: 0.04
Nodes (71): AdverseEffectsSerializer, Meta, BaseSerializer, Meta, ComorbiditySerializer, Meta, ConcomitantMedicationsSerializer, Meta (+63 more)

### Community 8 - "RbacPermissionRequiredMixin"
Cohesion: 0.15
Nodes (4): DICOMExportDownloadView, DICOMExportProgressView, RbacPermissionRequiredMixin, TaskDownloadView

### Community 9 - "extractor/tests.py"
Cohesion: 0.04
Nodes (33): Command, match_records(), overlap(), norm_value(), score_records(), EntityTypeChoices, ResponseModelTable, Meta (+25 more)

### Community 10 - "DICOM Server Forms & Views"
Cohesion: 0.04
Nodes (31): DICOMServerConfigForm, Meta, RetrieveStudiesForm, BatchDetailView, BatchListView, BatchSelectView, BatchStatusView, BulkLookupSearchView (+23 more)

### Community 11 - "FileUpload"
Cohesion: 0.09
Nodes (6): FileUpload, Meta, ProcessingStatusChoices, FileProcessorService, _get_easyocr_reader(), ocr_processed_text_task()

### Community 12 - "DICOM QR Client (Query/Retrieve)"
Cohesion: 0.06
Nodes (3): find_studies_with_series(), QRClientTests, _StubPACS

### Community 13 - "Clinical Data Forms"
Cohesion: 0.06
Nodes (60): AdverseEffectsForm, Meta, ComorbidityForm, Meta, ConcomitantMedicationsForm, Meta, CrispyFormMixin, CytogeneticsForm (+52 more)

### Community 14 - "Extraction Review & Record Ops"
Cohesion: 0.07
Nodes (56): ExtractionResult, Meta, RecordOperationChoices, ResultSourceChoices, ReviewChangeChoices, ReviewStatusChoices, _apply_snapshot(), approve_review() (+48 more)

### Community 15 - "Celery Tasks & TaskRun"
Cohesion: 0.04
Nodes (49): BulkDICOMUploadSession, Meta, StatusChoices, Notification, Meta, NotificationType, PatientDicomFile, TaskRun (+41 more)

### Community 16 - "Clinical List Views"
Cohesion: 0.03
Nodes (25): BaseListView, AdverseEffectsListView, ComorbidityListView, ConcomitantMedicationsListView, CytogeneticsListView, GeneExpressionDataListView, GermlineGenomicAlterationsListView, ImmunohistochemistryListView (+17 more)

### Community 17 - "classifier.py"
Cohesion: 0.08
Nodes (20): BulkDICOMUpload, Meta, DICOMStudy, Meta, DICOMStudyProject, Meta, StudyTypeChoices, StudyTypeRule (+12 more)

### Community 18 - "Clinical Form Views (CRUD)"
Cohesion: 0.04
Nodes (30): AdverseEffectsCreateView, BaseFormView, ComorbidityCreateView, ConcomitantMedicationsCreateView, CytogeneticsCreateView, DiagnosisCreateView, EpigeneticDataCreateView, GeneExpressionDataCreateView (+22 more)

### Community 19 - "Data Import Forms"
Cohesion: 0.07
Nodes (16): FileImportSessionStep, FileMappedField, Meta, FileMappedModel, Meta, CSVProcessorService, FieldIntrospectionService, ModelHierarchyService (+8 more)

### Community 20 - "DICOM C-STORE Ingest & QR"
Cohesion: 0.04
Nodes (25): _trigger_auto_retrieval(), RemoteDICOMNode, Meta, _collect_subop_stats(), _connect(), echo(), find_series(), _find_series_on_assoc() (+17 more)

### Community 22 - "Clinical Update Views"
Cohesion: 0.05
Nodes (27): BaseUpdateView, AdverseEffectsUpdateView, ComorbidityUpdateView, ConcomitantMedicationsUpdateView, CytogeneticsUpdateView, EpigeneticDataUpdateView, GeneExpressionDataUpdateView, GermlineGenomicAlterationsUpdateView (+19 more)

### Community 23 - "django_db"
Cohesion: 0.03
Nodes (29): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+21 more)

### Community 24 - "Bulk Patient Study Query"
Cohesion: 0.06
Nodes (7): task_finalize_batch_query(), task_query_patient_studies(), _finish(), BulkPatientListTests, BulkViewTests, CandidateIDTests, QueryTaskTests

### Community 25 - "EmbeddingConfiguration"
Cohesion: 0.05
Nodes (22): ExtractorConfig, _warm_embedding_provider(), Command, BackgroundTask, Meta, EmbeddingConfiguration, Meta, _advance_to_next_table_or_finalize() (+14 more)

### Community 26 - "Data Import Field Introspection"
Cohesion: 0.06
Nodes (4): Step2PatientIDMappingForm, Step10MissingRelationsView, Step5ColumnValueMappingView, Step9DefaultValuesView

### Community 27 - "Extractor Admin"
Cohesion: 0.07
Nodes (21): ClientConfigurationAdmin, DatabaseFieldAdmin, DatabaseFieldInline, DatabaseTableAdmin, EmbeddingConfigurationAdmin, ExtractionJobAdmin, ExtractionResultAdmin, ExtractionResultInline (+13 more)

### Community 28 - "Django Admin Registrations"
Cohesion: 0.10
Nodes (37): AdverseEffectsAdmin, BulkDICOMUploadAdmin, ComorbidityAdmin, ConcomitantMedicationsAdmin, CytogeneticsAdmin, DiagnosisAdmin, DICOMStudyProjectAdmin, EpigeneticDataAdmin (+29 more)

### Community 29 - "App Configs (ready hooks)"
Cohesion: 0.05
Nodes (10): ClientAppConfig, DataImportConfig, FileColumnFieldValueMapping, Meta, FileParentRecordMapping, Meta, FilePatientID, Meta (+2 more)

### Community 30 - "django_db_models_deletion"
Cohesion: 0.06
Nodes (16): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+8 more)

### Community 31 - "Admin Export Resources & Settings"
Cohesion: 0.05
Nodes (29): AdverseEffectsExportResource, Meta, CytogeneticsInline, DiagnosisExportResource, Meta, DICOMStudyProjectInline, EpigeneticDataInline, GeneExpressionDataInline (+21 more)

### Community 32 - "dicom_server/signals.py"
Cohesion: 0.11
Nodes (13): Command, _dispatch_one_off(), _ensure_periodic(), revoke_one_off(), sync_bulk_schedule(), _periodic_task_name(), sync_all_node_schedules(), sync_node_schedule() (+5 more)

### Community 33 - "LLM Extraction UI Pages"
Cohesion: 0.09
Nodes (42): Extraction Wizard Flow, LLM-Powered Data Extraction, Base (page), Form Template (page), Homepage (page), Model List (page), Client Configuration Create (page), Client Configuration Detail (page) (+34 more)

### Community 34 - "Bulk DICOM Selection Logic"
Cohesion: 0.13
Nodes (19): ancestors_of(), _approval_visible(), build_selections_for_patient(), _dcm_date_to_iso(), descendants_of(), _plan_approval_state(), _rt_labels(), select_study() (+11 more)

### Community 35 - "RemoteDICOMNodeForm"
Cohesion: 0.12
Nodes (7): RemoteDICOMNodeForm, Meta, apply_transforms(), parse_transform_lines(), transforms_to_lines(), validate_transforms(), TransformTests

### Community 36 - "DICOM Ingest Service"
Cohesion: 0.14
Nodes (7): ingest_dataset(), reject(), IngestResult, sanitize(), _selection_reject_reason(), IngestDatasetTests, make_test_dataset()

### Community 37 - "ArchiveLocation"
Cohesion: 0.03
Nodes (39): ArchiveIdempotencyTests, ArchiveConfigurationAdmin, ArchivedStudyAdmin, ArchiveLocationAdmin, ArchiveConfiguration, Meta, ArchivedStudy, Meta (+31 more)

### Community 38 - "Navbar Visibility Tests"
Cohesion: 0.08
Nodes (4): NavbarVisibilityTests, PatientSummaryPermissionTests, PermissionGatingTests, RoleGroupTests

### Community 39 - "django_core_validators"
Cohesion: 0.10
Nodes (10): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+2 more)

### Community 40 - "ModelAdmin"
Cohesion: 0.12
Nodes (6): AutoRetrievalStateAdmin, DICOMServerConfigurationAdmin, InboundDICOMInstanceAdmin, RemoteDICOMNodeAdmin, RetrievalBatchPatientAdmin, RetrievalJobAdmin

### Community 41 - "BulkScheduleForm"
Cohesion: 0.29
Nodes (3): BulkScheduleForm, Meta, BulkScheduleFormTests

### Community 42 - "DICOM Instance Selection"
Cohesion: 0.11
Nodes (9): instance_ancestors(), normalize_selection(), SelectionError, _series_by_uid(), _sop_index(), sop_series_uid(), InstanceAncestorsTests, NormalizeSelectionTests (+1 more)

### Community 43 - "make_study"
Cohesion: 0.05
Nodes (25): archive_studies(), archive_study(), ArchiveError, _sanitize_segment(), _study_stats(), dearchival_required_for_studies(), dearchive_studies(), dearchive_study() (+17 more)

### Community 44 - "Patient"
Cohesion: 0.08
Nodes (21): Patient, Gender, Meta, _cache_old_consent(), _aggregate_retrieval_batch(), _dispatch_retrieval_chunk(), _fail_stuck_batch(), _finish_task_run_quiet() (+13 more)

### Community 45 - "patient_data.py"
Cohesion: 0.04
Nodes (42): ExtractedRecord, Meta, RecordCreation, Meta, RecordCreationField, Meta, build_job_data_tree(), build_patient_data_tree() (+34 more)

### Community 46 - ".stage_extract"
Cohesion: 0.15
Nodes (7): create(), TableExtractParallelTests, create(), create(), create(), TableExtractTests, create()

### Community 47 - "deid_meddeid_ab.py"
Cohesion: 0.18
Nodes (8): parse_tagged(), iou(), llm_chat(), main(), run_match(), run_tag(), score_span_f1(), _normalize_entity_type()

### Community 48 - "url_policy.py"
Cohesion: 0.10
Nodes (11): DataAccuracyChoices, DeidNerEngineChoices, _delete_processed_file(), ExtractionBasisChoices, file_upload_path(), ModelTypeChoices, ResultStateChoices, is_cloud_provider() (+3 more)

### Community 51 - "SchemaDiscoveryService"
Cohesion: 0.05
Nodes (6): Command, DatabaseField, Meta, DatabaseTable, Meta, SchemaDiscoveryService

### Community 52 - "0035_recover_archived_studies.py"
Cohesion: 0.11
Nodes (15): _check_patient_ids(), _delete_study_rows(), _dicom_date(), _expected_folder_path(), Migration, _parse_dt(), _parse_manifest(), recover_archived_studies() (+7 more)

### Community 53 - "Allauth Auth UI"
Cohesion: 0.08
Nodes (26): Allauth Auth UI, Alert (page), Badge (page), Button (page), Button Group (page), Details (page), Field (page), Fields (page) (+18 more)

### Community 54 - "encrypted_model_fields_fields"
Cohesion: 0.13
Nodes (7): Migration, Migration, Migration, Migration, Migration, Migration, Migration

### Community 55 - "ArchiveLocationForm"
Cohesion: 0.18
Nodes (6): ArchiveConfigurationForm, Meta, ArchiveLocationForm, Meta, TestArchiveConfigurationForm, TestArchiveLocationForm

### Community 56 - "RetrievalBatchPatient"
Cohesion: 0.23
Nodes (6): BulkRetrieveForm, RetrievalBatchPatient, Meta, QueryStatus, FormTests, BatchQueryView

### Community 57 - "AutoRetrievalTaskTests"
Cohesion: 0.16
Nodes (5): AutoRetrievalState, Meta, _auto_retrieve_patient_node(), AutoRetrievalTaskTests, _fake_async_result()

### Community 59 - "MigrationBase"
Cohesion: 0.16
Nodes (4): ArchiveRecoveryTests, make_dcm(), MigrationBase, VerifyLocalStudiesTests

### Community 62 - "OpenMedNerRecognizer"
Cohesion: 0.18
Nodes (3): OpenMedNerError, OpenMedNerRecognizer, OpenMedNerRecognizerTests

### Community 63 - "ModelPermissionMixin"
Cohesion: 0.11
Nodes (3): DiagnosisUpdateView, ModelPermissionMixin, PatientUpdateView

### Community 64 - "query.py"
Cohesion: 0.13
Nodes (8): _make_canonical_id(), PatientSearchAPIView, _fill(), iter_find_responses(), match_date(), match_value(), _patient_matches(), _wildcard_regex()

### Community 65 - "data_import/models.py"
Cohesion: 0.05
Nodes (28): Project, Meta, Step10ReviewForm, Step4FieldMappingForm, Step5ColumnValueMappingForm, Step6DateFormatForm, Step7DurationDateForm, Step8LookupMappingForm (+20 more)

### Community 66 - "Data Import Wizard"
Cohesion: 0.17
Nodes (17): Step 10 Missing FK Relationships, CSV Data Import Workflow, Data Import Wizard, Base Import (page), Session List (page), Step10 Missing Relations (page), Step11 Review (page), Step12 Complete (page) (+9 more)

### Community 68 - "make_field"
Cohesion: 0.16
Nodes (3): make_field(), make_response_model(), make_table()

### Community 72 - "Notification"
Cohesion: 0.11
Nodes (4): AutoContinueTaskTests, FlashMessageRenderingTests, ModelDocstringTests, TaskRunResumeRetryViewTests

### Community 73 - "TemplateView"
Cohesion: 0.20
Nodes (3): BulkDICOMCompleteView, HomePageView, PatientSummaryView

### Community 74 - "llm_ner.py"
Cohesion: 0.18
Nodes (4): LlmNerError, LlmNerParseError, _parse_entity_output(), LlmNerParseTests

### Community 76 - "StagedPipelineTests"
Cohesion: 0.15
Nodes (3): StagedPipelineTests, create(), StagePlanningTests

### Community 78 - "FileImportJSON"
Cohesion: 0.16
Nodes (5): PatientImportSerializer, Meta, FileImportJSON, Meta, ImportExecutorService

### Community 79 - "LookupMiningTests"
Cohesion: 0.06
Nodes (5): FieldSnippetEntry, describe(), walk(), LookupSnippetMap, LookupMiningTests

### Community 81 - "find_patient"
Cohesion: 0.17
Nodes (3): find_patient(), FindPatientTests, SanitizeTests

### Community 82 - "make_rt_dataset"
Cohesion: 0.30
Nodes (3): IngestSelectionFilterTests, make_rt_dataset(), _ref_sop_item()

### Community 83 - "DICOM Server"
Cohesion: 0.12
Nodes (16): DICOM Server, Batch Detail (page), Batch List (page), Batch Select (page), Config Form (page), Dashboard (page), Job Detail (page), Job List (page) (+8 more)

### Community 84 - "0029_rbac_roles.py"
Cohesion: 0.16
Nodes (5): Migration, add_archive_perms_to_dicom_admin(), _archive_perm_codenames(), Migration, remove_archive_perms_from_dicom_admin()

### Community 87 - "model_capabilities.py"
Cohesion: 0.27
Nodes (6): _discover_anthropic(), discover_capabilities(), _discover_ollama(), _discover_openai_compatible(), _is_reasoning_model(), _is_vision_model()

### Community 91 - "LegacyImportServiceTests"
Cohesion: 0.08
Nodes (7): _encrypt_value(), _ensure_site(), LegacyImportServiceTests, LegacyImportTaskTests, _make_legacy_db(), StuckBatchRecoveryTests, TaskProgressResumeBarTests

### Community 93 - "TaskRunListView"
Cohesion: 0.22
Nodes (3): BulkDICOMSessionListView, _get_visible_task_types(), TaskRunListView

### Community 94 - "deid_rules.py"
Cohesion: 0.24
Nodes (4): Migration, Migration, default_hf_label_map(), default_rules()

### Community 95 - "DICOM Archive"
Cohesion: 0.18
Nodes (11): Archive Operator Role, Archive Viewer Role, DICOM Administrator Role, DICOM Archive Permissions, DICOM Archive, Archived List (page), Browse (page), Config Edit (page) (+3 more)

### Community 96 - "qr_client.py"
Cohesion: 0.04
Nodes (28): DICOMServerConfiguration, Meta, InboundDICOMInstance, Meta, Status, _db_cleanup(), handle_echo(), handle_find() (+20 more)

### Community 97 - "deid_span_ab_test.py"
Cohesion: 0.16
Nodes (6): Command, llm_chat(), _norm_span(), run_match(), run_tag(), score_entities_pairs()

### Community 98 - "TextDeidentificationService"
Cohesion: 0.10
Nodes (5): _resolve_device(), _normalize_tag_key(), _shifted_date_text(), TextDeidentificationService, DeidReplacementTests

### Community 101 - "associate_dicom_files_to_project"
Cohesion: 0.33
Nodes (3): associate_dicom_files_to_project(), ProjectSelectionForm, Media

### Community 102 - "text_deidentification.py"
Cohesion: 0.18
Nodes (3): build_text_recognizers(), _load_gazetteer(), _FakeResult

### Community 109 - "meddeid_pipeline_db_test.py"
Cohesion: 0.14
Nodes (12): _aggregate(), _append_doc(), _load_done(), load_notes(), load_pipelines(), main(), match_ratio(), pipeline_info() (+4 more)

### Community 110 - "DiagnosisImportSerializer"
Cohesion: 0.22
Nodes (4): DiagnosisImportSerializer, Meta, PathologyImportSerializer, Meta

### Community 112 - ".load"
Cohesion: 0.11
Nodes (5): cleanup_study_files(), sync_archive_schedule(), ArchiveConfigurationTests, ArchiveConfigurationSignalTests, SyncArchiveScheduleTests

### Community 113 - "import_filters.py"
Cohesion: 0.28
Nodes (3): get_item(), get_nested_item(), index()

### Community 117 - "0011_databasefield_relation_content_type_and_more.py"
Cohesion: 0.25
Nodes (3): Migration, Migration, Migration

### Community 120 - "system1_judge.py"
Cohesion: 0.36
Nodes (4): build_context(), endpoint(), judge_span(), _so_post()

### Community 121 - "components"
Cohesion: 0.25
Nodes (7): components, button, card, custom_form, legacy_card, pagination, table

### Community 122 - "0034_fix_dicomstudy_folder_paths.py"
Cohesion: 0.38
Nodes (4): _expected_folder_path(), fix_dicomstudy_folder_paths(), Migration, _sanitize()

### Community 132 - "Django Admin UI"
Cohesion: 0.33
Nodes (5): Django Admin UI, Card (page), Change Form (page), Change List (page), Index (page)

### Community 139 - "DICOM Data Export"
Cohesion: 0.33
Nodes (5): Associate DICOM to Project (admin action), DICOM Data Export, Dicom Data Export (page), Dicom Export Progress (page), Dicomstudy List (page)

### Community 141 - "DicomFrontendTestCase"
Cohesion: 0.17
Nodes (3): DicomFrontendTestCase, TestConfigView, TestPermissionGating

### Community 144 - "Bulk DICOM Import"
Cohesion: 0.33
Nodes (6): Bulk DICOM Import, Bulk Dicom Complete (page), Bulk Dicom Confirmation (page), Bulk Dicom Matching (page), Bulk Dicom Session List (page), Bulk Dicom Upload (page)

### Community 152 - "De-identification"
Cohesion: 0.40
Nodes (5): De-identification, Legacy Import (page), Legacy Import Results (page), Patient Detail (page), Patient List (page)

### Community 182 - "DateValidationMixin"
Cohesion: 0.06
Nodes (15): AdverseEffects, Meta, ConcomitantMedications, Meta, DateValidationMixin, OtherTreatment, Meta, Radiotherapy (+7 more)

### Community 185 - "resources.py"
Cohesion: 0.04
Nodes (21): GeneExpressionData, Meta, LaboratoryResults, Meta, LesionResponse, Meta, ModalityChoices, Outcome (+13 more)

### Community 186 - "TaskRegistryCoverageTests"
Cohesion: 0.17
Nodes (4): TaskRegistryCoverageTests, task_run_can_resume(), TaskProgressView, TaskRunDetailView

### Community 196 - "Diagnosis"
Cohesion: 0.14
Nodes (6): Diagnosis, Meta, Immunohistochemistry, Meta, RadiotherapyDoseVolumeData, Meta

### Community 204 - "Base Layout & Auth"
Cohesion: 0.50
Nodes (3): Base Layout & Auth, 403 (page), Login (page)

### Community 205 - "Patient Management"
Cohesion: 0.50
Nodes (4): Patient Management, Patient Data Export (page), Patient Search (page), Patient Summary New (page)

### Community 206 - "Task Management"
Cohesion: 0.50
Nodes (4): Task Management, Task Progress (page), Taskrun Detail (page), Taskrun List (page)

## Knowledge Gaps
- **38 isolated node(s):** `Card (page)`, `403 (page)`, `FK Relationship Tracking`, `Schema Discovery Service`, `UI Styleguide` (+33 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 2114 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **175 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Patient` connect `Patient` to `Extractor Forms & Deid Config`, `ingest.py`, `InstructorExtractionService`, `Bulk Retrieval Scheduling`, `SiteConfiguration`, `DRF Serializers`, `_upsert_study`, `DICOM Server Forms & Views`, `extractor/tests.py`, `DICOM QR Client (Query/Retrieve)`, `Clinical Data Forms`, `DicomFrontendTestCase`, `Celery Tasks & TaskRun`, `Extraction Review & Record Ops`, `classifier.py`, `Data Import Forms`, `DICOM C-STORE Ingest & QR`, `Data Import Model Writers`, `Bulk Patient Study Query`, `DICOM Ingest Service`, `ArchiveLocation`, `Navbar Visibility Tests`, `BulkScheduleForm`, `make_study`, `patient_data.py`, `DateValidationMixin`, `RetrievalBatchPatient`, `resources.py`, `AutoRetrievalTaskTests`, `MigrationBase`, `query.py`, `ArchiveViewTestCase`, `.deidentify`, `django_urls`, `TestNodeCRUD`, `find_patient`, `make_rt_dataset`, `FolderPathMigrationTests`, `LoopbackSCPTests`, `LegacyImportServiceTests`, `qr_client.py`, `RtInstanceSelectionE2ETests`, `PatientAutoRetrievalSignalTests`?**
  _High betweenness centrality (0.134) - this node is a cross-community bridge._
- **Are the 63 inferred relationships involving `Patient` (e.g. with `PatientForm` and `UnifiedClinicalDataResource`) actually correct?**
  _`Patient` has 63 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Card (page)`, `403 (page)`, `FK Relationship Tracking` to the rest of the system?**
  _38 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Extraction Mgmt Commands` be split into smaller, more focused modules?**
  _Cohesion score 0.048130322102924845 - nodes in this community are weakly interconnected._
- **Why does `DICOMStudy` connect `classifier.py` to `ingest.py`, `SiteConfiguration`, `DRF Serializers`, `_upsert_study`, `DICOM QR Client (Query/Retrieve)`, `Clinical Data Forms`, `Celery Tasks & TaskRun`, `Clinical Form Views (CRUD)`, `DICOM C-STORE Ingest & QR`, `Bulk Patient Study Query`, `DICOM Ingest Service`, `ArchiveLocation`, `make_study`, `Patient`, `0035_recover_archived_studies.py`, `AutoRetrievalTaskTests`, `MigrationBase`, `ModelPermissionMixin`, `query.py`, `ArchiveViewTestCase`, `TestPageRendering`, `FolderPathMigrationTests`, `LoopbackSCPTests`, `TestManualTriggers`, `qr_client.py`, `ForeignKeyInitMixin`, `.load`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Are the 51 inferred relationships involving `DICOMStudy` (e.g. with `DiagnosisUpdateView` and `ForeignKeyInitMixin`) actually correct?**
  _`DICOMStudy` has 51 INFERRED edges - model-reasoned connections that need verification._
- **Should `logging` be split into smaller, more focused modules?**
  _Cohesion score 0.04108934543717153 - nodes in this community are weakly interconnected._
# Graph Report - CHAVI-Client  (2026-10-25)

## Corpus Check
- 638 files · ~986,678 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 270 file(s) not represented in the graph (top: .doctree 152, .css 51, (none) 23)

## Summary
- 4953 nodes · 11543 edges · 262 communities (111 shown, 151 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 1292 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `29fe86b8`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Extraction Mgmt Commands
- DatabaseField
- Extractor Forms & Deid Config
- DICOM Study/Series/Instance Models
- InstructorExtractionService
- Bulk Retrieval Scheduling
- SiteConfiguration
- DRF Serializers
- Bulk DICOM Views
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
- views_lookup_embeddings.py
- Data Import Field Introspection
- Extractor Admin
- Django Admin Registrations
- App Configs (ready hooks)
- ArchiveConfiguration
- Admin Export Resources & Settings
- dicom_server/services/schedule_sync.py
- LLM Extraction UI Pages
- Bulk DICOM Selection Logic
- DICOM Server Forms
- DICOM Ingest Service
- DICOM Archive Views
- Navbar Visibility Tests
- StuckBatchRecoveryTests
- TestCase
- DICOM Archive Location Model
- DICOM Instance Selection
- make_study
- test_bulk_retrieval.py
- record_writer.py
- .stage_extract
- deid_meddeid_ab.py
- url_policy.py
- .get
- JSONGeneratorService
- SchemaDiscoveryService
- 0035_recover_archived_studies.py
- Allauth Auth UI
- extractor/tasks.py
- ArchiveConfigurationForm
- read_manifest_entries
- AutoRetrievalTaskTests
- EmbeddingIndexTests
- MigrationBase
- LlmNerClient
- InferenceContractTests
- OpenMedNerRecognizer
- ModelPermissionMixin
- query.py
- step11_review.py
- Data Import Wizard
- ArchiveViewTestCase
- make_field
- BaseImportView
- .deidentify
- build_table_question_prompt
- Notification
- get_study
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
- EmbeddingConfiguration
- BulkScheduleViewTests
- DICOM Archive
- test_qr.py
- deid_span_ab_test.py
- TextDeidentificationService
- ExtractionResult
- .handle
- Project
- text_deidentification.py
- dicom_archive/admin.py
- TestLocationTestView
- ProcessedText
- resolve_spans
- ClientConfigurationDeidValidationTests
- LlmDeidEndToEndTests
- meddeid_pipeline_db_test.py
- DiagnosisImportSerializer
- PatientAutoRetrievalSignalTests
- sync_archive_schedule
- import_filters.py
- TestLocationCrud
- _SourceIndex
- GapFillTests
- dicom_server/signals.py
- DeidPipelineResolutionTests
- chunk_text
- DeidDispatchViewTests
- components
- 0034_fix_dicomstudy_folder_paths.py
- LaboratoryResults
- export_dicom_data
- DateFormatParser
- reset_archive_config
- test_tasks.py
- BackgroundTask
- ChunkedEmbeddingServiceTests
- BaseEmbeddingProvider
- SemanticSearchService
- Django Admin UI
- AccountAdapter
- import_serializers.py
- dicom_archive/signals.py
- Comorbidity
- UUIDEncoder
- Symptom
- DICOM Data Export
- .test_task_fails_fast_when_get_not_negotiated
- TestPermissionGating
- extractor_filters.py
- LookupEmbedding
- Bulk DICOM Import
- DICOMStudyAdmin
- RadiotherapyAdmin
- BulkDICOMStudyMatch
- HashedForeignKeyField
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
- TestComponentExtraClassIsolation
- Lesion
- LesionResponse
- TestLocationTestButtons
- Outcome
- TestPermissionGating
- PatientAssessment
- PatientReportedOutcome
- RadiotherapyDoseVolumeData
- _link_series_references
- SomaticGenomicAlterations
- CHAVI-Client
- PatientDicomFile
- StageInformation
- AppScaffoldTests
- _get_storage_uids
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
- _modalities_str
- DiagnosisAdmin
- PathologyAdmin
- data_import/forms.py
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
10. `TextDeidentificationService` - 53 edges

## Surprising Connections (you probably didn't know these)
- `Extractor App (LLM Extraction)` --conceptually_related_to--> `LLM-Powered Data Extraction`  [INFERRED]
  extractor/PROGRESS.md → templates/extractor/client_configuration_create.html
- `BulkRetrieveForm` --uses--> `Patient`  [INFERRED]
  dicom_server/forms.py → client_app/models.py
- `RetrieveStudiesForm` --uses--> `Patient`  [INFERRED]
  dicom_server/forms.py → client_app/models.py
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

## Communities (262 total, 151 thin omitted)

### Community 0 - "Extraction Mgmt Commands"
Cohesion: 0.04
Nodes (18): ResponseModel, Meta, ResponseModelTable, Meta, ResponseModelTableField, Meta, PydanticModelBuilder, check() (+10 more)

### Community 1 - "DatabaseField"
Cohesion: 0.07
Nodes (11): Command, DatabaseField, Meta, collect_pending_rows(), _lookup_model(), prepare_table(), _source_rows(), _text_fields() (+3 more)

### Community 2 - "Extractor Forms & Deid Config"
Cohesion: 0.03
Nodes (66): ExtractionRecordReviewForm, ReviewApprovalForm, TextDeidentificationPipelineConfigForm, Meta, ClientConfiguration, Meta, ExtractionReviewBatch, Meta (+58 more)

### Community 3 - "DICOM Study/Series/Instance Models"
Cohesion: 0.04
Nodes (37): backfill(), Migration, BulkDICOMUploadSession, Meta, StatusChoices, DICOMInstance, Meta, DICOMSeries (+29 more)

### Community 4 - "InstructorExtractionService"
Cohesion: 0.06
Nodes (8): ExtractionJob, Meta, InstructorExtractionService, run_entry(), skip_descendants(), submit(), advance_extraction_job(), DeidUnshiftOnSaveTests

### Community 5 - "Bulk Retrieval Scheduling"
Cohesion: 0.05
Nodes (35): BulkRetrievalSchedule, Meta, Mode, RetrievalBatchPatient, Meta, QueryStatus, _aggregate_retrieval_batch(), _dispatch_retrieval_chunk() (+27 more)

### Community 6 - "SiteConfiguration"
Cohesion: 0.03
Nodes (30): SiteConfiguration, Meta, AutoRetrievalStateAdmin, DICOMServerConfigurationAdmin, InboundDICOMInstanceAdmin, PatientIDAliasInline, RemoteDICOMNodeAdmin, RetrievalBatchAdmin (+22 more)

### Community 7 - "DRF Serializers"
Cohesion: 0.04
Nodes (66): AdverseEffectsSerializer, Meta, BaseSerializer, Meta, ComorbiditySerializer, Meta, ConcomitantMedicationsSerializer, Meta (+58 more)

### Community 8 - "Bulk DICOM Views"
Cohesion: 0.03
Nodes (28): BulkDICOMCompleteView, BulkDICOMConfirmationView, BulkDICOMMatchingView, BulkDICOMSessionListView, BulkDICOMUploadView, custom_403_view(), DICOMDataExportView, DICOMExportDownloadView (+20 more)

### Community 9 - "extractor/tests.py"
Cohesion: 0.03
Nodes (49): DatabaseTable, Meta, DeidNerEngineChoices, _delete_processed_file(), EntityTypeChoices, ExtractedRecord, Meta, ExtractionBasisChoices (+41 more)

### Community 10 - "DICOM Server Forms & Views"
Cohesion: 0.04
Nodes (38): RemoteDICOMNodeForm, Meta, RetrieveStudiesForm, RetrievalBatch, Meta, Status, _parse_dicom_date(), BatchDetailView (+30 more)

### Community 11 - "FileUpload"
Cohesion: 0.09
Nodes (6): FileUpload, Meta, ProcessingStatusChoices, FileProcessorService, _get_easyocr_reader(), file_upload_delete()

### Community 12 - "DICOM QR Client (Query/Retrieve)"
Cohesion: 0.05
Nodes (4): _backfill_study_fields(), find_studies_with_series(), QRClientTests, _StubPACS

### Community 13 - "Clinical Data Forms"
Cohesion: 0.06
Nodes (60): AdverseEffectsForm, Meta, ComorbidityForm, Meta, ConcomitantMedicationsForm, Meta, CrispyFormMixin, CytogeneticsForm (+52 more)

### Community 14 - "Extraction Review & Record Ops"
Cohesion: 0.08
Nodes (52): RecordOperationChoices, ResultSourceChoices, ReviewChangeChoices, ReviewStatusChoices, _apply_snapshot(), approve_review(), _assert_supported_table(), _assessment_payload() (+44 more)

### Community 15 - "Celery Tasks & TaskRun"
Cohesion: 0.06
Nodes (36): BulkDICOMUpload, Meta, DICOMStudyProject, Meta, TaskRun, Meta, Status, TaskType (+28 more)

### Community 16 - "Clinical List Views"
Cohesion: 0.03
Nodes (30): BaseListView, AdverseEffectsListView, ComorbidityListView, ConcomitantMedicationsListView, CytogeneticsListView, DiagnosisListView, DICOMStudyListView, EpigeneticDataListView (+22 more)

### Community 17 - "classifier.py"
Cohesion: 0.10
Nodes (16): Diagnosis, Meta, StudyTypeChoices, StudyTypeRule, Meta, Operator, ReferenceEvent, StudyTypeSource (+8 more)

### Community 18 - "Clinical Form Views (CRUD)"
Cohesion: 0.04
Nodes (31): AdverseEffectsCreateView, BaseFormView, ComorbidityCreateView, ConcomitantMedicationsCreateView, CytogeneticsCreateView, DiagnosisCreateView, EpigeneticDataCreateView, ForeignKeyInitMixin (+23 more)

### Community 19 - "Data Import Forms"
Cohesion: 0.07
Nodes (9): FileImportSessionStep, FileMappedField, Meta, FilePatientID, Meta, CSVProcessorService, FieldIntrospectionService, ModelHierarchyService (+1 more)

### Community 20 - "DICOM C-STORE Ingest & QR"
Cohesion: 0.04
Nodes (35): RemoteDICOMNode, Meta, _backfill_rt_references(), _collect_subop_stats(), _connect(), echo(), _enrich_series_instances(), _find_instances_on_assoc() (+27 more)

### Community 22 - "Clinical Update Views"
Cohesion: 0.05
Nodes (27): BaseUpdateView, AdverseEffectsUpdateView, ComorbidityUpdateView, ConcomitantMedicationsUpdateView, CytogeneticsUpdateView, EpigeneticDataUpdateView, GeneExpressionDataUpdateView, GermlineGenomicAlterationsUpdateView (+19 more)

### Community 23 - "django_db"
Cohesion: 0.02
Nodes (85): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+77 more)

### Community 24 - "Bulk Patient Study Query"
Cohesion: 0.09
Nodes (3): BulkPatientListTests, BulkViewTests, CandidateIDTests

### Community 25 - "views_lookup_embeddings.py"
Cohesion: 0.15
Nodes (8): compute_embeddings(), embedding_config_activate(), embedding_config_create(), embedding_config_delete(), embedding_config_edit(), get_embedding_progress(), _inflight_embedding_tasks_alive(), lookup_embeddings()

### Community 26 - "Data Import Field Introspection"
Cohesion: 0.06
Nodes (7): Step2PatientIDMappingForm, Step10MissingRelationsView, Step4FieldMappingView, Step5ColumnValueMappingView, Step6DateFormatView, Step8LookupMappingView, Step9DefaultValuesView

### Community 27 - "Extractor Admin"
Cohesion: 0.07
Nodes (21): ClientConfigurationAdmin, DatabaseFieldAdmin, DatabaseFieldInline, DatabaseTableAdmin, EmbeddingConfigurationAdmin, ExtractionJobAdmin, ExtractionResultAdmin, ExtractionResultInline (+13 more)

### Community 28 - "Django Admin Registrations"
Cohesion: 0.10
Nodes (36): AdverseEffectsAdmin, BulkDICOMUploadAdmin, ComorbidityAdmin, ConcomitantMedicationsAdmin, CytogeneticsAdmin, DICOMStudyProjectAdmin, EpigeneticDataAdmin, GeneExpressionDataAdmin (+28 more)

### Community 29 - "App Configs (ready hooks)"
Cohesion: 0.05
Nodes (9): ClientAppConfig, DataImportConfig, FileColumnFieldValueMapping, Meta, FileImportUUIDValues, Meta, UUIDManager, DicomArchiveConfig (+1 more)

### Community 30 - "ArchiveConfiguration"
Cohesion: 0.10
Nodes (6): ArchiveConfiguration, Meta, ArchiveConfigurationTests, TaskTypeAdditionsTests, ArchiveConfigUpdateView, ArchiveDashboardView

### Community 31 - "Admin Export Resources & Settings"
Cohesion: 0.05
Nodes (29): AdverseEffectsExportResource, Meta, CytogeneticsInline, DiagnosisExportResource, Meta, DICOMStudyProjectInline, EpigeneticDataInline, GeneExpressionDataInline (+21 more)

### Community 32 - "dicom_server/services/schedule_sync.py"
Cohesion: 0.20
Nodes (5): Command, _periodic_task_name(), sync_all_node_schedules(), sync_node_schedule(), ScheduleSyncTests

### Community 33 - "LLM Extraction UI Pages"
Cohesion: 0.09
Nodes (42): Extraction Wizard Flow, LLM-Powered Data Extraction, Base (page), Form Template (page), Homepage (page), Model List (page), Client Configuration Create (page), Client Configuration Detail (page) (+34 more)

### Community 34 - "Bulk DICOM Selection Logic"
Cohesion: 0.12
Nodes (19): ancestors_of(), _approval_visible(), build_selections_for_patient(), _dcm_date_to_iso(), descendants_of(), _plan_approval_state(), _rt_labels(), select_study() (+11 more)

### Community 35 - "DICOM Server Forms"
Cohesion: 0.08
Nodes (8): BulkScheduleForm, Meta, apply_transforms(), parse_transform_lines(), transforms_to_lines(), validate_transforms(), TransformTests, BulkScheduleFormTests

### Community 36 - "DICOM Ingest Service"
Cohesion: 0.13
Nodes (7): ingest_dataset(), reject(), IngestResult, _selection_reject_reason(), _upsert_study(), IngestDatasetTests, make_test_dataset()

### Community 37 - "DICOM Archive Views"
Cohesion: 0.06
Nodes (12): ArchivedStudyListView, ArchiveLocationCreateView, ArchiveLocationDeleteView, ArchiveLocationListView, ArchiveLocationUpdateView, ArchivePermissionRequiredMixin, _json_payload(), LocalStudyBrowserView (+4 more)

### Community 38 - "Navbar Visibility Tests"
Cohesion: 0.08
Nodes (4): NavbarVisibilityTests, PatientSummaryPermissionTests, PermissionGatingTests, RoleGroupTests

### Community 39 - "StuckBatchRecoveryTests"
Cohesion: 0.24
Nodes (3): _ensure_site(), RetrievalSkipDoneTests, StuckBatchRecoveryTests

### Community 40 - "TestCase"
Cohesion: 0.12
Nodes (4): ChunkModelTests, ClientConfigurationDeidViewTests, ClientConfigurationSystem1CapabilityTests, MergeTests

### Community 41 - "DICOM Archive Location Model"
Cohesion: 0.08
Nodes (13): ArchiveLocationForm, Meta, ArchiveLocation, Meta, StorageType, prepare_location(), resolve_location_path(), test_location() (+5 more)

### Community 42 - "DICOM Instance Selection"
Cohesion: 0.11
Nodes (9): instance_ancestors(), normalize_selection(), SelectionError, _series_by_uid(), _sop_index(), sop_series_uid(), InstanceAncestorsTests, NormalizeSelectionTests (+1 more)

### Community 43 - "make_study"
Cohesion: 0.05
Nodes (19): archive_study(), ArchiveError, _sanitize_segment(), _study_stats(), dearchival_required_for_studies(), dearchive_studies(), dearchive_study(), ensure_studies_local() (+11 more)

### Community 44 - "test_bulk_retrieval.py"
Cohesion: 0.08
Nodes (14): BulkRetrieveForm, DICOMServerConfigForm, Meta, _finish_task_run_quiet(), task_finalize_batch_query(), task_finalize_retrieval_batch(), task_query_patient_studies(), _finish() (+6 more)

### Community 45 - "record_writer.py"
Cohesion: 0.09
Nodes (15): RecordCreation, Meta, RecordCreationField, Meta, _coerce(), _effective_map(), find_duplicate_candidates(), field_value() (+7 more)

### Community 46 - ".stage_extract"
Cohesion: 0.10
Nodes (7): create(), TableExtractParallelTests, create(), create(), create(), TableExtractTests, create()

### Community 47 - "deid_meddeid_ab.py"
Cohesion: 0.18
Nodes (8): parse_tagged(), iou(), llm_chat(), main(), run_match(), run_tag(), score_span_f1(), _normalize_entity_type()

### Community 48 - "url_policy.py"
Cohesion: 0.18
Nodes (4): is_cloud_provider(), is_local_endpoint(), normalize_base_url(), validate_base_url()

### Community 52 - "0035_recover_archived_studies.py"
Cohesion: 0.15
Nodes (13): _check_patient_ids(), _delete_study_rows(), _dicom_date(), _expected_folder_path(), Migration, _parse_dt(), _parse_manifest(), recover_archived_studies() (+5 more)

### Community 53 - "Allauth Auth UI"
Cohesion: 0.08
Nodes (26): Allauth Auth UI, Alert (page), Badge (page), Button (page), Button Group (page), Details (page), Field (page), Fields (page) (+18 more)

### Community 54 - "extractor/tasks.py"
Cohesion: 0.11
Nodes (9): _CudaSmokeTestFailed, EmbeddingUnavailableError, _advance_to_next_table_or_finalize(), compute_lookup_embeddings_task(), embed_lookup_table_chunk(), finalize_lookup_embeddings_task(), ocr_processed_text_task(), _record_table_result() (+1 more)

### Community 55 - "ArchiveConfigurationForm"
Cohesion: 0.36
Nodes (3): ArchiveConfigurationForm, Meta, TestArchiveConfigurationForm

### Community 57 - "AutoRetrievalTaskTests"
Cohesion: 0.10
Nodes (10): _cache_old_consent(), _trigger_auto_retrieval(), AutoRetrievalState, Meta, _auto_retrieve_patient_node(), task_auto_retrieve_node(), task_auto_retrieve_patient(), task_auto_retrieve_patient_batch() (+2 more)

### Community 59 - "MigrationBase"
Cohesion: 0.16
Nodes (4): ArchiveRecoveryTests, make_dcm(), MigrationBase, VerifyLocalStudiesTests

### Community 61 - "InferenceContractTests"
Cohesion: 0.13
Nodes (4): describe(), clean_records(), InferenceContractTests, create()

### Community 62 - "OpenMedNerRecognizer"
Cohesion: 0.18
Nodes (3): OpenMedNerError, OpenMedNerRecognizer, OpenMedNerRecognizerTests

### Community 63 - "ModelPermissionMixin"
Cohesion: 0.11
Nodes (3): DiagnosisUpdateView, ModelPermissionMixin, PatientUpdateView

### Community 64 - "query.py"
Cohesion: 0.19
Nodes (6): _fill(), iter_find_responses(), match_date(), match_value(), _patient_matches(), _wildcard_regex()

### Community 65 - "step11_review.py"
Cohesion: 0.08
Nodes (12): Step10ReviewForm, FieldLookupValues, Meta, FileDateFieldMapping, Meta, FileDefaultValues, Meta, FileMissingRelations (+4 more)

### Community 66 - "Data Import Wizard"
Cohesion: 0.17
Nodes (17): Step 10 Missing FK Relationships, CSV Data Import Workflow, Data Import Wizard, Base Import (page), Session List (page), Step10 Missing Relations (page), Step11 Review (page), Step12 Complete (page) (+9 more)

### Community 68 - "make_field"
Cohesion: 0.18
Nodes (4): ExtractionPlanTests, make_field(), make_response_model(), make_table()

### Community 69 - "BaseImportView"
Cohesion: 0.08
Nodes (6): Step1UploadCSVForm, Meta, FileImportSession, Meta, BaseImportView, Step1UploadCSVView

### Community 70 - ".deidentify"
Cohesion: 0.11
Nodes (3): _FakeAnalyzer, TextDeidPipelineTests, processed_text_deid_review()

### Community 71 - "build_table_question_prompt"
Cohesion: 0.22
Nodes (4): build_table_question_prompt(), _lookup_choices_line(), table_docstring(), TablePromptTests

### Community 72 - "Notification"
Cohesion: 0.09
Nodes (7): Notification, Meta, NotificationType, AutoContinueTaskTests, FlashMessageRenderingTests, ModelDocstringTests, TaskRunResumeRetryViewTests

### Community 74 - "llm_ner.py"
Cohesion: 0.18
Nodes (4): LlmNerError, LlmNerParseError, _parse_entity_output(), LlmNerParseTests

### Community 76 - "StagedPipelineTests"
Cohesion: 0.13
Nodes (5): FieldSnippetEntry, LookupSnippetMap, StagedPipelineTests, create(), StagePlanningTests

### Community 78 - "FileImportJSON"
Cohesion: 0.13
Nodes (6): PatientImportSerializer, Meta, FileImportJSON, Meta, ImportExecutorService, Step12ExecuteImportView

### Community 81 - "find_patient"
Cohesion: 0.17
Nodes (3): find_patient(), FindPatientTests, SanitizeTests

### Community 82 - "make_rt_dataset"
Cohesion: 0.21
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

### Community 90 - "SimpleTestCase"
Cohesion: 0.14
Nodes (3): AgeDurationRegressionTests, ClinicalAllowlistTests, FilterDecompositionTests

### Community 91 - "LegacyImportServiceTests"
Cohesion: 0.12
Nodes (5): _encrypt_value(), LegacyImportServiceTests, LegacyImportTaskTests, _make_legacy_db(), TaskProgressResumeBarTests

### Community 93 - "EmbeddingConfiguration"
Cohesion: 0.12
Nodes (9): ExtractorConfig, _warm_embedding_provider(), Command, EmbeddingConfiguration, Meta, compute_lookup_embeddings(), compute_lookup_table_embeddings(), finalize_lookup_index() (+1 more)

### Community 95 - "DICOM Archive"
Cohesion: 0.18
Nodes (11): Archive Operator Role, Archive Viewer Role, DICOM Administrator Role, DICOM Archive Permissions, DICOM Archive, Archived List (page), Browse (page), Config Edit (page) (+3 more)

### Community 96 - "test_qr.py"
Cohesion: 0.07
Nodes (12): DICOMServerConfiguration, Meta, _db_cleanup(), handle_echo(), handle_find(), handle_store(), build_ae(), run_server() (+4 more)

### Community 97 - "deid_span_ab_test.py"
Cohesion: 0.16
Nodes (6): Command, llm_chat(), _norm_span(), run_match(), run_tag(), score_entities_pairs()

### Community 98 - "TextDeidentificationService"
Cohesion: 0.11
Nodes (4): _resolve_device(), _shifted_date_text(), TextDeidentificationService, DeidReplacementTests

### Community 99 - "ExtractionResult"
Cohesion: 0.15
Nodes (6): DataAccuracyChoices, ExtractionResult, Meta, classify_review(), InferenceReviewContractTests, ReviewValueTests

### Community 100 - ".handle"
Cohesion: 0.15
Nodes (5): Command, match_records(), overlap(), norm_value(), score_records()

### Community 101 - "Project"
Cohesion: 0.15
Nodes (5): Project, Meta, associate_dicom_files_to_project(), ProjectSelectionForm, Media

### Community 102 - "text_deidentification.py"
Cohesion: 0.12
Nodes (6): build_text_recognizers(), _load_gazetteer(), default_hf_label_map(), default_rules(), _FakeResult, _normalize_tag_key()

### Community 103 - "dicom_archive/admin.py"
Cohesion: 0.29
Nodes (3): ArchiveConfigurationAdmin, ArchivedStudyAdmin, ArchiveLocationAdmin

### Community 105 - "ProcessedText"
Cohesion: 0.13
Nodes (5): Command, ProcessedText, Meta, deidentify_processed_text_task(), FileUploadDetailDeidRenderTests

### Community 109 - "meddeid_pipeline_db_test.py"
Cohesion: 0.22
Nodes (9): load_notes(), load_pipelines(), main(), match_ratio(), pipeline_info(), _pkg(), run_doc_production(), run_pipeline() (+1 more)

### Community 110 - "DiagnosisImportSerializer"
Cohesion: 0.22
Nodes (4): DiagnosisImportSerializer, Meta, PathologyImportSerializer, Meta

### Community 112 - "sync_archive_schedule"
Cohesion: 0.21
Nodes (3): sync_archive_schedule(), ArchiveConfigurationSignalTests, SyncArchiveScheduleTests

### Community 113 - "import_filters.py"
Cohesion: 0.28
Nodes (3): get_item(), get_nested_item(), index()

### Community 117 - "dicom_server/signals.py"
Cohesion: 0.23
Nodes (8): _dispatch_one_off(), _ensure_periodic(), revoke_one_off(), sync_bulk_schedule(), _disable_bulk_schedule_on_delete(), _disable_node_schedule_on_delete(), _sync_bulk_schedule_on_save(), _sync_node_schedule_on_save()

### Community 121 - "components"
Cohesion: 0.25
Nodes (7): components, button, card, custom_form, legacy_card, pagination, table

### Community 122 - "0034_fix_dicomstudy_folder_paths.py"
Cohesion: 0.38
Nodes (4): _expected_folder_path(), fix_dicomstudy_folder_paths(), Migration, _sanitize()

### Community 126 - "reset_archive_config"
Cohesion: 0.24
Nodes (4): candidate_studies(), task_scheduled_archive(), ScheduledArchiveTaskTests, reset_archive_config()

### Community 127 - "test_tasks.py"
Cohesion: 0.47
Nodes (3): ArchiveStudiesTaskTests, DearchiveStudiesTaskTests, TaskTestBase

### Community 128 - "BackgroundTask"
Cohesion: 0.15
Nodes (3): BackgroundTask, Meta, EmbeddingDispatcherTests

### Community 129 - "ChunkedEmbeddingServiceTests"
Cohesion: 0.21
Nodes (3): embed_one_chunk(), ChunkedEmbeddingServiceTests, embed()

### Community 130 - "BaseEmbeddingProvider"
Cohesion: 0.19
Nodes (4): BaseEmbeddingProvider, build_provider(), OpenAICompatibleProvider, SentenceTransformerProvider

### Community 132 - "Django Admin UI"
Cohesion: 0.33
Nodes (5): Django Admin UI, Card (page), Change Form (page), Change List (page), Index (page)

### Community 135 - "dicom_archive/signals.py"
Cohesion: 0.22
Nodes (3): cleanup_study_files(), study_deleted_receiver(), _sync_archive_schedule_on_save()

### Community 139 - "DICOM Data Export"
Cohesion: 0.33
Nodes (5): Associate DICOM to Project (admin action), DICOM Data Export, Dicom Data Export (page), Dicom Export Progress (page), Dicomstudy List (page)

### Community 143 - "LookupEmbedding"
Cohesion: 0.25
Nodes (3): Command, LookupEmbedding, Meta

### Community 144 - "Bulk DICOM Import"
Cohesion: 0.33
Nodes (6): Bulk DICOM Import, Bulk Dicom Complete (page), Bulk Dicom Confirmation (page), Bulk Dicom Matching (page), Bulk Dicom Session List (page), Bulk Dicom Upload (page)

### Community 147 - "BulkDICOMStudyMatch"
Cohesion: 0.40
Nodes (3): BulkDICOMStudyMatch, MatchStatus, Meta

### Community 152 - "De-identification"
Cohesion: 0.40
Nodes (5): De-identification, Legacy Import (page), Legacy Import Results (page), Patient Detail (page), Patient List (page)

### Community 182 - "DateValidationMixin"
Cohesion: 0.06
Nodes (15): AdverseEffects, Meta, ConcomitantMedications, Meta, DateValidationMixin, OtherTreatment, Meta, Radiotherapy (+7 more)

### Community 185 - "resources.py"
Cohesion: 0.05
Nodes (17): EpigeneticData, Meta, GeneExpressionData, Meta, Immunohistochemistry, Meta, ModalityChoices, Pathology (+9 more)

### Community 204 - "Base Layout & Auth"
Cohesion: 0.50
Nodes (3): Base Layout & Auth, 403 (page), Login (page)

### Community 205 - "Patient Management"
Cohesion: 0.50
Nodes (4): Patient Management, Patient Data Export (page), Patient Search (page), Patient Summary New (page)

### Community 206 - "Task Management"
Cohesion: 0.50
Nodes (4): Task Management, Task Progress (page), Taskrun Detail (page), Taskrun List (page)

### Community 250 - "data_import/forms.py"
Cohesion: 0.10
Nodes (14): Step4FieldMappingForm, Step5ColumnValueMappingForm, Step6DateFormatForm, Step7DurationDateForm, Step8LookupMappingForm, Step9MissingRelationsForm, DateFormat, DurationUnits (+6 more)

## Knowledge Gaps
- **38 isolated node(s):** `Card (page)`, `403 (page)`, `FK Relationship Tracking`, `Schema Discovery Service`, `UI Styleguide` (+33 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 2110 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **151 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Patient` connect `DICOM Study/Series/Instance Models` to `Extractor Forms & Deid Config`, `InstructorExtractionService`, `Bulk Retrieval Scheduling`, `SiteConfiguration`, `DRF Serializers`, `extractor/tests.py`, `DICOM Server Forms & Views`, `DICOM QR Client (Query/Retrieve)`, `Clinical Data Forms`, `Extraction Review & Record Ops`, `Celery Tasks & TaskRun`, `classifier.py`, `Data Import Forms`, `DICOM C-STORE Ingest & QR`, `Data Import Model Writers`, `DICOM Server Forms`, `DICOM Ingest Service`, `Navbar Visibility Tests`, `StuckBatchRecoveryTests`, `make_study`, `test_bulk_retrieval.py`, `record_writer.py`, `DateValidationMixin`, `resources.py`, `AutoRetrievalTaskTests`, `MigrationBase`, `query.py`, `ArchiveViewTestCase`, `.deidentify`, `TestNodeCRUD`, `find_patient`, `make_rt_dataset`, `FolderPathMigrationTests`, `LoopbackSCPTests`, `LegacyImportServiceTests`, `test_qr.py`, `PatientAutoRetrievalSignalTests`?**
  _High betweenness centrality (0.138) - this node is a cross-community bridge._
- **Are the 63 inferred relationships involving `Patient` (e.g. with `PatientForm` and `UnifiedClinicalDataResource`) actually correct?**
  _`Patient` has 63 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Card (page)`, `403 (page)`, `FK Relationship Tracking` to the rest of the system?**
  _38 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Extraction Mgmt Commands` be split into smaller, more focused modules?**
  _Cohesion score 0.0444635685599541 - nodes in this community are weakly interconnected._
- **Why does `UnifiedClinicalDataResource` connect `Data Import Model Writers` to `Outcome`, `PatientAssessment`, `DICOM Study/Series/Instance Models`, `PatientReportedOutcome`, `SomaticGenomicAlterations`, `Comorbidity`, `StageInformation`, `Symptom`, `LaboratoryResults`, `classifier.py`, `DateValidationMixin`, `Cytogenetics`, `resources.py`, `GermlineGenomicAlterations`, `Django Admin Registrations`, `Lesion`, `LesionResponse`, `Admin Export Resources & Settings`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Are the 51 inferred relationships involving `DICOMStudy` (e.g. with `DiagnosisUpdateView` and `ForeignKeyInitMixin`) actually correct?**
  _`DICOMStudy` has 51 INFERRED edges - model-reasoned connections that need verification._
- **Should `DatabaseField` be split into smaller, more focused modules?**
  _Cohesion score 0.06852497096399536 - nodes in this community are weakly interconnected._
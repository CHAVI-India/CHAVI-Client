# Graph Report - CHAVI-Client  (2026-10-25)

## Corpus Check
- 407 files · ~288,050 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4935 nodes · 11499 edges · 292 communities (102 shown, 190 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 1292 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Extraction Mgmt Commands
- Extractor Config & Django Core
- Extractor Forms & Deid Config
- DICOM Study/Series/Instance Models
- Instructor Extraction Service
- Bulk Retrieval Scheduling
- Patient & Site Models
- DRF Serializers
- Bulk DICOM Views
- Extraction Result Models
- DICOM Server Forms & Views
- Deid Backfill Command
- DICOM QR Client (Query/Retrieve)
- Clinical Data Forms
- Extraction Review & Record Ops
- Celery Tasks & TaskRun
- Clinical List Views
- Bulk DICOM Upload Models
- Clinical Form Views (CRUD)
- Data Import Forms
- DICOM C-STORE Ingest & QR
- Data Import Model Writers
- Clinical Update Views
- client_app Migrations
- Bulk Patient Study Query
- Background Task Tracking
- Data Import Field Introspection
- Extractor Admin
- Django Admin Registrations
- App Configs (ready hooks)
- DICOM Archive Configuration
- Admin Export Resources & Settings
- DICOM Auto-Retrieval Signals
- LLM Extraction UI Pages
- Bulk DICOM Selection Logic
- DICOM Server Forms
- DICOM Ingest Service
- DICOM Archive Views
- Navbar Visibility Tests
- Task Resume & Retrieval Tests
- Extraction Nesting & Deid Tests
- DICOM Archive Location Model
- DICOM Instance Selection
- DICOM Archive Service
- DICOM Server Admin
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 101
- Community 102
- Community 103
- Community 104
- Community 105
- Community 106
- Community 107
- Community 108
- Community 109
- Community 110
- Community 111
- Community 112
- Community 113
- Community 114
- Community 115
- Community 116
- Community 117
- Community 118
- Community 119
- Community 120
- Community 121
- Community 122
- Community 123
- Community 124
- Community 125
- Community 127
- Community 129
- Community 130
- Community 131
- Community 132
- Community 133
- Community 134
- Community 135
- Community 136
- Community 137
- Community 138
- Community 139
- Community 140
- Community 141
- Community 142
- Community 143
- Community 144
- Community 145
- Community 146
- Community 147
- Community 148
- Community 149
- Community 150
- Community 151
- Community 152
- Community 153
- Community 154
- Community 155
- Community 156
- Community 157
- Community 158
- Community 159
- Community 160
- Community 161
- Community 162
- Community 163
- Community 164
- Community 165
- Community 166
- Community 167
- Community 168
- Community 169
- Community 170
- Community 171
- Community 172
- Community 173
- Community 174
- Community 175
- Community 176
- Community 177
- Community 178
- Community 179
- Community 180
- Community 181
- Community 182
- Community 183
- Community 184
- Community 185
- Community 186
- Community 187
- Community 188
- Community 189
- Community 190
- Community 191
- Community 192
- Community 193
- Community 194
- Community 195
- Community 196
- Community 197
- Community 198
- Community 199
- Community 200
- Community 201
- Community 202
- Community 203
- Community 204
- Community 205
- Community 206
- Community 207
- Community 208
- Community 209
- Community 210
- Community 211
- Community 212
- Community 213
- Community 214
- Community 215
- Community 216
- Community 217
- Community 218
- Community 219
- Community 220
- Community 221
- Community 222
- Community 223
- Community 224
- Community 225
- Community 226
- Community 227
- Community 228
- Community 229
- Community 230
- Community 243
- Community 244
- Community 245
- Community 246
- Community 247
- Community 248
- Community 250
- Community 251
- Community 252
- Community 253
- Community 254
- Community 264
- Community 265
- Community 266
- Community 267
- Community 268
- Community 269
- Community 270
- Community 271
- Community 284
- Community 285
- Community 289
- Community 290

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
- `ArchiveViewTestCase` --uses--> `SiteConfiguration`  [INFERRED]
  dicom_archive/tests/test_views.py → client_app/models.py
- `make_study()` --uses--> `SiteConfiguration`  [INFERRED]
  dicom_archive/tests/utils.py → client_app/models.py
- `AutoRetrievalTaskTests` --uses--> `SiteConfiguration`  [INFERRED]
  dicom_server/tests/test_auto_retrieval.py → client_app/models.py
- `ModelSetupMixin` --uses--> `SiteConfiguration`  [INFERRED]
  dicom_server/tests/test_bulk_schedule.py → client_app/models.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Data Import Wizard 12-Step Flow** — feature_data_import_wizard, data_import_workflow_csvimport, data_import_workflow_hierarchyconstraint, data_import_step10_missingfk [INFERRED 0.80]
- **LLM Extraction Pipeline** — feature_llm_extraction, extractor_progress_schemadiscoveryservice, extractor_progress_pydanticbuilder, extractor_progress_stage2_extraction [INFERRED 0.80]
- **DICOM Archive Access Control** — feature_dicom_archive, dicom_archive_permissions_modelperms, dicom_archive_permissions_dicomadminrole, dicom_archive_permissions_archiveoperator [INFERRED 0.80]

## Communities (292 total, 190 thin omitted)

### Community 0 - "Extraction Mgmt Commands"
Cohesion: 0.03
Nodes (40): Command, match_records(), overlap(), norm_value(), score_records(), DatabaseTable, Meta, EntityTypeChoices (+32 more)

### Community 1 - "Extractor Config & Django Core"
Cohesion: 0.03
Nodes (38): ExtractorConfig, _warm_embedding_provider(), Command, Command, Command, DatabaseField, Meta, DeidNerEngineChoices (+30 more)

### Community 2 - "Extractor Forms & Deid Config"
Cohesion: 0.03
Nodes (65): ExtractionRecordReviewForm, ReviewApprovalForm, TextDeidentificationPipelineConfigForm, Meta, ClientConfiguration, Meta, DataAccuracyChoices, ExtractionReviewBatch (+57 more)

### Community 3 - "DICOM Study/Series/Instance Models"
Cohesion: 0.04
Nodes (34): DICOMInstance, Meta, DICOMSeries, Meta, DICOMStudy, Meta, UnprocessedDICOMStudies, Meta (+26 more)

### Community 4 - "Instructor Extraction Service"
Cohesion: 0.03
Nodes (14): ExtractionJob, Meta, FieldSnippetEntry, InstructorExtractionService, walk(), run_entry(), skip_descendants(), submit() (+6 more)

### Community 5 - "Bulk Retrieval Scheduling"
Cohesion: 0.04
Nodes (44): BulkRetrievalSchedule, Meta, Mode, RetrievalBatch, Meta, Status, RetrievalBatchPatient, Meta (+36 more)

### Community 6 - "Patient & Site Models"
Cohesion: 0.04
Nodes (30): Patient, Gender, Meta, SiteConfiguration, Meta, DICOMServerConfigForm, Meta, DICOMServerConfiguration (+22 more)

### Community 7 - "DRF Serializers"
Cohesion: 0.05
Nodes (66): AdverseEffectsSerializer, Meta, BaseSerializer, Meta, ComorbiditySerializer, Meta, ConcomitantMedicationsSerializer, Meta (+58 more)

### Community 8 - "Bulk DICOM Views"
Cohesion: 0.03
Nodes (28): BulkDICOMCompleteView, BulkDICOMConfirmationView, BulkDICOMMatchingView, BulkDICOMSessionListView, BulkDICOMUploadView, custom_403_view(), DICOMDataExportView, DICOMExportDownloadView (+20 more)

### Community 9 - "Extraction Result Models"
Cohesion: 0.04
Nodes (45): ExtractedRecord, Meta, ExtractionResult, Meta, RecordCreation, Meta, null_fields_for(), build_job_data_tree() (+37 more)

### Community 10 - "DICOM Server Forms & Views"
Cohesion: 0.04
Nodes (35): BulkRetrieveForm, RetrieveStudiesForm, FormTests, BatchDetailView, BatchListView, BatchQueryView, BatchRetrieveView, BatchSelectView (+27 more)

### Community 11 - "Deid Backfill Command"
Cohesion: 0.04
Nodes (14): Command, FileUpload, Meta, ProcessedText, Meta, ProcessingStatusChoices, FileProcessorService, _get_easyocr_reader() (+6 more)

### Community 12 - "DICOM QR Client (Query/Retrieve)"
Cohesion: 0.05
Nodes (6): get_series(), get_study(), move_study(), probe_qr_capabilities(), QRClientTests, _StubPACS

### Community 13 - "Clinical Data Forms"
Cohesion: 0.05
Nodes (62): AdverseEffectsForm, Meta, ComorbidityForm, Meta, ConcomitantMedicationsForm, Meta, CrispyFormMixin, CytogeneticsForm (+54 more)

### Community 14 - "Extraction Review & Record Ops"
Cohesion: 0.07
Nodes (52): RecordOperationChoices, ResultSourceChoices, ReviewChangeChoices, ReviewStatusChoices, _apply_snapshot(), approve_review(), _assert_supported_table(), _assessment_payload() (+44 more)

### Community 15 - "Celery Tasks & TaskRun"
Cohesion: 0.07
Nodes (32): BulkDICOMUpload, Meta, TaskRun, Meta, Status, TaskType, process_study_files(), cleanup_manifest() (+24 more)

### Community 16 - "Clinical List Views"
Cohesion: 0.04
Nodes (24): BaseListView, AdverseEffectsListView, ComorbidityListView, ConcomitantMedicationsListView, CytogeneticsListView, DICOMStudyListView, GeneExpressionDataListView, GermlineGenomicAlterationsListView (+16 more)

### Community 17 - "Bulk DICOM Upload Models"
Cohesion: 0.05
Nodes (32): BulkDICOMUploadSession, Meta, StatusChoices, DateValidationMixin, Diagnosis, Meta, ModalityChoices, Project (+24 more)

### Community 18 - "Clinical Form Views (CRUD)"
Cohesion: 0.04
Nodes (30): AdverseEffectsCreateView, BaseFormView, ComorbidityCreateView, ConcomitantMedicationsCreateView, CytogeneticsCreateView, DiagnosisCreateView, EpigeneticDataCreateView, GeneExpressionDataCreateView (+22 more)

### Community 19 - "Data Import Forms"
Cohesion: 0.10
Nodes (16): Step7DurationDateForm, DateFormat, DurationUnits, FileImportSessionStep, FileMappedField, Meta, FileMappedModel, Meta (+8 more)

### Community 20 - "DICOM C-STORE Ingest & QR"
Cohesion: 0.05
Nodes (29): handle_store(), _backfill_rt_references(), _backfill_study_fields(), _collect_subop_stats(), _connect(), _enrich_series_instances(), _find_instances_on_assoc(), find_series() (+21 more)

### Community 22 - "Clinical Update Views"
Cohesion: 0.05
Nodes (27): BaseUpdateView, AdverseEffectsUpdateView, ComorbidityUpdateView, ConcomitantMedicationsUpdateView, CytogeneticsUpdateView, EpigeneticDataUpdateView, GeneExpressionDataUpdateView, GermlineGenomicAlterationsUpdateView (+19 more)

### Community 23 - "client_app Migrations"
Cohesion: 0.03
Nodes (30): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+22 more)

### Community 24 - "Bulk Patient Study Query"
Cohesion: 0.07
Nodes (6): task_query_patient_studies(), _finish(), BulkPatientListTests, BulkViewTests, CandidateIDTests, QueryTaskTests

### Community 25 - "Background Task Tracking"
Cohesion: 0.06
Nodes (17): BackgroundTask, Meta, _advance_to_next_table_or_finalize(), compute_lookup_embeddings_task(), embed_lookup_table_chunk(), finalize_lookup_embeddings_task(), _record_table_result(), ChunkedEmbeddingTaskTests (+9 more)

### Community 26 - "Data Import Field Introspection"
Cohesion: 0.08
Nodes (3): Step10MissingRelationsView, Step12ExecuteImportView, Step9DefaultValuesView

### Community 27 - "Extractor Admin"
Cohesion: 0.06
Nodes (23): ClientConfigurationAdmin, DatabaseFieldAdmin, DatabaseFieldInline, DatabaseTableAdmin, EmbeddingConfigurationAdmin, ExtractionJobAdmin, ExtractionResultAdmin, ExtractionResultInline (+15 more)

### Community 28 - "Django Admin Registrations"
Cohesion: 0.10
Nodes (38): AdverseEffectsAdmin, BulkDICOMUploadAdmin, ComorbidityAdmin, ConcomitantMedicationsAdmin, CytogeneticsAdmin, DiagnosisAdmin, DICOMStudyProjectAdmin, EpigeneticDataAdmin (+30 more)

### Community 29 - "App Configs (ready hooks)"
Cohesion: 0.05
Nodes (11): ClientAppConfig, DataImportConfig, FileDateFieldMapping, Meta, FileDefaultValues, Meta, FileImportUUIDValues, Meta (+3 more)

### Community 30 - "DICOM Archive Configuration"
Cohesion: 0.07
Nodes (11): ArchiveConfiguration, Meta, sync_archive_schedule(), task_scheduled_archive(), ArchiveConfigurationTests, TaskTypeAdditionsTests, ArchiveConfigurationSignalTests, SyncArchiveScheduleTests (+3 more)

### Community 31 - "Admin Export Resources & Settings"
Cohesion: 0.05
Nodes (29): AdverseEffectsExportResource, Meta, CytogeneticsInline, DiagnosisExportResource, Meta, DICOMStudyProjectInline, EpigeneticDataInline, GeneExpressionDataInline (+21 more)

### Community 32 - "DICOM Auto-Retrieval Signals"
Cohesion: 0.08
Nodes (17): _cache_old_consent(), _trigger_auto_retrieval(), Command, RemoteDICOMNode, Meta, _dispatch_one_off(), _ensure_periodic(), revoke_one_off() (+9 more)

### Community 33 - "LLM Extraction UI Pages"
Cohesion: 0.09
Nodes (42): Extraction Wizard Flow, LLM-Powered Data Extraction, Base (page), Form Template (page), Homepage (page), Model List (page), Client Configuration Create (page), Client Configuration Detail (page) (+34 more)

### Community 34 - "Bulk DICOM Selection Logic"
Cohesion: 0.12
Nodes (19): ancestors_of(), _approval_visible(), build_selections_for_patient(), _dcm_date_to_iso(), descendants_of(), _plan_approval_state(), _rt_labels(), select_study() (+11 more)

### Community 35 - "DICOM Server Forms"
Cohesion: 0.08
Nodes (10): BulkScheduleForm, Meta, RemoteDICOMNodeForm, Meta, apply_transforms(), parse_transform_lines(), transforms_to_lines(), validate_transforms() (+2 more)

### Community 36 - "DICOM Ingest Service"
Cohesion: 0.09
Nodes (9): ingest_dataset(), reject(), IngestResult, sanitize(), _selection_reject_reason(), _upsert_study(), _StubRemotePACS, IngestDatasetTests (+1 more)

### Community 37 - "DICOM Archive Views"
Cohesion: 0.06
Nodes (11): ArchivedStudyListView, ArchiveLocationCreateView, ArchiveLocationDeleteView, ArchiveLocationListView, ArchivePermissionRequiredMixin, _json_payload(), LocalStudyBrowserView, LocationTestView (+3 more)

### Community 38 - "Navbar Visibility Tests"
Cohesion: 0.08
Nodes (4): NavbarVisibilityTests, PatientSummaryPermissionTests, PermissionGatingTests, RoleGroupTests

### Community 39 - "Task Resume & Retrieval Tests"
Cohesion: 0.07
Nodes (12): _ensure_site(), RetrievalSkipDoneTests, StuckBatchRecoveryTests, RetrievalJobSeries, Meta, find_studies_for_patient(), _mark_item_done(), _mark_item_failed() (+4 more)

### Community 40 - "Extraction Nesting & Deid Tests"
Cohesion: 0.07
Nodes (8): nest_children(), rescue_single_parent(), ClientConfigurationDeidViewTests, ClientConfigurationSystem1CapabilityTests, DeidPipelineResolutionTests, FileUploadDetailDeidRenderTests, MergeTests, StagePlanningTests

### Community 41 - "DICOM Archive Location Model"
Cohesion: 0.10
Nodes (9): ArchiveLocation, Meta, StorageType, prepare_location(), resolve_location_path(), test_location(), PrepareLocationTests, ResolveLocationPathTests (+1 more)

### Community 42 - "DICOM Instance Selection"
Cohesion: 0.11
Nodes (9): instance_ancestors(), normalize_selection(), SelectionError, _series_by_uid(), _sop_index(), sop_series_uid(), InstanceAncestorsTests, NormalizeSelectionTests (+1 more)

### Community 43 - "DICOM Archive Service"
Cohesion: 0.09
Nodes (9): archive_study(), ArchiveError, _sanitize_segment(), _study_stats(), ArchiveStudiesBatchTests, ArchiveStudyTests, ArchiveTestBase, CleanupTests (+1 more)

### Community 44 - "DICOM Server Admin"
Cohesion: 0.08
Nodes (13): AutoRetrievalStateAdmin, DICOMServerConfigurationAdmin, InboundDICOMInstanceAdmin, PatientIDAliasInline, RemoteDICOMNodeAdmin, RetrievalBatchAdmin, RetrievalBatchPatientAdmin, RetrievalJobAdmin (+5 more)

### Community 45 - "Community 45"
Cohesion: 0.06
Nodes (16): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+8 more)

### Community 46 - "Community 46"
Cohesion: 0.14
Nodes (3): create(), TableExtractParallelTests, TableExtractTests

### Community 47 - "Community 47"
Cohesion: 0.12
Nodes (10): _norm_span(), parse_tagged(), score_entities_pairs(), iou(), llm_chat(), main(), run_match(), run_tag() (+2 more)

### Community 48 - "Community 48"
Cohesion: 0.09
Nodes (8): build_context(), endpoint(), judge_span(), _so_post(), LlmDeidConfigurationError, is_cloud_provider(), is_local_endpoint(), validate_base_url()

### Community 52 - "Community 52"
Cohesion: 0.11
Nodes (15): _check_patient_ids(), _delete_study_rows(), _dicom_date(), _expected_folder_path(), Migration, _parse_dt(), _parse_manifest(), recover_archived_studies() (+7 more)

### Community 53 - "Community 53"
Cohesion: 0.08
Nodes (26): Allauth Auth UI, Alert (page), Badge (page), Button (page), Button Group (page), Details (page), Field (page), Fields (page) (+18 more)

### Community 54 - "Community 54"
Cohesion: 0.08
Nodes (12): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+4 more)

### Community 55 - "Community 55"
Cohesion: 0.12
Nodes (8): ArchiveConfigurationForm, Meta, ArchiveLocationForm, Meta, TestArchiveConfigurationForm, TestArchiveLocationForm, ArchiveConfigUpdateView, ArchiveLocationUpdateView

### Community 56 - "Community 56"
Cohesion: 0.11
Nodes (6): read_manifest(), read_manifest_entries(), LegacyImportTaskTests, TaskCheckpointServiceTests, TaskProgressResumeBarTests, TaskRegistryCoverageTests

### Community 57 - "Community 57"
Cohesion: 0.14
Nodes (6): _auto_retrieve_patient_node(), task_auto_retrieve_node(), task_auto_retrieve_patient(), task_auto_retrieve_patient_batch(), AutoRetrievalTaskTests, _fake_async_result()

### Community 60 - "Community 60"
Cohesion: 0.15
Nodes (4): LlmNerClient, LlmNerRecognizer, LlmNerClientTests, LlmNerRecognizerTests

### Community 62 - "Community 62"
Cohesion: 0.15
Nodes (3): OpenMedNerError, OpenMedNerRecognizer, OpenMedNerRecognizerTests

### Community 63 - "Community 63"
Cohesion: 0.11
Nodes (3): DiagnosisUpdateView, ModelPermissionMixin, PatientUpdateView

### Community 64 - "Community 64"
Cohesion: 0.14
Nodes (7): _make_canonical_id(), _fill(), iter_find_responses(), match_date(), match_value(), _patient_matches(), _wildcard_regex()

### Community 65 - "Community 65"
Cohesion: 0.12
Nodes (8): Step10ReviewForm, FileDurationDateMapping, Meta, FileMissingRelations, Meta, FileParentRecordMapping, Meta, Step11ReviewView

### Community 66 - "Community 66"
Cohesion: 0.17
Nodes (17): Step 10 Missing FK Relationships, CSV Data Import Workflow, Data Import Wizard, Base Import (page), Session List (page), Step10 Missing Relations (page), Step11 Review (page), Step12 Complete (page) (+9 more)

### Community 67 - "Community 67"
Cohesion: 0.10
Nodes (5): TestNavIntegration, TestComponentExtraClassIsolation, TestLocationTestButtons, ArchiveViewTestCase, TestPermissionGating

### Community 68 - "Community 68"
Cohesion: 0.24
Nodes (3): make_field(), make_response_model(), make_table()

### Community 69 - "Community 69"
Cohesion: 0.12
Nodes (3): Step1UploadCSVForm, Meta, Step1UploadCSVView

### Community 70 - "Community 70"
Cohesion: 0.18
Nodes (6): dearchive_study(), DearchivalRequiredTests, DearchiveStudiesBatchTests, DearchiveStudyTests, DearchiveTestBase, EnsureStudiesLocalTests

### Community 71 - "Community 71"
Cohesion: 0.19
Nodes (5): build_table_question_prompt(), _lookup_choices_line(), _question_for(), table_docstring(), TablePromptTests

### Community 72 - "Community 72"
Cohesion: 0.14
Nodes (3): FlashMessageRenderingTests, ModelDocstringTests, TaskRunResumeRetryViewTests

### Community 74 - "Community 74"
Cohesion: 0.18
Nodes (4): LlmNerError, LlmNerParseError, _parse_entity_output(), LlmNerParseTests

### Community 76 - "Community 76"
Cohesion: 0.12
Nodes (8): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration

### Community 78 - "Community 78"
Cohesion: 0.16
Nodes (5): PatientImportSerializer, Meta, FileImportJSON, Meta, ImportExecutorService

### Community 79 - "Community 79"
Cohesion: 0.12
Nodes (6): FieldLookupValues, Meta, FileColumnFieldValueMapping, Meta, Step5ColumnValueMappingView, Step8LookupMappingView

### Community 81 - "Community 81"
Cohesion: 0.17
Nodes (3): find_patient(), FindPatientTests, SanitizeTests

### Community 82 - "Community 82"
Cohesion: 0.30
Nodes (3): IngestSelectionFilterTests, make_rt_dataset(), _ref_sop_item()

### Community 83 - "Community 83"
Cohesion: 0.12
Nodes (16): DICOM Server, Batch Detail (page), Batch List (page), Batch Select (page), Config Form (page), Dashboard (page), Job Detail (page), Job List (page) (+8 more)

### Community 84 - "Community 84"
Cohesion: 0.16
Nodes (5): Migration, add_archive_perms_to_dicom_admin(), _archive_perm_codenames(), Migration, remove_archive_perms_from_dicom_admin()

### Community 87 - "Community 87"
Cohesion: 0.27
Nodes (6): _discover_anthropic(), discover_capabilities(), _discover_ollama(), _discover_openai_compatible(), _is_reasoning_model(), _is_vision_model()

### Community 88 - "Community 88"
Cohesion: 0.15
Nodes (3): FileImportSession, Meta, ImportSessionListView

### Community 91 - "Community 91"
Cohesion: 0.24
Nodes (3): _encrypt_value(), LegacyImportServiceTests, _make_legacy_db()

### Community 93 - "Community 93"
Cohesion: 0.22
Nodes (4): Notification, Meta, NotificationType, AutoContinueTaskTests

### Community 95 - "Community 95"
Cohesion: 0.18
Nodes (11): Archive Operator Role, Archive Viewer Role, DICOM Administrator Role, DICOM Archive Permissions, DICOM Archive, Archived List (page), Browse (page), Config Edit (page) (+3 more)

### Community 96 - "Community 96"
Cohesion: 0.25
Nodes (3): _db_cleanup(), handle_echo(), handle_find()

### Community 97 - "Community 97"
Cohesion: 0.27
Nodes (4): Command, llm_chat(), run_match(), run_tag()

### Community 101 - "Community 101"
Cohesion: 0.22
Nodes (3): associate_dicom_files_to_project(), ProjectSelectionForm, Media

### Community 102 - "Community 102"
Cohesion: 0.24
Nodes (4): Migration, Migration, default_hf_label_map(), default_rules()

### Community 103 - "Community 103"
Cohesion: 0.29
Nodes (3): ArchiveConfigurationAdmin, ArchivedStudyAdmin, ArchiveLocationAdmin

### Community 110 - "Community 110"
Cohesion: 0.22
Nodes (4): DiagnosisImportSerializer, Meta, PathologyImportSerializer, Meta

### Community 112 - "Community 112"
Cohesion: 0.22
Nodes (4): Step2PatientIDMappingForm, FilePatientID, Meta, Step2PatientIDMappingView

### Community 113 - "Community 113"
Cohesion: 0.28
Nodes (3): get_item(), get_nested_item(), index()

### Community 117 - "Community 117"
Cohesion: 0.29
Nodes (3): study_age_days(), LocationPathTestBase, StudyAgeDaysTests

### Community 118 - "Community 118"
Cohesion: 0.25
Nodes (3): Migration, Migration, Migration

### Community 121 - "Community 121"
Cohesion: 0.25
Nodes (7): components, button, card, custom_form, legacy_card, pagination, table

### Community 122 - "Community 122"
Cohesion: 0.38
Nodes (4): _expected_folder_path(), fix_dicomstudy_folder_paths(), Migration, _sanitize()

### Community 123 - "Community 123"
Cohesion: 0.24
Nodes (3): LaboratoryResults, Meta, PatientDicomFile

### Community 131 - "Community 131"
Cohesion: 0.38
Nodes (4): create(), create(), create(), create()

### Community 132 - "Community 132"
Cohesion: 0.33
Nodes (5): Django Admin UI, Card (page), Change Form (page), Change List (page), Index (page)

### Community 137 - "Community 137"
Cohesion: 0.27
Nodes (3): DICOMStudyProject, Meta, UUIDEncoder

### Community 139 - "Community 139"
Cohesion: 0.33
Nodes (5): Associate DICOM to Project (admin action), DICOM Data Export, Dicom Data Export (page), Dicom Export Progress (page), Dicomstudy List (page)

### Community 144 - "Community 144"
Cohesion: 0.33
Nodes (6): Bulk DICOM Import, Bulk Dicom Complete (page), Bulk Dicom Confirmation (page), Bulk Dicom Matching (page), Bulk Dicom Session List (page), Bulk Dicom Upload (page)

### Community 147 - "Community 147"
Cohesion: 0.40
Nodes (3): BulkDICOMStudyMatch, MatchStatus, Meta

### Community 152 - "Community 152"
Cohesion: 0.40
Nodes (5): De-identification, Legacy Import (page), Legacy Import Results (page), Patient Detail (page), Patient List (page)

### Community 204 - "Community 204"
Cohesion: 0.50
Nodes (3): Base Layout & Auth, 403 (page), Login (page)

### Community 205 - "Community 205"
Cohesion: 0.50
Nodes (4): Patient Management, Patient Data Export (page), Patient Search (page), Patient Summary New (page)

### Community 206 - "Community 206"
Cohesion: 0.50
Nodes (4): Task Management, Task Progress (page), Taskrun Detail (page), Taskrun List (page)

## Knowledge Gaps
- **38 isolated node(s):** `403 (page)`, `Card (page)`, `Alert (page)`, `Badge (page)`, `Button (page)` (+33 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 2104 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **190 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Patient` connect `Patient & Site Models` to `Extractor Forms & Deid Config`, `DICOM Study/Series/Instance Models`, `Instructor Extraction Service`, `Bulk Retrieval Scheduling`, `DRF Serializers`, `Extraction Result Models`, `DICOM Server Forms & Views`, `Deid Backfill Command`, `DICOM QR Client (Query/Retrieve)`, `Clinical Data Forms`, `Extraction Review & Record Ops`, `Celery Tasks & TaskRun`, `Bulk DICOM Upload Models`, `Data Import Forms`, `Data Import Model Writers`, `Bulk Patient Study Query`, `DICOM Auto-Retrieval Signals`, `DICOM Server Forms`, `DICOM Ingest Service`, `Navbar Visibility Tests`, `Task Resume & Retrieval Tests`, `DICOM Archive Service`, `Community 57`, `Community 64`, `Community 67`, `Community 73`, `Community 75`, `Community 81`, `Community 82`, `Community 85`, `Community 86`, `Community 91`, `Community 105`, `Community 111`, `Community 112`?**
  _High betweenness centrality (0.123) - this node is a cross-community bridge._
- **Are the 63 inferred relationships involving `Patient` (e.g. with `PatientForm` and `UnifiedClinicalDataResource`) actually correct?**
  _`Patient` has 63 INFERRED edges - model-reasoned connections that need verification._
- **What connects `403 (page)`, `Card (page)`, `Alert (page)` to the rest of the system?**
  _38 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Extraction Mgmt Commands` be split into smaller, more focused modules?**
  _Cohesion score 0.02730281301709873 - nodes in this community are weakly interconnected._
- **Why does `DICOMStudy` connect `DICOM Study/Series/Instance Models` to `Bulk Retrieval Scheduling`, `Patient & Site Models`, `DRF Serializers`, `DICOM QR Client (Query/Retrieve)`, `Clinical Data Forms`, `Celery Tasks & TaskRun`, `Bulk DICOM Upload Models`, `Clinical Form Views (CRUD)`, `Bulk Patient Study Query`, `DICOM Ingest Service`, `DICOM Archive Views`, `Task Resume & Retrieval Tests`, `DICOM Archive Service`, `Community 52`, `Community 57`, `Community 59`, `Community 63`, `Community 64`, `Community 67`, `Community 73`, `Community 80`, `Community 85`, `Community 86`, `Community 92`, `Community 101`, `Community 109`, `Community 117`, `Community 126`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **Are the 51 inferred relationships involving `DICOMStudy` (e.g. with `DiagnosisUpdateView` and `ForeignKeyInitMixin`) actually correct?**
  _`DICOMStudy` has 51 INFERRED edges - model-reasoned connections that need verification._
- **Should `Extractor Config & Django Core` be split into smaller, more focused modules?**
  _Cohesion score 0.028024606971975393 - nodes in this community are weakly interconnected._
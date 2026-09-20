# Extractor App — LLM Extraction Audit Report

**Audit date:** 2026-09-20  
**Revision:** Fourth pass — adds findings 62–71 (encryption-key fallback, deletion cascades that destroy reviewed results, discovery overwriting manual lookup corrections, tool-name validity, prompt/type contradiction, threshold reuse, Ollama truncation, PHI in filenames, operational limits, documentation drift). Third-pass content retained.  
**Scope:** Uploaded documents → text conversion → response-model configuration → LLM requests → lookup resolution → saved results → human review. Supporting templates, admin, embedding jobs, dependencies, and deployment configuration were inspected where relevant. No application fixes were made.

**Important scope clarification:** The existing `deidentification` app is **not designed to deidentify clinical input documents for extractor**. Its absence from this pipeline is not a missing integration or a defect. This report does not recommend connecting it to extractor. Authorization to send clinical text to a configured provider, transport security, logging, and retention remain separate extractor/deployment responsibilities; they do not imply that input deidentification is required.

**Deployment context (reviewer-provided):** The application will be deployed on a hospital LAN, not the public internet, and will be accessible to hospital users only. This lowers the priority of internet-facing exposure findings but does not remove them: internal SSRF can still reach clinical network systems, a stored key can still egress to a mistyped internal endpoint, and hospital users are not a uniform access group — role/minimum-necessary scoping remains an open policy question. LAN deployment also makes the LAN-hosted-LLM timeout in finding 70 more likely to matter.

## 1. Plain-language summary

The principal concern is not just requests failing. Several paths can report success while losing information or assigning the wrong meaning to it.

- **The AI may receive damaged input.** Spreadsheet conversion can remove leading zeros and turn text such as `NA` or `None` into empty cells. Different worksheet names can produce the same output filename, silently replacing one sheet with another.
- **Missing material can go unnoticed.** A workbook can be marked complete when one sheet failed. A PDF can convert to an empty text file without a quality check or explicit OCR fallback.
- **The setup preview does not describe what extraction actually does.** The wizard shows nested records and validators; actual extraction uses a flat model with optional fields. Repeated field names collide, multiple records cannot be represented faithfully, and an answer in the wrong shape can silently become all-null data.
- **Clinical validation is weaker than previously understood.** Numeric limits already defined in the clinical models are not properly discovered, so simply switching to the previewed model would not fix them. Field descriptions and unit expectations are also missing from the runtime prompt/schema.
- **Lookup matching can lose essential distinctions.** For example, CTCAE lookup display-field discovery keeps the adverse-event term but loses the grade and description. Different grades can then match the same label.
- **Some failure indicators are unreliable.** Embedding computation can report success after every encoding failed; the extraction dashboard calls a file “Extracted” if any job exists, including a failed or pending one.
- **Review and traceability have gaps.** Undoing a correction can silently fail. Reprocessing overwrites source-text paths used by old jobs, and configuration changes during a run can change how its answers are saved.
- **Previously identified security and privacy concerns remain:** full documents and credentials are logged; parsed output is also retained without field-level encryption; embedding keys are exposed to authenticated users; configurable endpoints and editable file paths need appropriate trust boundaries.
- **"Encrypted" fields may be encrypted with a key that is in the source code.** If the deployment does not set its own key, the committed fallback is used, so extracted values and LLM API keys are only nominally protected. The sample environment file supplies an invalid key that prevents startup, which pushes operators toward the committed fallback. (Comment: This does not need fixing. Will be deployed in production with proper keys.)
- **Deleting an uploaded file also deletes every reviewed result derived from it.** The confirmation dialog mentions only the file and its processed versions. Deleting a response model, database table, or client configuration in admin has the same effect. (Comment: We should surface the related deletions in the UI.)
- **Re-running the setup wizard silently undoes manual lookup corrections.** Schema discovery re-guesses the display field each time, so a `fix_lookup_value_fields` correction is reverted the next time anyone starts the wizard. (Comment: What can be done about this ?)
- **Response-model names can break OpenAI tool calls, and the prompt contradicts the schema.** Punctuation or long names become invalid function names; the prompt tells the model to return "exact text" while boolean and integer fields reject text such as "present" or "12 per 10 HPF", causing hidden retries and failures.
- **Documentation promises checks the code does not perform** (file-type validation, pre-extraction validation, range validators, encrypted storage). (Comment: These are important to be implemented.)

**Not every risk is a confirmed deployment incident.** The app intentionally supports local LLM endpoints, and shared access may be intentional in a single-site installation. Those policies must be established before labeling all private endpoints or shared patient access as vulnerabilities. No live-provider accuracy, exploit, production-data, or database-write tests were performed in this pass. (Comment: This application will be deployed in a LAN not on the internet. It will be accessible to users in the hospital only.)

## 2. Method, evidence, and corrections

### Evidence labels

- **Verified:** reproduced with synthetic data, in-memory documents, mocked network/storage/ORM calls, or an installed-library behavior check. This does not mean production was exercised.
- **Code-confirmed:** a reachable implementation defect is visible in the cited code; it was not reproduced end-to-end.
- **Conditional risk:** impact depends on permissions, configuration, deployment, document contents, or an unconfirmed requirement.
- **Coverage gap:** a missing safeguard or capability, not proof that the LLM actually produced a particular wrong answer.

Severity prioritizes clinical data integrity and exposure: **High**, **Medium**, **Low**, or **Info**. Earlier blanket “Critical” ratings have been narrowed where exploitability, clinical harm, or deployment scope was not demonstrated. Original finding numbers 1–50 are retained; third-pass additions are 51–61 and fourth-pass additions are 62–71. Several findings share a root cause, so the register is not a count of independent exploits.

### Corrections to the first two passes

1. **Deidentification:** remove the alleged missing integration and mandatory-input-deidentification recommendation. The user has explicitly clarified that application's different purpose.
2. **Dependencies:** `openpyxl==3.1.5` is both declared and installed. The missing dependency claim was wrong. `sentence-transformers` and `anthropic` remain absent from the inspected venv.
3. **Database:** a settings default and an unrelated SQLite file do not identify the deployed database. The user's migration command reported no pending migrations. Django's `CreateExtension` forward operation skips SQLite; it does not itself make SQLite migrations fail. PostgreSQL/pgvector is needed for the implemented similarity queries, not necessarily for every extractor feature.
4. **Ordering:** Django `.first()` uses model ordering or adds primary-key ordering. The lookup problem is ambiguous or clinically wrong first-match selection, not inherently random ordering.
5. **Cleanup:** `django_cleanup.apps.CleanupConfig` is enabled (`chavi_client/settings.py:72`). It covers `FileUpload.file`, a `FileField`, including deletion signals. It does not cover `ProcessedText.processed_file_path`, a `CharField`. Blanket claims that all uploaded files leak on cascades were incorrect.
6. **Range validators:** ordinary numeric strings are interpolated into numeric comparisons, e.g. `v < 0`, not `v < '0'`. That code-generation failure claim is withdrawn. The actual missing-bounds defect is finding 54.
7. **One-to-one relationships:** `OneToOneField` subclasses `ForeignKey`; `_determine_field_type` already handles it via `isinstance`. The claimed omission is withdrawn.
8. **Providers:** consecutive user messages are not established here as an Anthropic API failure. Google/Mistral/Cohere/Other may work through compatible endpoints. Traditional Azure APIs and Azure's OpenAI-compatible APIs must not be conflated. Endpoint construction and connection-test inconsistencies remain real.
9. **Vector dimensions:** different configurations sharing a variable-dimension column are not automatically incompatible; the query filters by configuration. Editing/reusing a configuration without invalidating its model and vectors is the supported concern.
10. **Generated-code execution:** `wizard_step4` calls validation once; `response_model_detail` builds/displays code but does not execute it. Claims of two executions on every detail-page view were wrong.
11. **Timeouts and checks:** a long Gunicorn timeout does not guarantee no proxy/client timeout. A successful `manage.py check` is not evidence that migrations, provider calls, clinical accuracy, or every code path work.
12. **Configured lookup PK:** all lookup models inspected use `code` as the actual primary key. The ignored configured-PK argument is a conditional extensibility/configuration bug, not demonstrated corruption in the default discovered schema.

### Third-pass verification receipts

All tests used synthetic values. Isolated Django imports used `settings.configure()` with an in-memory database definition, an ephemeral encryption key, and no project settings; ORM/storage calls in service probes were mocked. No patient records, credentials, real uploaded files, live LLMs, migrations, or persistent database writes were used.

| Check | Observed result |
|---|---|
| Installed package metadata | Django 6.0.8; OpenAI 3.3.0; Instructor 1.17.0; Pydantic 2.13.5; pandas 3.0.5; openpyxl 3.1.5; sentence-transformers/anthropic not importable |
| OpenAI SDK with HTTP mock transport | Base ending `/v1/chat/completions` generated `/v1/chat/completions/chat/completions`; no real HTTP request |
| XLSX built in memory, then default `read_excel`/`to_csv` | Text identifiers `000123`, `000456` became `123`, `456`; `NA`, `NULL`, `None`, `N/A` became empty CSV cells |
| Worksheet-name sanitizer | `Lab A` and `Lab_A` both became `Lab_A` |
| Synthetic blank PDF through MarkItDown | Conversion returned `''` without a conversion exception |
| Real `_process_excel`, mocked sheets/storage/ORM | One good sheet plus one raising an exception returned `success=True` and a nonempty `errors` list |
| Real `_extract_validation_rules` on bounded DecimalField | Returned nullable/optional/has_validators, but no minimum, maximum, decimal precision, or scale |
| Real range/choice generation | Numeric bounds generated valid numeric comparisons; integer choices generated string comparisons |
| Pydantic optional flat model given nested data | Nested unexpected key was ignored; output became `{'amount': None}` |
| Real lookup display-field discovery | CTCAE selected `ctcae_term`; performance status selected `code`; every inspected lookup model had actual PK `code` |
| Real unwrapped review view with mocked result | Submitting the original value retained the previous correction and `data_edited=True` |
| Real embedding task with all encoding calls failing and mocked ORM | Refresh deletion was requested on the mock; task called `mark_complete(success=True, total_processed=0)`, not `mark_failed` |
| Django `CreateExtension` on a mocked SQLite schema editor | No SQL execution |
| Django `QuerySet.first()` with a probe object | Added `order_by('pk')` when no ordering existed |
| **4th pass:** `settings.py` encryption key expression | `os.environ.get(..., '<literal>')` with a syntactically valid 32-byte Fernet fallback committed in git; `sampleenv` key decodes to 21 bytes and is rejected by `Fernet()`; `encrypted_model_fields` builds its crypter at import time; no tracked docker/entrypoint config sets the variable |
| **4th pass:** `on_delete` introspection of extractor FKs | CASCADE on every link in `Patient → FileUpload → ProcessedText → ExtractionJob → ExtractionResult`, and on `ExtractionJob.response_model`, `ExtractionResult.database_field`, `DatabaseField.table`, `DatabaseTable.content_type`, `ResponseModel.client` |
| **4th pass:** `_create_or_update_database_fields` source | `update_or_create` defaults include `lookup_table_value_field_name` and `field_validation` → overwritten on every discovery run |
| **4th pass:** Instructor `openai_schema` on `create_model("Dx(v2)/PathModel")` | Function name passed through unsanitized; fails OpenAI `^[a-zA-Z0-9_-]{1,64}$` |
| **4th pass:** Pydantic coercion of "exact text" into typed fields | `"present"` → `bool_parsing` error; `"12 per 10 HPF"` → `int_parsing` error; `"yes"`/`"12"` coerce |
| **4th pass:** 213 `client_app` field names vs Pydantic namespace | No collisions with `BaseModel` attributes; no `model_` prefixes — **clean** |
| **4th pass:** `git ls-files` for `media/`, `logs/`, `db.sqlite3`, `.env*` | Nothing tracked; `.gitignore` covers them — **clean** |
| **4th pass:** `LookupEmbedding._meta.indexes` | Only B-tree indexes on `(content_type, field_name)` and `object_id`; no vector index |

These checks establish mechanics, not measured clinical error rates. No live provider behavior or OCR accuracy was benchmarked. Ignored venv source files were not available for file inspection; installed-library checks and repository source were used instead.

## 3. Findings register

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| 1 | High | OpenAI API-root construction duplicates the completion path | Verified |
| 2 | High | Embedding dependencies/API incompatibility disables supported search paths | Verified / code-confirmed |
| 3 | High | Documents, extracted data, and authentication headers logged | Code-confirmed |
| 4 | High | Semantic search can return different text than the configured display label | Code-confirmed |
| 5 | High | Candidate shortlist uses only the first 500 characters | Code-confirmed |
| 6 | High | Flat optional runtime model diverges from nested preview | Verified / code-confirmed |
| 7 | Medium | Lookup values are Python repr, not JSON | Verified in earlier pass |
| 8 | High | Machine output labeled accurate and assigned a verifier before review | Code-confirmed |
| 9 | High | Empty/unreadable processed content can reach the LLM | Code-confirmed |
| 10 | Medium | No context-budget check or chunking implementation | Code-confirmed |
| 11 | Medium | Provider setup and connection tests use inconsistent contracts | Code-confirmed |
| 12 | Medium | Bulk extraction runs in the web request; retries and double-submits duplicate work | Code-confirmed |
| 13 | High | Same-PK config edits leave cached embedding model/vectors stale | Code-confirmed |
| 14 | Medium | Wizard/detail error handling and field ownership validation gaps | Code-confirmed |
| 15 | Medium | Derived-path cleanup uses the wrong path base | Code-confirmed |
| 16 | High | Embedding administration lacks model-permission checks | Code-confirmed |
| 17 | Medium | Extraction accepts incomplete/empty model configurations | Code-confirmed |
| 18 | Medium | Embedding jobs run in daemon threads; nothing detects or restarts a dead one | Code-confirmed |
| 19 | High | First-match lookup resolution does not reject ambiguous labels | Code-confirmed |
| 20 | Medium | Fixed token budget, SDK-default timeout, and missing usage accounting | Code-confirmed |
| 21 | Medium | Generated-model validation can report misleading success | Code-confirmed |
| 22 | High | Display-field guessing loses CTCAE grade and other composite meaning | Verified / code-confirmed |
| 23 | Low | Dashboard/results N+1 queries and unbounded listings | Code-confirmed |
| 24 | Medium | Untyped serialization and omitted null result rows impair review | Code-confirmed |
| 25 | Medium | Reprocessing duplicates rows; encoding/resource checks absent | Code-confirmed |
| 26 | Low | Client configuration bypasses model validation | Code-confirmed |
| 27 | Low | Prompt role/content/order validation is incomplete | Code-confirmed |
| 28 | Low | Unsupported type fallback and secondary maintenance issues | Code-confirmed |
| 29 | Info | Similarity queries require PostgreSQL/pgvector | Backend constraint |
| 30 | Info | Write-back and chunking models/flags are not implemented workflows | Scope/capability gap |
| 31 | High | Endpoint control can redirect credentials and documents | Conditional risk |
| 32 | High | Cross-resource permission checks missing; object-scoping policy unknown | Code-confirmed / conditional risk |
| 33 | High | Plain JSON response duplicates encrypted clinical result data | Code-confirmed |
| 34 | High | Completion precedes non-atomic result persistence | Code-confirmed |
| 35 | Medium | Semantic path ignores configured non-PK code field | Conditional risk |
| 36 | High | Upload validation bypass can leave unsupported files in storage | Code-confirmed |
| 37 | High | Untrusted document instructions lack an extraction trust boundary | Coverage gap / conditional risk |
| 38 | High | User deletion cascades through extraction history | Code-confirmed |
| 39 | Medium | Browser embedding task ignores selected provider | Code-confirmed |
| 40 | Medium | Empty candidate fallback and embedding freshness are incomplete | Code-confirmed |
| 41 | Medium | Schema refresh leaves stale fields and offers internal relationship IDs | Code-confirmed |
| 42 | High | Embedding API key is plaintext and returned to login-only edit view | Code-confirmed |
| 43 | High | Editable processed path permits reads/deletes outside media storage | Conditional risk |
| 44 | Medium | No explicit support for traditional Azure deployment/version contracts | Conditional risk |
| 45 | Low | Credential expiry and refresh fields have no runtime effect | Code-confirmed |
| 46 | Medium | CSV source aliases and derived-file cleanup require separate ownership | Code-confirmed / latent risk |
| 47 | Medium | Generated choice validators stringify types and fail to escape values | Verified / conditional reachability |
| 48 | Medium | Embedding task buffers entire tables; repeated query embedding work | Code-confirmed |
| 49 | Medium | Review values lack validation and cannot be explicitly cleared | Code-confirmed |
| 50 | High | Upstream/provider strings rendered through `innerHTML` | Code-confirmed sink / conditional exploit |
| 51 | High | Different worksheet names overwrite the same CSV | Verified |
| 52 | High | Excel conversion changes identifiers and literal text | Verified |
| 53 | Medium | PDF conversion lacks text-coverage/empty-output/OCR failure handling | Verified empty-output path / coverage gap |
| 54 | High | Discovery drops actual clinical bounds, precision, and model validation | Verified / code-confirmed |
| 55 | High | Jobs lack immutable source/config snapshots; in-flight edits change results | Code-confirmed |
| 56 | High | Partial workbook conversion is shown as complete | Verified |
| 57 | High | Refresh discards old embeddings before success and can report zero-result success | Verified with mocks |
| 58 | Medium | Undoing a correction silently keeps the old correction | Verified with mocks |
| 59 | Medium | Dashboard marks failed/pending jobs as extracted | Code-confirmed |
| 60 | High | Clinical unit, evidence, identity, and temporal context safeguards absent | Coverage gap |
| 61 | Medium | Shared wizard session state and destructive backtracking lose configuration | Code-confirmed |
| 62 | High | Field encryption falls back to a key committed in source; sample env key is invalid | Verified — fix deferred (prod keys planned) |
| 63 | High | File/config deletion cascades destroy reviewed extraction results; confirmation omits this | Verified — cascade intended (staging data); UI disclosure implemented |
| 64 | High | Every wizard start re-guesses lookup display fields, reverting manual/`fix_lookup_value_fields` corrections | Verified — fix options provided |
| 65 | High | Response-model name becomes an unsanitized OpenAI tool/function name | Verified / conditional on provider |
| 66 | High | "Extract the exact text" instruction contradicts typed bool/int/float fields → hidden retries and failures | Verified |
| 67 | Medium | One similarity threshold governs both label↔label and document-snippet↔label comparisons | Code-confirmed / conditional |
| 68 | Medium | Ollama silently truncates over-length prompts; no context-size control via OpenAI-compatible API | Conditional risk |
| 69 | Medium | Upload filenames (possibly PHI) propagate to logs/paths; full patient list and orphan response models exposed | Code-confirmed |
| 70 | Low | Per-worker model loading, no vector index, LAN-Ollama timeout heuristic, login-only progress endpoint | Code-confirmed |
| 71 | Medium | Documentation claims validation/encryption/range-validator behavior the code does not deliver | Verified — controls to be implemented |

## 4. Detailed findings

All relative paths below are relative to the repository root. `services/...` and `models.py` references explicitly include `extractor/` to avoid ambiguity.

### 1. OpenAI API root is confused with a completion endpoint

**Evidence:** `extractor/services/instructor_extractor.py:37-61`, especially line 54; `extractor/views.py:606-639`.

For an OpenAI-style provider with a base URL lacking the substring `v1`, the factory appends `/v1/chat/completions`; the SDK appends `/chat/completions` again. An offline HTTP transport test confirmed the doubled path. The `v1` substring test can also be satisfied by a hostname rather than a version path. Conversely, the connection test blindly appends `/v1/chat/completions`, even if the configured URL already ends in `/v1`.

**Impact/direction:** normal root configurations can fail, and testing and extraction disagree. Normalize a provider-specific API root once and reuse the actual extraction client for tests. A compatible custom proxy could accept unusual routes; a universal 404 was not established.

### 2. Semantic-search implementation is unavailable on the inspected dependency paths

**Evidence:** `extractor/services/semantic_search.py:38-97`; `extractor/tasks.py:42-49`; `extractor/management/commands/compute_lookup_embeddings.py:96-131,208-217`; `requirements.txt`.

The inspected environment lacks sentence-transformers. The alternative OpenAI path calls the removed `openai.Embedding.create` API with OpenAI 3.3.0. Search catches failures and returns empty results; label resolution still tries exact matching before any semantic or partial fallback. It is therefore incorrect to say all matching is disabled.

**Impact/direction:** when the semantic part fails, only plain text matching keeps working — the AI quietly gets fewer and worse options with no warning shown to anyone. Install the missing dependencies or fix the removed OpenAI embedding call, and make it visible in the UI when semantic search is unavailable or its index is incomplete. The embedding progress UI can show task failure, so the earlier assertion that nobody ever sees an error was too broad.

### 3. Clinical documents and credentials are logged

**Evidence:** `extractor/services/instructor_extractor.py:380-394,481-495`; `extractor/views.py:591-595,645-662`; `chavi_client/settings.py:209-217,246-250`.

INFO logs include complete prompt messages and extracted data; connection testing logs headers containing provider credentials. Extractor logging is routed to console and `logs/debug.log`. These are concrete disclosure paths independent of any input-deidentification requirement.

**Direction:** structured metadata-only logging, redacted exceptions/headers, and appropriate log access/retention. No real logs or keys were inspected to demonstrate this.

### 4. Candidate text and configured display labels can disagree

**Evidence:** `extractor/services/semantic_search.py:144-171`; `extractor/services/instructor_extractor.py:215-243,266-305,466-479`.

Similarity search returns the text of whichever embedded field matched, including a code or description, rather than consistently using the configured display field. The LLM is asked to echo that text, then a separate lookup tries to resolve it against the configured display field. Semantic rematching may recover the same object, so failure is not guaranteed, but the link to the original lookup row is thrown away and the second match may pick a different answer.

**Direction:** keep track of which lookup row each shown candidate came from, display the configured label for that row, and when saving the answer match it only against the candidates actually shown in that request — not against the whole table a second time.

### 5. Lookup shortlist ignores most of a long document

**Evidence:** `extractor/services/semantic_search.py:202-211`; `extractor/services/instructor_extractor.py:170-175,235-239`.

Only the first 500 characters choose the candidates; `top_k_results` defaults to five but is configurable, not a hard maximum. A later diagnosis, site, or drug may have no correct candidate. The prompt permits null when no option matches; this is an omission/wrong-choice risk, not proof of a forced hallucination.

**Direction:** choose candidates using the parts of the document relevant to each field instead of only the first 500 characters, test that the correct option actually makes it into the shortlist, and let the model answer "not found" rather than forcing a pick from a list that may not contain the right answer.

### 6. Runtime schema diverges from the wizard model

**Evidence:** `extractor/services/instructor_extractor.py:86-132,374-389,452-490`; `extractor/services/pydantic_builder.py:31-55,176-197`.

The runtime builder creates one flat all-optional model; the preview defines lists of nested table models with additional validation. Repeated field names overwrite each other in the schema and the same scalar is subsequently saved under each matching table field. Repeated diagnoses/events cannot be represented as distinct records. Pydantic's default extra-field handling also accepts an unexpected nested payload while ignoring its keys: a synthetic nested response became an all-null flat result.

**Direction:** use one schema definition for both preview and extraction, decide how repeated records (e.g., several diagnoses) are stored, decide what a null answer means versus a field that was never attempted, and reject response keys the schema does not expect. Do not simply execute the preview unchanged: findings 21, 47, and 54 show defects there too.

### 7. Stored lookup object is not JSON

**Evidence:** `extractor/services/instructor_extractor.py:475-484`; `templates/extractor/extraction_job_detail.html:145`.

`str({'label': ..., 'code': ...})` produces Python representation syntax, not JSON. A JSON parser fails. The current detail template displays this as text; no downstream JSON consumer was identified, so the earlier claim of an existing downstream crash was too strong.

**Direction:** store lookup results as real JSON going forward, and decide how to handle the rows already saved in the old Python-repr format instead of silently changing what those values mean.

### 8. Extraction assigns accuracy and a verifier before review

**Evidence:** `extractor/services/instructor_extractor.py:486-493`; `extractor/models.py:365-376`.

Results receive `data_accuracy='accurate'` and `verified_by=user` immediately, while the verification timestamp remains null. This conflates model output with reviewed data. `verified_by` is non-nullable, so fixing this requires a schema/workflow decision, not merely omitting the argument.

**Direction:** add a real "not yet reviewed" status, leave the reviewer field empty until a human actually reviews, and record who accepted each result and when.

### 9. Empty or unreadable content does not stop extraction

**Evidence:** `extractor/services/file_processor.py:245-264`; `extractor/services/instructor_extractor.py:528-536,377-389`.

Missing files and decoding/read errors return `''`; existing empty files also return `''`. Bulk extraction passes that content onward without a guard. If the model returns a valid optional response, the job can complete with no evidence or invented values.

**Direction:** fail or require explicit intervention before a paid/provider call on absent, blank, or unusable input; preserve the actual read/conversion error.

### 10. No input-context budget or chunking workflow

**Evidence:** `extractor/models.py:339`; `extractor/services/instructor_extractor.py:166-182,384-389`.

The whole document and candidate lists are sent at once; `processed_file_chunked` has no operational use. Long requests may be rejected or truncated by a provider. Output is capped at 4096 tokens with no schema-size adaptation.

**Direction:** check the prompt size against the model's context limit before sending and fail visibly when it is too large; or split long documents into chunks and reassemble the results — but only after tests show that facts spread across chunks (a diagnosis and its date, a medication and its dose) are not lost or misjoined. Chunking alone is not sufficient for clinical record integrity.

### 11. Connection tests do not validate the extraction protocol

**Evidence:** `extractor/views.py:591-639,664-683`; `extractor/services/instructor_extractor.py:26-84,365-389`.

Anthropic is unavailable without its package, and its configured base URL is not passed to the SDK. Google testing uses a native generateContent URL but retains an OpenAI-shaped payload; generic providers use another URL-building rule. Ollama's native chat test does not test Instructor JSON/schema behavior. HTTP 200 is considered success without validating structured extraction.

**Direction:** test through the same provider adapter, model, mode, and a small synthetic response schema. Do not assume that all non-OpenAI provider labels are broken: compatible API roots may work. The earlier Anthropic consecutive-role failure claim is withdrawn.

### 12. Bulk extraction runs inside the web request and repeats work on retry

**Evidence:** `extractor/views.py:960-1004`; `extractor/services/instructor_extractor.py:497-552`; `gunicorn.conf.py`; `nginx.conf`; `nginx/nginx.conf`.

Selected documents invoke sequential LLM calls within one HTTP request. A double submission or retry creates fresh jobs and incurs repeated work/cost. Worker/proxy/client interruption can leave work in progress or encourage another submission. Timeout settings differ between supplied deployment configurations; no active deployment was inferred.

**Direction:** run extraction as a background job instead of inside the web request, recognize a repeated submission of the same file/schema/user request instead of silently starting duplicate paid calls, and define what a retry should do. Do not block legitimate re-extraction merely because any historical job exists.

### 13. Embedding configuration edits do not invalidate the cached model

**Evidence:** `extractor/services/semantic_search.py:20-54,146-151`; `extractor/models.py:446-465,501-509`; `extractor/views_semantic_search.py:149-160`.

Django model equality compares primary keys. Editing a row's model/provider/key can retain the old process-cached encoder or module-global credential. Existing vectors also retain that configuration ID. Different model versions can be mixed within one ID; equal dimensions do not make their spaces compatible, and unequal dimensions can break distance calculations.

**Direction:** treat each change to model/provider/key as a new configuration version instead of editing the row in place, tie the cached encoder to that version, keep credentials on the client rather than a module global, and switch to a fully built index in one step so old and new vectors are never mixed. Different configurations sharing a variable-dimension column are not by themselves a demonstrated bug because queries filter by config.

### 14. Wizard validation and errors are incomplete

**Evidence:** `extractor/views.py:132-140,184-199,243-275,305-317,339-346`; `extractor/models.py:297-304`.

Posted table/field IDs use unguarded `objects.get`. Field ownership is checked in model `clean()` but that method is not invoked by `objects.create()`. Incomplete configurations can raise in detail/completion views. Step 4 checks configuration validity on POST, not whether generated code validation passed, so invalid code need not prevent completion.

**Direction:** use validated forms, check that posted fields actually belong to the selected tables, and apply the same "is this configuration ready" test when the wizard finishes and when extraction starts.

### 15. Deletion of processed files resolves relative paths incorrectly

**Evidence:** `extractor/models.py:102-120`; `extractor/services/file_processor.py:267-287`.

The model's delete override checks a MEDIA_ROOT-relative string against the working directory. Under a normal repository-root working directory it misses the derived file. Queryset/cascade deletion bypasses the override altogether. The explicit upload-delete service joins MEDIA_ROOT, but its error return is ignored by the calling view.

**Direction:** resolve stored paths against the media directory the same way in every deletion path, and report cleanup failures to the user instead of ignoring them. Account for django-cleanup on uploaded `FileField`s separately (finding 46).

### 16. Embedding administration is login-only

**Evidence:** `extractor/views_semantic_search.py:21-22,74-76,139-141,177-179,195-197,215-217,264-265`.

Any authenticated user can reach embedding configuration create/edit/delete/activate and compute endpoints, unlike model-permission-gated main extractor views. This can change lookup behavior and consume server resources. The API-key edit form adds a direct secret disclosure (finding 42).

**Direction:** require explicit permissions for the embedding configuration and task endpoints, restrict who can supply or use stored credentials, and limit how often and how large these jobs can run. This is missing model-level authorization, not merely object-level authorization.

### 17. Extraction does not require a ready configuration

**Evidence:** `extractor/views.py:975-984`; `extractor/services/instructor_extractor.py:87-132,246,374-389`.

An empty response model can produce an empty Pydantic schema; nothing checks readiness before extraction starts. Posted processed IDs are also not restricted to uploads with completed processing. Provider behavior varies, but a valid empty response can be marked successful.

**Direction:** before starting an extraction, check that the chosen response model actually has fields selected, that the processed file exists and is readable, and that the provider and lookups are usable — and fail the request visibly if not.

### 18. Embedding tasks are not durable

**Evidence:** `extractor/views_semantic_search.py:233-248`; `extractor/tasks.py:23-40,120-129,178-180`.

Daemon threads die with their web worker and nothing detects or restarts a stuck task row. Concurrent requests can duplicate computation. Each text field performs an existence query, and threads never close their database connections. SQLite locking is a backend-dependent risk, not evidence about the active database.

**Direction:** move embedding computation to a real background worker — or at minimum record a heartbeat so a dead task can be detected and restarted — limit how many run at once, and close database connections inside the thread.

### 19. Ambiguous lookup labels silently pick one row

**Evidence:** `extractor/services/instructor_extractor.py:266-301`.

Exact labels need not be unique, and substring matches can identify multiple records. `.first()` chooses model/PK order rather than checking ambiguity. This can consistently choose the wrong clinical code. Exact-match success short-circuits semantic disambiguation. Numeric zero codes would additionally be treated as missing by `if result`, although current discovered lookup PKs are strings.

**Direction:** handle three cases differently: exactly one matching row (accept it), several matching rows (leave it for a human to decide instead of silently taking the first), and no match. See CTCAE-specific evidence in finding 22.

### 20. Request policy and usage accounting are incomplete

**Evidence:** `extractor/services/instructor_extractor.py:48-56,384-400`.

There is no application-specific timeout or output budget policy, and `tokens_used` is always null. SDK timeout/retries and Instructor validation retries do exist; the absence of explicit arguments does not mean there are no timeouts/retries. Temperature is unspecified, but low temperature neither guarantees factuality nor applies uniformly to all models.

**Direction:** set explicit timeouts and output limits per provider, record tokens used and retry counts on each job so cost is visible, and obtain completion metadata in a way the chosen provider supports. Evaluate clinical quality rather than treating deterministic sampling as validation.

### 21. Generated-code validation does not prove usable extraction

**Evidence:** `extractor/services/pydantic_builder.py:245-321,324-354,357-405`; `extractor/views.py:248-273,344-346`.

Step 4 executes generated code once. Sample and empty instantiation failures become warnings, while `valid` only requires successful parsing/execution and no errors. Sample construction often uses nulls and can miss invalid nested validators. Free-text model names are not robustly sanitized as Python identifiers, and configuration content is interpolated into executable code without a sandbox; this is a trust boundary, not grounds for assuming injection is harmless.

Pydantic-v1 APIs (`validator`, `__fields__`, `dict`) are deprecated in the installed v2 environment; future compatibility should be tested, not asserted from a future release. Detail views generate/display code without executing validation.

**Direction:** do not execute generated source code for ordinary schema building; test the generated model against realistic nested sample data — including data that should fail — before calling a configuration ready.

### 22. Display-field discovery loses real clinical distinctions

**Evidence:** `extractor/services/schema_discovery.py:337-378`; `lookup/models.py:141-152,350-357`; `client_app/models.py:1718-1725`; `extractor/services/instructor_extractor.py:267-269`.

The regex picks the first `self.<field>` in `__str__`. Runtime checks on shipped models selected only `ctcae_term` for `LookupCTCAEGrade`, dropping grade/description, and `code` for performance status. Multiple CTCAE rows can share the same adverse-event term but differ in grade; echoing only the term causes exact matching to return the first code, not necessarily the intended grade. No real lookup rows were inspected to assert a specific patient error.

**Direction:** build display labels that keep the full meaning (e.g., adverse-event term plus grade for CTCAE), tie each shown candidate to its lookup row, and test that different grades cannot collapse to the same label. Inherited `__str__` is not inherently uninspectable; composite meaning is the demonstrated defect.

### 23. Unbounded lists and per-row database queries

**Evidence:** `extractor/views.py:901-947,1013-1026`.

The dashboard performs a job existence query per processed file and the result list counts rows per job. Lists have no pagination. This creates avoidable query growth and large pages; no measured production slowdown is claimed.

**Direction:** load related data in bulk instead of one query per row, and paginate long lists — without dropping any permission filtering already applied.

### 24. Result storage loses typing and review visibility

**Evidence:** `extractor/services/instructor_extractor.py:462-493`; `extractor/models.py:365-384`; `templates/extractor/extraction_job_detail.html:145-174`.

Non-string values become text representations, while null fields produce no `ExtractionResult` row. The parsed `raw_llm_response` may retain nulls, but the normal per-field review UI does not make missing fields a first-class review state. Lists/dicts/booleans need consistent typed treatment and record identity.

**Direction:** store result values in a typed format (not plain strings), record an explicit "field was expected but not found" state, and show those missing fields in the review screen instead of omitting their rows.

### 25. Reprocessing and input-resource checks are incomplete

**Evidence:** `extractor/views.py:821-847`; `extractor/services/file_processor.py:95-109,144-150,195-214,257-264`.

Reprocessing creates new rows rather than an explicit file version; paths can be reused. CSV is accepted without parsing or encoding checks, then read as UTF-8; other encodings become read errors/empty input. Extractor does not enforce its own parser/file-size limits, although a deployment may impose HTTP limits.

**Direction:** check each upload's type, encoding, and size before processing, and store reprocessed output under a new version instead of overwriting the same path. Source overwrite consequences are detailed in finding 55.

### 26. Client configuration bypasses model validation

**Evidence:** `extractor/views.py:451-473,508-524`; `extractor/models.py:37-49`.

Create/edit use direct saves, so URL and expiry-dependency validation are not applied. Required-field checking is inconsistent. Django DateTimeField can parse valid input strings; assigning a string is not itself a bug, but malformed dates need controlled validation rather than a persistence error.

**Direction:** use validated forms for create/edit so that URL and expiry rules actually run, plus whatever checks a given provider needs.

### 27. Prompt configuration has weak validation/order controls

**Evidence:** `extractor/views.py:1117-1131,1156-1167`; `extractor/services/instructor_extractor.py:143-157`; `extractor/models.py:260-265,311-325`.

POSTed roles are not checked against choices. Admin JSON prompts can contain non-string `content`; a missing content key falls back to Python dictionary representation. Ordering is solely creation time, and only system/user roles are represented. Absence of few-shot assistant messages is a capability limitation, not inherently an extraction bug.

**Direction:** check that posted roles are valid choices and that prompt content is a string, and let users set message order explicitly rather than relying on creation time.

### 28. Type fallbacks and maintenance issues

**Evidence:** `extractor/services/instructor_extractor.py:108-124,418-425`; `extractor/services/pydantic_builder.py:200-211`; `extractor/services/schema_discovery.py:288-301`.

Tuple types fall back to string, and dates/times are also unconstrained strings at runtime. Exact class-name discovery will not recognize every future custom Django field; no current custom client field omission was established. Generated class names can be invalid for punctuation/leading-digit input. Raw exception strings may expose provider details. Unused variables/imports are lower priority than these observable issues.

### 29. PostgreSQL/pgvector is a similarity-search dependency

**Evidence:** `extractor/migrations/0002_enable_pgvector.py:6-18`; `extractor/services/semantic_search.py:140-178`; `chavi_client/settings.py:137-145`.

Django skips `CreateExtension` on non-PostgreSQL backends; an offline behavior check confirmed that. The implemented cosine-distance query still depends on pgvector capabilities. The configured production/development backend was not inferred from defaults or a SQLite file. No database migration failure was reproduced.

**Direction:** state clearly in configuration and documentation that semantic search requires PostgreSQL with pgvector, check for it at startup, and let unrelated extraction features keep working when it is absent.

### 30. Unimplemented capabilities are not all defects

**Evidence:** `extractor/models.py:339,390-430`; `extractor/admin.py:72-84,313-338`.

`RecordCreation`/`RecordCreationField` and the chunking flag exist without an implemented automatic write-back/chunking workflow in the reviewed extraction path. No extracted values are shown here being automatically written into clinical tables. Document this boundary instead of promising those capabilities.

The separate `deidentification` app has no required role in sanitizing extractor inputs. Its absence is explicitly excluded as a finding.

### 31. Endpoint configuration grants sensitive outbound authority

**Evidence:** `extractor/views.py:451-473,508-524,580-683`; `extractor/services/instructor_extractor.py:37-84`.

A configuration editor can retain an existing stored key while changing its destination; connection testing sends that credential, and extraction sends the document. Non-200 connection responses are partially returned to the caller. Unvalidated endpoints and redirects therefore expose an SSRF/credential-egress trust boundary. This was not exercised against internal or external services.

**Direction:** decide who may authorize destinations and use stored credentials; allow approved local/Ollama/private endpoints rather than blanket-blocking all private addresses. Apply network restrictions, redirect/destination validation, remote TLS requirements, and response redaction consistent with that policy. URL format validation alone is not an SSRF defense.

**Deployment note (reviewer):** LAN-only deployment reduces external-exfiltration risk but not the mechanism — internal SSRF can reach clinical network systems, and a mistyped or compromised internal endpoint still receives the stored key. A pragmatic policy for this environment is an allowlist of approved internal LLM endpoints rather than broad network controls.

### 32. Resource permissions and object-scoping policy

**Evidence:** `extractor/views.py:960-987,1035-1077,1080-1104,757-801`; `extractor/models.py:58-110,333-376`.

An `add_extractionjob` holder can post arbitrary processed-file and response-model IDs without separate checks for access to those resources. `view_extractionjob` reveals source content and extracted values without independently requiring `view_processedtext`/`view_extractionresult`. These are concrete cross-resource permission gaps if those permissions are meant to be separated.

Global patient/object querysets exist, but shared access may be intentional. `processed_by_user` and `extracted_by` do exist; they record actors, not an enforced ownership rule. No multi-tenant policy was provided, so universal cross-tenant IDOR is not established.

**Direction:** specify role/resource/site access requirements, then test and enforce them at each read/write/dispatch boundary. Do not assume uploader-only ownership is the right clinical workflow.

**Deployment note (reviewer):** "accessible to hospital users only" still describes multiple roles and many staff; it does not imply every user may access every patient's documents. The open question is which roles (uploader, reviewer, admin, clinician) should see what — confirm that before deciding whether per-object checks are needed.

### 33. Unencrypted parsed-response duplicate

**Evidence:** `extractor/models.py:345,371-374`; `extractor/services/instructor_extractor.py:392-401`; `extractor/admin.py:278-280`.

The parsed `model_dump()` is saved in a plain JSONField, duplicating potentially sensitive values otherwise stored in EncryptedTextFields. The name `raw_llm_response` is misleading: this is not the original provider response and cannot recover dropped fields or retries.

**Direction:** decide deliberately whether this parsed-response copy should be kept at all, who may see it, and whether it should be encrypted like the result fields; if debugging data is needed, store a separate redacted record designed for that purpose. Database/disk-level encryption was not evaluated.

### 34. Completed status precedes non-atomic persistence

**Evidence:** `extractor/services/instructor_extractor.py:396-425,452-495`; `extractor/models.py:365-384`.

The job is marked complete before result inserts. A mid-loop failure flips status to failed but leaves earlier rows; a crash may leave completed status with incomplete rows. Nothing prevents the same results being saved twice.

**Direction:** save the result rows and the "completed" status in one transaction after the LLM call returns, so a job cannot be marked complete with half its results missing. If multi-record extraction is ever supported, uniqueness must be defined per extracted record — blindly making `(job, field)` unique would preserve the current single-record limitation.

### 35. Configured lookup code field is ignored by semantic results

**Evidence:** `extractor/services/semantic_search.py:99-171`; `extractor/tasks.py:85,111-143`; `extractor/services/schema_discovery.py:326-334`.

Semantic results use actual object PK, whereas exact/partial paths return the configured `pk_field_name`. This disagrees only when those differ. Discovery defaults to the actual PK and all inspected lookup models use PK `code`; default-schema corruption was not established.

The query also limits embedding rows to `top_k * 3` before object deduplication. Tables such as LookupProtein have more than three text fields, so repeated rows for one object can underfill the intended distinct-object shortlist.

**Direction:** either require the configured code field to be the real primary key (and reject other settings), or use the configured field consistently in every lookup path; and apply the result limit after collapsing rows that belong to the same lookup object, not before.

### 36. Unsupported uploads can reach storage before failure

**Evidence:** `extractor/models.py:62-84`; `extractor/views.py:763-790`.

The upload view bypasses the declared extension validator. An unsupported extension sets non-nullable `file_type` to `None`; FileField persistence can write the file before the database rejects the insert. The view catches the exception, so this is not an established successful unsupported row or uncaught 500. Allowed extensions also receive no content-signature validation.

**Direction:** validate before storage and handle storage/DB failure cleanup. Serving arbitrary orphaned HTML is deployment-dependent: root `docker-compose.yml` mounts `nginx.conf`, whose media location is commented out; the alternative `nginx/nginx.conf:50-55` does expose media. Do not claim unauthenticated media exposure in every deployment.

### 37. Indirect document instructions lack a clear trust boundary

**Evidence:** `extractor/services/instructor_extractor.py:143-187,374-408`.

Document text is concatenated into the same user message as extraction instructions. No built-in requirement rejects instructions embedded in source documents, and shape validation is not factual validation. Configured system messages can help but are optional. No live prompt-injection success was tested, and this flow gives the model no arbitrary execution tools.

**Direction:** mark document text clearly as data rather than instructions (delimiters plus a system rule telling the model to ignore commands inside the document), keep output constrained to the schema, and leave contested answers to human review. Treat this as extraction-integrity risk rather than claiming demonstrated system compromise.

### 38. User deletion removes extraction evidence

**Evidence:** `extractor/models.py:108,346,375,400`.

Actor foreign keys use CASCADE. Deleting a processor/extractor/reviewer can remove processed-text records, jobs, results, and record-operation history. Deleting a reviewer can remove results even when someone else created the job.

**Direction:** agree how long extraction records must be kept, then stop account deletion from erasing them — block deletion of users who have review history (PROTECT), deactivate accounts instead of deleting them, or store the actor's name as plain text on the record so it remains after the account is gone.

### 39. UI embedding task ignores provider

**Evidence:** `extractor/tasks.py:43-47`; `extractor/views_semantic_search.py:124-129,215-248`; `extractor/management/commands/compute_lookup_embeddings.py:96-121`.

The browser-launched task unconditionally constructs SentenceTransformer, including for the offered OpenAI embedding configuration. Installing the missing library or fixing the legacy OpenAI call alone does not repair this path.

**Direction:** one provider adapter shared by query embeddings, background indexing, and the management command.

### 40. No-option fallback and stale/deleted lookup entries

**Evidence:** `extractor/services/instructor_extractor.py:220-242`; `extractor/tasks.py:120-129`; `extractor/management/commands/compute_lookup_embeddings.py:195-204`; `extractor/services/semantic_search.py:146-171`; `extractor/models.py:479-509`.

Nonempty documents with no semantic candidates do not receive the all-options fallback. Incremental computation skips any existing embedding without comparing text/version. Embedding object IDs are plain strings rather than lookup-row foreign keys, and search does not verify the referenced row still exists; removed records can therefore remain candidates until refresh.

**Direction:** show "search is unavailable" differently from "no option matched", record when the index was built and how much of the table it covers, and remove or rebuild embeddings for lookup rows that were deleted or renamed — rather than silently working from a stale index.

### 41. Discovery leaves stale fields selectable and offers internal relationship IDs

**Evidence:** `extractor/services/schema_discovery.py:57-100,216-301`; `extractor/views.py:204-218`.

Discovery only upserts metadata, leaving removed/renamed fields selectable. Ordinary internal relationship fields are mapped to their PK scalar type and can be offered for extraction without a binding strategy. Not every PK is an integer: Patient uses a string identifier.

**Direction:** when re-scanning, mark fields that no longer exist in the model as removed instead of leaving them selectable, and keep the identifiers operators explicitly configure separate from internal database relationship IDs. One-to-one fields are already covered by the ForeignKey subtype check.

### 42. Embedding credentials are plaintext and returned by an unrestricted edit view

**Evidence:** `extractor/models.py:449-454`; `extractor/views_semantic_search.py:139-174`; `templates/extractor/embedding_config_form.html:92-103`.

The key is an ordinary CharField and is rendered in the password input's HTML value. Password masking does not keep it out of the response; the endpoint only requires login. This is a direct access-control issue in addition to storage protection. Blank edits overwrite the key.

**Direction:** require permission to view or edit credentials, store the key encrypted, and never put its value into the HTML — accept a new key on submit and offer explicit "keep current" / "clear" behavior, so a blank form field cannot silently erase it.

### 43. Editable paths escape storage boundaries

**Evidence:** `extractor/admin.py:135-149`; `extractor/services/file_processor.py:251-258,274-281`; `extractor/views.py:873-888`.

A staff account allowed to edit ProcessedText can set an absolute or traversing path. Reads and deletion join it to MEDIA_ROOT without containment enforcement; absolute paths replace the base. The path can expose app-readable files or cause deletion outside processed-file storage with the additional required action privileges.

**Direction:** store processed-file paths as fixed identifiers that admins cannot edit, resolve them inside the media directory with traversal and symlink checks, and test that a staff account cannot point reads or deletes outside storage. No sensitive file read or deletion was performed for this audit.

### 44. Azure support depends on what the configured endpoint actually expects

**Evidence:** `extractor/services/instructor_extractor.py:37-61`; `extractor/views.py:614-615`.

The implementation has no traditional Azure deployment-path/API-version adapter. However, Azure-compatible OpenAI v1 endpoints may work with an ordinary OpenAI client and appropriate configuration. The earlier blanket claim that Azure always fails is withdrawn.

**Direction:** explicitly support/document endpoint variants and test the chosen protocol, rather than inferring it solely from a provider-name substring.

### 45. Expiry/refresh metadata is unused

**Evidence:** `extractor/models.py:34-49`; `extractor/views.py:456-472,512-521`; `extractor/services/instructor_extractor.py:26-84`.

Expiry and refresh-key fields are collected but never used — there is no expiry warning before calls and no refresh operation. Provider rejection is still possible; storing a refresh credential is not evidence of refresh support.

**Direction:** either implement real expiry and refresh handling, or remove/label these fields so they do not imply a capability that does not exist — and stop retaining secrets the app never uses.

### 46. Source aliases are not independently owned derived files

**Evidence:** `extractor/services/file_processor.py:144-150,274-281`; `extractor/models.py:62,107`; `chavi_client/settings.py:72`; `extractor/views.py:858-865`.

CSV ProcessedText points to the original upload. The current explicit cleanup caller is the upload-delete view, which intentionally deletes the source too; this is not a separate demonstrated accidental deletion in today's UI. A processed-only cleanup feature would be unsafe without alias ownership rules.

Django-cleanup covers uploaded FileFields, so bulk/cascade upload-file leakage is not established merely from bypassed overrides. Derived CharField paths remain outside its coverage.

**Direction:** keep a clear distinction between "this processed file is just the original upload" and "this processed file is a derived file the app owns", and reuse django-cleanup for deletion instead of duplicating it.

### 47. Generated choice values lose types and escaping

**Evidence:** `extractor/services/pydantic_builder.py:143-173`.

Choice generation wraps every value in double quotes. Synthetic integer choices become `["1", "2"]`, rejecting integer values, and embedded quotes/backslashes can alter or invalidate generated source. Current inspected clinical choices are mainly text choices; an existing integer-choice failure was not demonstrated. Numeric range strings such as `"0"` correctly produce numeric comparisons; that earlier allegation is withdrawn.

**Direction:** generate choices with their real types (numbers as numbers, not quoted strings) and insert values safely instead of pasting raw strings into source code. The real clinical numeric-bound omission is finding 54.

### 48. Unbounded index memory and repeated embedding computation

**Evidence:** `extractor/tasks.py:103-157`; `extractor/services/instructor_extractor.py:203-226`; `extractor/services/semantic_search.py:123-135,202-210`.

UI indexing accumulates a full table of vector objects before bulk insertion and evaluates a queryset without streaming. Extraction separately recomputes the same first-500-character query embedding for each lookup field, rather than caching it for that document/config version. Large tables/many fields increase memory, latency, or embedding API cost. No actual memory exhaustion was measured.

**Direction:** process embeddings in batches instead of loading a whole table into memory, compute the document's query embedding once per job instead of once per lookup field, and record counts, timing, and failures so cost is visible.

### 49. Review cannot clear values or validate typed corrections

**Evidence:** `extractor/views.py:1089-1101`; `templates/extractor/extraction_job_detail.html:165-200`.

Empty edits are ignored; arbitrary accuracy strings are saved without choice validation. Corrections remain untyped text without lookup/date/range validation. Each POST replaces reviewer/time, even if nothing changed, and no revision history is retained.

**Direction:** give reviewers explicit actions — accept, correct, clear, reject — validate corrections against the field's type and lookup, and keep a history of what changed. The additional undo bug is reproduced in finding 58.

### 50. Untrusted strings reach HTML execution sinks

**Evidence:** `templates/extractor/client_configuration_detail.html:237-293`; `extractor/views.py:676-683`; `templates/extractor/semantic_search_settings.html:302-334`.

Provider error text and configuration/task values are interpolated into `innerHTML`. A malicious endpoint can influence an error body rendered by a privileged user's connection test; shared configurations mean this is not necessarily self-XSS. Extracted clinical values themselves use escaped Django template output.

**Direction:** insert untrusted text with `textContent` (or build DOM elements) instead of `innerHTML`. Sink/source flow is code-confirmed; browser exploit execution was not performed.

### 51. Worksheet-name collision silently overwrites clinical input — new

**Evidence:** `extractor/services/file_processor.py:195-219`; `extractor/models.py:102-110`.

Distinct valid Excel sheet names `Lab A` and `Lab_A` both sanitize to `Lab_A`; the output name otherwise uses the same workbook stem/upload ID. The second `to_csv` overwrites the first, while both ProcessedText rows point at that path. The persisted model has no separate sheet-name/identity field; the returned sheet name is not saved.

**Reproduction:** the exact sanitizer produced identical names in an isolated check. The overwrite mechanism follows from the two writes to the same deterministic path.

**Direction/test:** make each output filename unique even when sheet names collide (e.g., include the original sheet name or a counter), and save which worksheet each processed file came from. Test two colliding valid names and assert distinct paths and contents.

### 52. Excel inference erases literal source information — new

**Evidence:** `extractor/services/file_processor.py:191-206`.

Default `pd.read_excel()` infers types and missing values. An in-memory workbook containing text `000123` and `000456` became numeric 123/456; literal `NA`, `NULL`, `None`, and `N/A` became empty CSV cells. The LLM never receives the original evidence. Formatting-dependent values, formulas without cached results, and merged cells need additional dedicated fidelity testing; they were not all reproduced here.

**Direction/test:** decide how cells should be converted to text so the literal source is preserved — keep leading zeros, distinguish a real "NA" string from an empty cell, and keep units/dates/formats where they carry meaning. Test with fixed example workbooks covering zero-prefixed identifiers and clinical negative/unknown text.

### 53. PDF conversion has no usable-text coverage gate — new

**Evidence:** `extractor/services/file_processor.py:95-117`; `extractor/services/instructor_extractor.py:528-536`.

A synthetic blank PDF converted successfully to `''`. The application writes that result and marks conversion completed without checking text length, pages represented, or missing image-only pages. No explicit OCR/fallback/low-text warning is configured in this path. This also matters for mixed documents whose text-bearing cover sheet hides missing scanned clinical pages.

**Direction/test:** validate usable text and page coverage, flag OCR-required/partial documents, and fail or require review rather than silently proceeding. Blank conversion was reproduced; general OCR accuracy and specific scanned PDFs were not tested.

### 54. Discovery drops the clinical validators even before runtime ignores them — new

**Evidence:** `extractor/services/schema_discovery.py:381-408`; `client_app/models.py:12-21,741-750`; `extractor/services/pydantic_builder.py:111-140`.

Discovery checks `field.min_value`/`max_value`, but Django's clinical fields express bounds through MinValueValidator/MaxValueValidator in `field.validators`. Only `has_validators=True` is recorded. A synthetic 0–100 DecimalField produced no bounds and no `max_digits`/`decimal_places`. Model-level date-pair validation (`client_app/models.py:25-50`) is also not represented. Consequently the preview is weaker than the database models even if finding 6 is fixed.

**Direction/test:** read the MinValueValidator/MaxValueValidator objects, decimal precision, and cross-field rules on the clinical models and turn them into real constraints in the generated schema. Test percentages outside 0–100, negative measures, precision limits, and inconsistent date pairs through discovery → schema → validation.

### 55. Source and configuration are mutable across a job — new

**Evidence:** `extractor/services/instructor_extractor.py:374-408,447-455`; `extractor/services/file_processor.py:91-107,201-213`; `extractor/views.py:1066-1074`; `extractor/models.py:333-348`.

Schema, prompt fields, and persistence fields are queried at different times, with an external LLM call in between. Editing a configuration during that interval can drop returned keys or change the lookup/table mapping used to save them. Jobs retain live configuration FKs, not a versioned snapshot. Reprocessing writes to the same file path; old job detail pages reread the current file contents, not the original input. Thus review evidence and reported configuration can change after extraction.

**Direction/test:** when a job starts, freeze what it ran against — the exact text version, the response-model definition, the prompt, and the candidate lists shown to the model — so later edits cannot change what the job appears to have used. Mock an edit between model completion and save, and test that the saved results still use the frozen version.

### 56. Partial workbook conversion is reported as complete — new

**Evidence:** `extractor/services/file_processor.py:226-234,51-58`; `extractor/views.py:830-841`.

Any successful sheet sets `success=True` even if other sheets failed. The processing status becomes completed, and the view displays `errors` only in the false-success branch. A mocked good sheet plus a failing sheet reproduced `success=True` with an error list; the failure is therefore hidden from the normal success feedback.

**Direction/test:** report how many sheets were expected versus processed and show the failed ones; do not mark the upload ready while sheets are missing.

### 57. Embedding refresh can destroy coverage and still report success — new

**Evidence:** `extractor/tasks.py:76-82,131-175`; `extractor/management/commands/compute_lookup_embeddings.py:145-151,206-246`.

Refresh deletes existing vectors before replacements are validated. Individual encoding exceptions are caught and skipped; completion reports success even if all attempts failed. An isolated real-task probe with mocked ORM/encoder confirmed deletion was requested and `mark_complete(success=True, total_processed=0)` was called after every encode raised. No actual vectors were deleted.

**Direction/test:** build the new set of embeddings separately, check its coverage and errors, and only then swap it in — keeping the old index if the new one fails. Report separately how many records were skipped, created, failed, and deleted.

### 58. Reverting to the original extraction does not undo a correction — new

**Evidence:** `extractor/views.py:1092-1095`; `templates/extractor/extraction_job_detail.html:151-174`.

The view compares incoming text against `extracted_data`, not the effective edited value. After a correction, submitting the original extracted text bypasses the branch and leaves `edited_data` and `data_edited` unchanged. The view still reports success and refreshes the verifier timestamp.

**Reproduction:** actual unwrapped view with a mocked result retained “Previous correction” after posting “Original”.

**Direction/test:** compare submissions against the value currently shown to the reviewer (the corrected value if there is one), and add an explicit "revert to extracted" action that clears the correction. Test original → corrected → original, corrected → blank/null, and unchanged submissions.

### 59. Failed and pending jobs are labeled extracted — new

**Evidence:** `extractor/views.py:925-944`; `templates/extractor/extraction_dashboard.html:112-115,147-150,190-193`; `extractor/views.py:989-992`.

The dashboard sets `has_extraction` using any job's existence, not successful status or the chosen response model/version. Failed/pending jobs get a green “Extracted” badge and count toward completion. Batch feedback also uses the success message channel even when every file failed, though its text includes the failure count.

**Direction/test:** base the badge on job status rather than existence — distinguishing never-started, in-progress, failed, completed, partially saved, and reviewed — and check which response model the job used. Test failed-only and pending-only histories.

### 60. Clinical meaning and source evidence are not part of what extraction is required to produce — new

**Evidence:** `extractor/services/instructor_extractor.py:166-182,209-244`; `extractor/services/schema_discovery.py:245-257,381-408`; `client_app/models.py:670-678,764-778`; `extractor/models.py:365-376`.

Runtime prompts list field names/types and candidate labels but omit Django help text, units, and most clinical meaning. For example, the clinical model defines greatest tumor dimension in centimeters; source text may say millimeters, while the generic rule asks for exact source text and the runtime value is numeric. There are no rules for negation, historical versus current findings, other people's diagnoses, or unknown versus absent.

Patient linkage exists indirectly through `job → processed_file → file_upload → patient`; the earlier suggestion that there is no patient relationship at all was incorrect. However, that chosen link is not checked against document identity, and results have no per-value page/sheet/span evidence. Workbook sheets are separate jobs without a merge/association strategy, which is a limitation when cross-sheet context is required.

**Status/direction:** these are clinical quality/verification gaps, not measured errors. Decide which units each field expects, how negation and history should be recorded, which patient each result belongs to, when the model should answer "not found", and what evidence (page, sheet, text span) should be stored with each value; test with sample documents that have known answers. This does not require the unrelated deidentification app.

### 61. Wizard backtracking and multiple tabs can discard configuration — new

**Evidence:** `extractor/views.py:87-95,117-144,168-199`; `extractor/models.py:288-290`.

All wizard tabs use the same session `response_model_id`. Starting a second model changes the target used by another open tab. Step 2 deletes all ResponseModelTable rows then recreates them, cascading their field selections even when the user only goes back and resubmits the same tables. Step 3 similarly replaces all selections. Transactions prevent partial writes but do not preserve user intent or prevent stale-tab updates.

**Direction/test:** tie each wizard run to the specific model being built (an ID in the URL instead of one shared session value), and on resubmission update only what actually changed instead of deleting and recreating all selections. Test back navigation with unchanged tables and two interleaved browser tabs.

### 62. Field encryption falls back to a committed key; sample env key is invalid — new (4th pass)

**Evidence:** `chavi_client/settings.py:724`; `sampleenv:20`; `extractor/models.py:33,36,371,374`; `docker-compose.yml`, `entrypoint.docker.sh`, `Dockerfile` (no `DJANGO_FIELD_ENCRYPTION_KEY`).

`FIELD_ENCRYPTION_KEY = os.environ.get('DJANGO_FIELD_ENCRYPTION_KEY', '<literal key>')`. The literal is a syntactically valid 32-byte Fernet key and is tracked in git. Any deployment that does not set the variable encrypts `ExtractionResult.extracted_data`/`edited_data`, `ClientConfiguration.model_api_key`, and the refresh key with a key readable by anyone with repository access — encryption at rest becomes nominal. This also weakens finding 33's premise that the per-field copy is protected.

`sampleenv` supplies a key that decodes to 21 bytes; `Fernet()` rejects it and `encrypted_model_fields` constructs its crypter at import time, so a deployment following the sample file fails at startup. The path of least resistance is to unset the variable and inherit the committed fallback. No tracked container configuration sets the variable; whether the untracked `.env.docker` does is unknown.

**Direction/test:** remove the fallback (fail fast if unset), ship a valid generation instruction rather than a literal sample key, treat the committed key as compromised and plan re-encryption/rotation for any data written under it. Add a startup check that the key is not the historical literal.

**Disposition (reviewer):** fix deferred — production will set `DJANGO_FIELD_ENCRYPTION_KEY` properly. Residual items worth a small fix regardless: `sampleenv`'s invalid key still crashes any deployment that follows it (import-time `Fernet()` failure), and anything already written under the fallback stays nominally encrypted. A cheap middle ground if reconsidered: keep the fallback but emit a startup warning when it is in use.

### 63. Deleting an upload or configuration deletes reviewed clinical results — new (4th pass)

**Evidence:** `extractor/models.py:64,106,337,338,369,370,182,148,248`; `extractor/views.py:850-870`; `extractor/services/file_processor.py:267-287`; `templates/extractor/file_upload_detail.html:172`.

Every link from `Patient → FileUpload → ProcessedText → ExtractionJob → ExtractionResult` is `CASCADE`, as are `ExtractionJob.response_model`, `ExtractionResult.database_field → DatabaseField → DatabaseTable → ContentType`, and `ResponseModel.client`. Consequences:

- `file_upload_delete` (and `delete_processed_files`, which deletes `ProcessedText` rows explicitly) removes every extraction job and every human-reviewed `ExtractionResult` derived from that file. The confirmation modal says only "this file and all its processed versions".
- Deleting a `ResponseModel`, `DatabaseTable`, or `DatabaseField` in admin deletes all results ever extracted with that configuration. `client_configuration_delete` guards against dependent response models in the view, but admin deletion of a `ClientConfiguration` cascades straight through.
- `manage.py remove_stale_contenttypes` after a `client_app` model rename would cascade `DatabaseTable → … → ExtractionResult`.

This is distinct from finding 38 (user-actor cascades). Reviewed results are the app's clinical output; configuration and source artefacts should not own them.

**Direction/test:** block deletion where reviewed results exist (Django `PROTECT`, or archive instead of deleting) on `ExtractionJob.processed_file`, `ExtractionJob.response_model`, and `ExtractionResult.database_field`; show the user which jobs and results a deletion would remove; test that deleting an upload with reviewed results is refused or archives rather than destroys.

**Disposition (reviewer):** extraction results are a staging area — reviewed values are pushed into the clinical tables and the staging rows are disposable, so cascade deletion is the intended behavior and no model-level `PROTECT` is planned at this stage. The fix is disclosure: the delete confirmation now enumerates dependent jobs/results (implemented, Group 1). Residual notes: admin deletion paths (`ResponseModel`/`DatabaseField`/`ClientConfiguration`) still delete staging results without any prompt, and `remove_stale_contenttypes` can cascade unexpectedly — acceptable while staging data is disposable; revisit if retention requirements change.

### 64. Wizard start silently reverts manual lookup corrections — new (4th pass)

**Evidence:** `extractor/services/schema_discovery.py:247-258`; `extractor/views.py:35-67`; `templates/extractor/wizard_start.html:175-216`; `extractor/management/commands/fix_lookup_value_fields.py`.

`_create_or_update_database_fields` uses `update_or_create` with `defaults` that include `lookup_table_value_field_name`, `lookup_table_pk_field_name`, `field_type`, and `field_validation`. Every wizard start triggers a full re-discovery from the browser, so any value corrected in admin or by `fix_lookup_value_fields` is overwritten by the regex guess again. For `LookupPerformanceStatus` this is a confirmed loop: discovery guesses `code` (third-pass check) → the fix command changes it to `label` → the next wizard start restores `code`. The fix command's own final message ("recompute embeddings") compounds the churn.

**What can be done about this — the options, in plain terms:** The core problem is that every time the setup wizard runs, it re-guesses which column of each lookup table should be shown to the AI, and writes that guess on top of whatever a person deliberately chose. Four ways to stop that:

- **Guess only once.** Let the scan fill in its guess the first time it sees a field, then never touch that setting again. The scan can still update facts about the database itself (the column's data type, whether it is a lookup), but the display-column choice is left alone once it exists. This is the least work. The cost: if the lookup table genuinely changes later, the stale guess stays until someone updates it by hand.
- **Remember who set it.** Keep a small marker on each field saying "guessed by the scan" or "chosen by a person." The scan may refresh its own guesses but must skip anything a person set. The cost: a little more bookkeeping, and you need a way to hand a field back to the scanner if that is ever wanted.
- **Store the guess and the decision separately.** The scan writes its guess into one place; the person's choice lives in another. The app always uses the person's choice when one exists and falls back to the guess otherwise. The scan can re-guess as often as it likes without ever erasing the decision. The cost: two places to check when something looks wrong, and every bit of code that reads the setting must know to prefer the person's choice.
- **Ask before changing anything.** When the wizard re-scans, show the operator a list of what is about to change — "this field's display column would switch back from your choice to the guess" — and let them accept or reject each change. The most transparent option, but the most work to build, and it adds a manual step to every wizard run.

Any of the four breaks the loop. The first is the least effort, the second and third are safest where manual corrections matter, and the fourth gives the most visibility. Whichever is chosen, the way to verify it is the same: change a field's display column by hand (for example, from `code` to `label`), run the wizard again, and check that the field is still set to `label` — the person's value — rather than reset to the scan's guess.

### 65. Response-model names become unsanitized tool/function names — new (4th pass)

**Evidence:** `extractor/services/instructor_extractor.py:127-130,384-389`; `extractor/models.py:249`.

The runtime model is named `f'{response_model.name.replace(" ", "")}Model'`; Instructor's tools mode uses the class `__name__` as the OpenAI function name. A name such as `Dx (v2)/Path` yields `Dx(v2)/PathModel`, which fails OpenAI's documented `^[a-zA-Z0-9_-]{1,64}$` constraint; `ResponseModel.name` allows 512 characters, so long names fail on length alone. Verified: Instructor's `openai_schema` passes the name through unchanged. JSON mode (Ollama) is unaffected; other OpenAI-compatible servers may or may not enforce the pattern.

**Direction/test:** generate the tool/function name separately from the display name — strip invalid characters and cap it at 64 characters — rather than passing the raw name through; test with punctuation, unicode, and >64-char names against the tools-mode payload builder.

### 66. Prompt instruction contradicts the typed runtime schema — new (4th pass)

**Evidence:** `extractor/services/instructor_extractor.py:108-124,170-175`; Pydantic coercion check.

Rule 5 of the prompt says "For regular fields without options, extract the exact text from the document," while the runtime model types boolean/integer/float fields. Pydantic (lax mode) coerces `"yes"`/`"12"` but rejects `"present"` (`bool_parsing`) and `"12 per 10 HPF"` (`int_parsing`). Instructor then retries up to `max_retries=3` times, each re-sending the full document, before the job fails — with `tokens_used` null, the cost is invisible (finding 20). Alternatively a model may silently "fix" the value (e.g., choose `true` for "focally present"), which is a clinical-meaning decision made without evidence. Date/time fields are typed `str` with no format instruction, so the same document can yield `12/03/2024`, `March 12, 2024`, or `2024-03-12`.

**Direction/test:** either add per-type instructions to the prompt ("return only the number", "answer true or false", "use YYYY-MM-DD") including unit expectations from the field's help text, or have the model return both the quoted source text and a cleaned value; test bool/int/date fields against realistic pathology phrasing.

### 67. One similarity threshold serves two different comparison types — new (4th pass)

**Evidence:** `extractor/services/semantic_search.py:157-160,180-211`; `extractor/models.py:459-462`.

`similarity_threshold` (default 0.7) filters both (a) extracted-label ↔ lookup-label matching in `map_label_to_code` and (b) 500-character document snippet ↔ lookup-label matching in `get_filtered_lookup_options`. Cosine similarity between a paragraph of clinical prose and a two-word label under general sentence-embedding models is typically far below what two short labels achieve. With a threshold tuned for (a), (b) will frequently return nothing — and finding 40 shows there is no all-options fallback in that case. Even with embeddings installed and indexed, the "Valid Options" feature may therefore be empty most of the time. Not measured (no embedding model available); presented as a design defect we consider very likely rather than a proven failure rate.

**Direction/test:** use different settings for the two jobs — a looser cutoff for collecting candidate options and a stricter one for matching the model's answer — or drop the hard cutoff for candidates and just take the best few; measure how often the correct option appears in the shortlist on synthetic documents before enabling the MUST-pick instruction.

### 68. Ollama truncates over-length prompts silently — new (4th pass, conditional)

**Evidence:** `extractor/services/instructor_extractor.py:43-51,365-369,384-389`; Ollama OpenAI-compatibility behavior (documented upstream; not exercised here).

Finding 10 assumed over-length input produces an API error. For Ollama the documented behavior is different: input beyond the model's `num_ctx` is truncated server-side with only a server-log notice, and the OpenAI-compatible `/v1/chat/completions` endpoint does not accept the `options.num_ctx` override. Because the document is appended after the schema and rules, the *end of the document* (often the diagnosis/conclusion in pathology reports) is what gets dropped, and the job completes normally. This applies to the "Local (Ollama)" provider the UI explicitly offers.

**Direction/test:** count the prompt size and compare it with the model's configured context limit before sending; for Ollama use the native API or set `num_ctx` in the Modelfile; test that an oversized document fails loudly instead of completing with its tail dropped.

### 69. Identifiers leak through filenames, patient lists, and orphan configurations — new (4th pass)

**Evidence:** `extractor/services/file_processor.py:53,56,91-92,119,144,160,192,224`; `extractor/models.py:96-97,122-125`; `extractor/views.py:87-95,328,794-795,947`.

- Upload filenames (commonly `Surname_Pathology.pdf`) are logged at INFO on every processing step, embedded in derived artefact paths (`processed/pdf/Surname_Pathology_12.md`), and used as `__str__` for `FileUpload`/`ProcessedText` in admin and lists. Finding 3 covers document *content* in logs; filenames are a separate, always-on channel.
- `file_upload_create` renders `Patient.objects.all()` into the dropdown for anyone with `add_fileupload`, disclosing the full patient-ID roster regardless of finding 32's policy outcome.
- `wizard_step1` creates the `ResponseModel` row on POST before any tables/fields exist; abandoned wizards leave orphan models that appear in `response_model_list` and the extraction dashboard dropdown (`ResponseModel.objects.all()`), where selecting one triggers findings 14/17.

**Direction/test:** store uploads under generated names and keep the original filename as a permission-controlled display field; make patient selection searchable or scoped instead of listing every patient; create the `ResponseModel` row only when the wizard finishes, or hide incomplete models from the selection lists.

### 70. Operational limits — new (4th pass)

**Evidence:** `gunicorn.conf.py:9-11`; `extractor/services/semantic_search.py:20-46`; `extractor/models.py:516-521`; `extractor/views.py:643`; `extractor/views_semantic_search.py:264-265`.

- Gunicorn runs `cpu_count()*2+1` worker processes; `SemanticSearchService` lazily loads a `SentenceTransformer` per process on first use (not thread-safe: two threads can load concurrently). First-request latency and N copies of the model in memory are unbudgeted.
- `LookupEmbedding` has no vector index (HNSW/IVFFlat); every similarity query is a sequential scan of all embeddings for the config.
- The connection-test timeout heuristic treats only `localhost`/`127.0.0.1` as local; a LAN-hosted Ollama gets the 30 s remote timeout and reports false failures for large models. Under the reviewer-confirmed LAN deployment, a LAN-hosted LLM is the likely topology, so this is a probable operational bug rather than an edge case.
- `get_embedding_progress` is login-only and accepts any task UUID.

### 71. Documentation promises behavior the code does not deliver — new (4th pass)

**Evidence:** `extractor/FILE_UPLOAD_README.md:181` ("File type validation"); `EXTRACTION_UI_GUIDE.md:38` ("Validates selected files and response model"), `:230` ("Encrypted storage for sensitive data"); `extractor/PROGRESS.md:184` ("✅ Field validators for choices and ranges").

Each claim is contradicted by a verified finding: upload validators never run (36); extraction performs no readiness validation (17); encryption may use the committed key and the parsed response is plaintext (62, 33); range bounds are never discovered (54). Operators reading these documents will assume controls exist.

**Direction:** per reviewer, the promised controls are to be implemented, not just documented away — file-type enforcement (36), extraction-readiness validation (17), range/validator discovery (54), and genuine encrypted storage (33; note the deferred key handling in 62 makes this rest on production env discipline). Update the docs as each control lands; until then a "known limitations" section prevents operators assuming the controls exist.

## 5. Recommended remediation order (future work only)

1. **Stop destroying or corrupting evidence first:** show which jobs and results a deletion would remove and protect those links outside the UI too (63, 38); save results and job status in one step so a job cannot be "complete" with half its results (34); add a real "not reviewed" state (8); let reviewers undo corrections properly (49, 58); freeze the input each job ran against (55). (62 deferred: production will set its own key; fix `sampleenv` when convenient.)
2. **Fix input fidelity before tuning the LLM:** sheet names that collapse to the same output file and spreadsheet type inference that alters values (51, 52), workbooks reported complete when a sheet failed (56), conversions that produce no usable text without a warning or OCR fallback (9, 53), and prompts that silently exceed the model's context size for Ollama (10, 68).
3. **Make the real extraction match what was configured:** one schema for preview and runtime (6, 17, 21), prompt instructions that fit each field type (66), a safe generated tool name (65), numeric limits carried through from the clinical models (54), and rules for units, evidence, and which patient a record belongs to (60). Plan how repeated records are stored rather than adding a single-value uniqueness constraint blindly.
4. **Stop lookups silently changing meaning:** protect manual display-field corrections from re-scans (64); keep CTCAE term + grade in labels and flag ambiguous matches (19, 22); use different similarity cutoffs for collecting candidates versus matching the answer (67); make sure the right option actually reaches the shortlist (4, 5, 35); fix the embedding code paths (2, 39); and rebuild indexes safely instead of deleting first (13, 40, 57).
5. **Close the concrete exposure paths:** stop logging documents, credentials, and filenames (3, 69); restrict who can see or edit embedding keys (16, 42); decide whether the plain parsed-response copy should exist (33); enforce upload type checks and stored-path boundaries (36, 43); and replace `innerHTML` with safe text insertion for untrusted strings (50). Agree which provider endpoints and access rules apply on this LAN before enforcing them (31, 32); keep intentionally supported local endpoints working. No integration with the deidentification app is proposed.
6. **Make operations and documentation match reality:** one real connection test per provider (1, 11, 44, 70), extraction and embedding as resumable background jobs with limits (10, 12, 18, 20, 48, 70), a dashboard that shows true job status (59), a wizard that neither loses work nor leaves empty models selectable (14, 61, 69), file cleanup that actually removes the right files (15, 46), and documentation that matches the code (71).

## 6. Verification limits and follow-up acceptance criteria

- This is a code-and-isolated-behavior audit, not a live security assessment or clinical accuracy certification. No LLM calls, PHI inspection, provider credentials, active deployment network probes, or database migrations/writes were used in the third or fourth pass. The committed encryption key was inspected only for length/validity and never printed or used.
- Fourth-pass items checked and found clean: no Pydantic namespace collisions among 213 `client_app` field names; no `media/`, `logs/`, `db.sqlite3`, or `.env*` files tracked in git; `.gitignore` covers them; extractor templates escape extracted values.
- Ollama truncation (68) and the threshold-reuse effect (67) are inferred from documented upstream behavior and embedding geometry respectively; neither was measured here and both should be confirmed empirically before fixes are scoped.
- The earlier successful `manage.py check` remains only a framework sanity check. User-reported migrations were up to date; no new database-state inference has been made.
- `extractor/tests.py` is a stub; no comprehensive extraction regression suite was identified. The probes above are session checks, not committed regression tests.
- Before fixes are accepted, convert the listed reproductions into automated tests using an isolated test database and fake provider/storage adapters. Add negative tests for wrong schema shape, ambiguous grades, empty/partial input, failure during persistence/refresh, stale config changes, cross-resource permissions, and source-value fidelity.
- A representative clinical evaluation must separately measure correct extraction, omissions, wrong codes, units, negation and timing, repeated records, and the model's ability to answer "not found". A valid JSON/Pydantic response alone is not a passing accuracy criterion.
- Confirm the intended role/site access policy, approved remote/local provider destinations, how long processed files and logs are kept, and the patient-link verification workflow before treating conditional findings as deployment violations.

*Only this report was revised. Application code, dependencies, configuration, and data were not changed.*

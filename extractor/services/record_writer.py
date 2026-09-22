"""
Write-back: create client_app records from extracted staging data.

Manual, per-record, create-only. Reuses schema-discovery metadata:
`DatabaseField.relation_content_type` links internal FK fields to their
target tables so parent chains (e.g. Pathology → Diagnosis → Patient) are
resolved before a row is created.
"""

import json
from decimal import Decimal
from datetime import datetime, date, time, timedelta

from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from logging import getLogger

from extractor.models import (
    DatabaseField, ExtractionResult, RecordCreation, RecordCreationField,
    ExtractedRecord,
)

log = getLogger(__name__)


class RecordWriteError(Exception):
    """User-facing write-back failure (missing parent, bad value, etc)."""


# Curated identity keys per client_app model — ordered key-sets; the first
# set whose fields are all non-null in the extracted values is used for the
# duplicate check. Parent scope (same patient / same created parent) is
# implicit. Stored per-table on DatabaseTable.match_fields; these are defaults.
DEFAULT_MATCH_FIELDS = {
    'diagnosis': [['diagnosis', 'diagnosis_date'],
                  ['cancer_system', 'cancer_site', 'cancer_side']],
    'outcome': [['outcome_type', 'date_outcome_assessed']],
    'lesion': [['date_lesion_assessed', 'lesion_site', 'lesion_laterality'],
               ['date_lesion_assessed', 'lesion_type']],
    'lesionresponse': [['lesion_response_date', 'lesion_response']],
    'symptom': [['symptom', 'date_onset'],
                ['symptom', 'date_symptom_assessment']],
    'germlinegenomicalterations': [['date_test', 'cosmic_gene_name', 'protein_modification'],
                                   ['date_test', 'cosmic_gene_name', 'reference_sequence']],
    'pathology': [['date_pathology', 'specimen_type', 'tumor_site'],
                  ['date_pathology', 'histological_type']],
    'immunohistochemistry': [['date_ihc', 'protein_name']],
    'cytogenetics': [['date_cytogenetics', 'gene', 'cytogenetic_abnormality'],
                     ['date_cytogenetics', 'gene']],
    'somaticgenomicalterations': [['date_test', 'cosmic_gene_name', 'protein_modification'],
                                  ['date_test', 'cosmic_gene_name', 'variant_type']],
    'geneexpressiondata': [['date_test', 'gene']],
    'epigeneticdata': [['date_test', 'gene', 'epigenetic_abnormality_type']],
    'othertreatment': [['treatment', 'treatment_start_date']],
    'radiotherapy': [['radiotherapy_start_date', 'radiotherapy_course_type'],
                     ['radiotherapy_start_date', 'radiotherapy_modality']],
    'radiotherapyvolume': [['volume_name', 'volume_type'],
                           ['volume_radiotherapy_start_date', 'volume_type']],
    'radiotherapydosevolumedata': [['volume_name', 'volume_type', 'radiation_dose_units']],
    'surgery': [['surgery_date', 'surgery_side'],
                ['surgery_date', 'surgery_intent']],
    'concomitantmedications': [['medication_name', 'date_medication_start_date']],
    'systemictherapy': [['systemic_therapy_regimen', 'systemic_therapy_start_date'],
                        ['systemic_therapy_type', 'systemic_therapy_start_date']],
    'systemictherapyschedule': [['systemic_therapy_agent', 'systemic_therapy_agent_start_date']],
    'adverseeffects': [['ctcae_grade_lookup', 'adverse_effect_start_date']],
    'patientreportedoutcome': [['pro_assessment_date', 'pro_instrument', 'pro_question_id'],
                               ['pro_assessment_date', 'pro_question']],
    'patientoutcome': [['patient_status', 'date_of_death'],
                       ['patient_status', 'last_date_of_follow_up']],
    'comorbidity': [['comorbidity_type', 'date_of_comorbidity_diagnosis'],
                    ['comorbidity_type', 'date_of_comorbidity_assessment']],
    'stageinformation': [['staging_system', 'stage_type', 't_stage', 'n_stage', 'm_stage'],
                         ['staging_system', 'stage_type']],
    'laboratoryresults': [['laboratory_test', 'result_date']],
    'patientassessment': [['date_assessment']],
}


def get_match_fields(db_table):
    """Stored per-table key-sets, else the curated defaults for the model."""
    if db_table.match_fields:
        return db_table.match_fields
    model_name = db_table.clientapp_content_type.model
    return DEFAULT_MATCH_FIELDS.get(model_name, [])


def effective_result_value(result):
    """Return the reviewed value without losing an explicit empty edit."""
    if result.data_edited:
        return result.edited_data
    if result.result_state in ('not_found', 'unresolved'):
        return None
    return result.extracted_data


def _raw_value_map(extracted_record):
    """field_id -> effective raw value (edited beats extracted); not_found/unresolved -> None."""
    results = ExtractionResult.objects.filter(
        record=extracted_record
    ).select_related('database_field')
    return {r.database_field_id: effective_result_value(r) for r in results}


def find_duplicate_candidates(db_table, extracted_record):
    """
    Existing client_app rows matching the extracted record's identity keys,
    scoped to the same patient via the table's patient_path.

    Returns a list of {'pk', 'matched_on': [field names], 'row': obj}.
    Empty list = no candidate found (or no usable key-set).
    """
    model_class = db_table.clientapp_content_type.model_class()
    patient = extracted_record.extraction_job.processed_file.file_upload.patient_id
    if model_class is None or patient is None:
        return []

    patient_path = (db_table.clientapp_table_fk_fields or {}).get('patient_path')
    if not patient_path:
        return []
    scope = {'__'.join(step['field'] for step in patient_path): patient}
    qs = model_class.objects.filter(**scope)

    key_sets = get_match_fields(db_table)
    if not key_sets:
        return []

    field_map = _raw_value_map(extracted_record)
    db_fields = {
        f.clientapp_field_name: f
        for f in db_table.databasefield_set.filter(is_active=True)
    }

    def field_value(name):
        db_field = db_fields.get(name)
        if db_field is None:
            return None
        raw = field_map.get(db_field.id)
        if raw is None:
            return None
        if db_field.lookup_field:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, json.JSONDecodeError):
                return None
            code = parsed.get('code') if isinstance(parsed, dict) else None
            return (f'{name}_id', code) if code not in (None, '') else (f'{name}_id', None)
        try:
            return (name, _coerce(raw, db_field.field_type))
        except (ValueError, TypeError):
            return (name, None)

    for key_set in key_sets:
        filters = {}
        usable = True
        for name in key_set:
            fv = field_value(name)
            if fv is None or fv[1] is None:
                usable = False
                break
            filters[fv[0]] = fv[1]
        if not usable:
            continue
        matches = list(qs.filter(**filters)[:10])
        if matches:
            return [{'pk': r.pk, 'row': r, 'matched_on': key_set} for r in matches]
    return []


def _coerce(value, field_type):
    """Coerce an extracted string value into the target model field type."""
    if value is None:
        return None
    if field_type == 'int':
        return int(float(str(value).strip()))
    if field_type == 'float':
        return float(str(value).strip())
    if field_type == 'decimal':
        return Decimal(str(value).strip())
    if field_type == 'bool':
        v = str(value).strip().lower()
        if v in ('true', '1', 'yes'):
            return True
        if v in ('false', '0', 'no'):
            return False
        raise ValueError(f"cannot coerce {value!r} to bool")
    if field_type == 'date':
        return date.fromisoformat(str(value).strip()[:10])
    if field_type == 'datetime':
        return datetime.fromisoformat(str(value).strip())
    if field_type == 'time':
        return time.fromisoformat(str(value).strip())
    if field_type == 'timedelta':
        return timedelta(seconds=int(float(str(value).strip())))
    return str(value)


def _effective_map(extracted_record):
    """(field_id -> effective raw value, field_id -> ExtractionResult)."""
    results = {
        r.database_field_id: r
        for r in ExtractionResult.objects.filter(record=extracted_record)
                                          .select_related('database_field')
    }
    return _raw_value_map(extracted_record), results


def _resolve_parent_instance(extracted_record):
    """
    pk of the client_app row an extracted record maps to — its successful
    RecordCreation when created, else a unique dedup match against existing
    patient-scoped rows. Raises RecordWriteError when neither resolves.
    """
    creation = RecordCreation.objects.filter(
        extracted_record=extracted_record,
        operation='create',
        record_created=True,
    ).first()
    if creation:
        return creation.created_record_pk

    candidates = find_duplicate_candidates(
        extracted_record.database_table, extracted_record)
    model_name = extracted_record.database_table.clientapp_content_type.model
    if len(candidates) == 1:
        return str(candidates[0]['pk'])
    if len(candidates) > 1:
        raise RecordWriteError(
            f"Several existing '{model_name}' rows match extracted record "
            f"#{extracted_record.id} — resolve the duplicate first.")
    raise RecordWriteError(
        f"Create the parent '{model_name}' record first "
        f"(extracted record #{extracted_record.id}).")


def resolve_record_pk(extracted_record):
    """
    pk of the client_app row an extracted record maps to (created row or a
    unique dedup match), else None. Display-facing variant of
    _resolve_parent_instance.
    """
    try:
        return _resolve_parent_instance(extracted_record)
    except RecordWriteError:
        return None


def _resolve_parent_fks(extracted_record):
    """
    Map internal FK field names to concrete pk values.

    - patient FKs resolve to the job's patient.
    - FKs matching this record's parent_record (nested extraction) resolve to
      that parent's created row, else to a unique existing match.
    - FKs without a parent_record fall back to the RecordCreation created for
      the same job+table. Exactly one must exist, else a user-facing error
      explains what to create first.
    """
    job = extracted_record.extraction_job
    patient = job.processed_file.file_upload.patient_id
    fks = {}

    rel_fields = DatabaseField.objects.filter(
        clientapp_database_table=extracted_record.database_table,
        field_validation__is_relationship=True,
        relation_content_type__isnull=False,
    ).select_related('relation_content_type')

    for f in rel_fields:
        target_model = f.relation_content_type.model_class()
        if target_model is None:
            continue
        name = f.clientapp_field_name

        if target_model._meta.model_name == 'patient' and target_model._meta.app_label == 'client_app':
            if patient is None:
                raise RecordWriteError(
                    f"Cannot create {extracted_record.database_table.clientapp_content_type.model}: "
                    f"the source file is not linked to a patient.")
            fks[f'{name}_id'] = patient.pk
            continue

        parent_rec = extracted_record.parent_record
        if (parent_rec is not None and
                parent_rec.database_table.clientapp_content_type_id == f.relation_content_type_id):
            fks[f'{name}_id'] = _resolve_parent_instance(parent_rec)
            continue

        creations = RecordCreation.objects.filter(
            extraction_job=job,
            database_table__clientapp_content_type=f.relation_content_type,
            operation='create',
            record_created=True,
        )
        if creations.count() == 0:
            raise RecordWriteError(
                f"Create the parent record first: field '{name}' needs a "
                f"'{f.relation_content_type.model}' record from this job.")
        if creations.count() > 1:
            raise RecordWriteError(
                f"Multiple '{f.relation_content_type.model}' records were created "
                f"for this job — write-back can't choose a parent for '{name}'.")
        fks[f'{name}_id'] = creations.first().created_record_pk

    return fks


def create_record_for_extracted_record(extracted_record, user):
    """
    Legacy entry point retained for compatibility. Extraction write-back must
    go through an approved ExtractionReviewBatch.
    """
    raise RecordWriteError(
        "Direct record creation is no longer available; use the job review and approval workflow.")


def _legacy_create_record_for_extracted_record(extracted_record, user):
    existing = RecordCreation.objects.filter(
        extracted_record=extracted_record, operation='create', record_created=True
    ).first()
    if existing:
        return existing, False

    db_table = extracted_record.database_table
    model_class = db_table.clientapp_content_type.model_class()
    if model_class is None:
        raise RecordWriteError("Cannot resolve the target client_app model.")

    field_map, results = _effective_map(extracted_record)
    values = _resolve_parent_fks(extracted_record)

    errors = []
    for db_field in db_table.databasefield_set.filter(is_active=True).select_related('lookup_content_type'):
        name = db_field.clientapp_field_name
        if not db_field.is_extractable():
            # relationship FKs resolve via _resolve_parent_fks; auto PKs use
            # the model's default (uuid4) — neither comes from extracted text
            continue
        if name in ('id', 'created_at', 'updated_at'):
            continue

        raw = field_map.get(db_field.id)
        result_obj = results.get(db_field.id) if isinstance(results, dict) else None

        # Required-ness comes from the real model field, not the validation
        # dict — fields with defaults (e.g. auto UUIDs) are never required.
        try:
            model_field = model_class._meta.get_field(name)
            required = not model_field.null and not model_field.blank \
                and not model_field.has_default()
        except Exception:
            required = False

        if db_field.lookup_field:
            if raw is None:
                if required:
                    errors.append(f"'{name}' is required but the lookup was unresolved/not found")
                continue
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, json.JSONDecodeError):
                parsed = None
            code = parsed.get('code') if isinstance(parsed, dict) else None
            if code in (None, ''):
                if required:
                    errors.append(f"'{name}' is required but has no lookup code")
                continue
            values[f'{name}_id'] = code
            continue

        if raw is None:
            if required:
                errors.append(f"'{name}' is required but was not extracted")
            continue

        try:
            values[name] = _coerce(raw, db_field.field_type)
        except (ValueError, TypeError) as e:
            errors.append(f"'{name}': {e}")

    if errors:
        raise RecordWriteError("; ".join(errors))

    with transaction.atomic():
        instance = model_class(**values)
        try:
            instance.full_clean()
        except DjangoValidationError as e:
            raise RecordWriteError(
                f"Model validation failed: {e.message_dict if hasattr(e, 'message_dict') else e}")
        instance.save()

        creation = RecordCreation.objects.create(
            extraction_job=extracted_record.extraction_job,
            database_table=db_table,
            extracted_record=extracted_record,
            created_record_pk=str(instance.pk),
            operation='create',
            record_created=True,
            record_created_by=user,
        )
        for db_field_id, res in (results.items() if isinstance(results, dict) else []):
            if db_field_id in field_map and field_map[db_field_id] is not None:
                RecordCreationField.objects.create(
                    record_creation=creation, extraction_result=res)

    log.info(
        f"Created {model_class.__name__} #{instance.pk} from extracted record "
        f"{extracted_record.id} by {user}")
    return creation, True

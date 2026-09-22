import hashlib
import json
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core import signing
from django.db import models, transaction
from django.db.models import Count
from django.utils import timezone

from extractor.models import (
    DataAccuracyChoices, DatabaseField, ExtractionJob, ExtractionResult,
    ExtractionReviewBatch, RecordCreation, RecordCreationField,
    RecordOperationChoices, ResultSourceChoices, ReviewChangeChoices,
    ReviewStatusChoices,
)
from extractor.services.patient_data import _grid_columns, _cell_value, _format_existing_cell
from extractor.services.record_writer import find_duplicate_candidates
from extractor.services.semantic_search import build_lookup_label


REVIEW_SCHEMA_VERSION = 1
REVIEW_EXPIRY = timedelta(hours=1)
OPTION_PAGE_SIZE = 25
SYSTEM_FIELD_NAMES = {'id', 'created_at', 'updated_at'}
REVIEWABLE_MODEL_NAMES = {
    'diagnosis', 'outcome', 'lesion', 'lesionresponse', 'symptom',
    'germlinegenomicalterations', 'pathology', 'immunohistochemistry',
    'cytogenetics', 'somaticgenomicalterations', 'geneexpressiondata',
    'epigeneticdata', 'othertreatment', 'radiotherapy', 'radiotherapyvolume',
    'radiotherapydosevolumedata', 'surgery', 'concomitantmedications',
    'systemictherapy', 'systemictherapyschedule', 'adverseeffects',
    'patientreportedoutcome', 'patientoutcome', 'comorbidity',
    'stageinformation', 'laboratoryresults', 'patientassessment',
}


class ReviewValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('The extraction review contains errors.')


class ReviewConflictError(Exception):
    pass


def _json_dumps(value):
    return json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True, separators=(',', ':'))


def _json_loads(value):
    return json.loads(value or '{}')


def _model_for_table(table):
    return table.clientapp_content_type.model_class()


def _model_name(table):
    return table.clientapp_content_type.model


def _assert_supported_table(table):
    if _model_name(table) not in REVIEWABLE_MODEL_NAMES:
        raise ReviewValidationError({'__all__': [f"Saving {_model_name(table)} records is not supported by extraction review."]})


def _extractable_fields(record):
    return [f for f in record.database_table.databasefield_set.filter(
        is_active=True).select_related('lookup_content_type') if f.is_extractable()]


def _relationship_fields(record):
    return list(record.database_table.databasefield_set.filter(
        is_active=True,
        field_validation__is_relationship=True,
        relation_content_type__isnull=False,
    ).select_related('relation_content_type'))


def _related_instance(model_field, value):
    if value in (None, ''):
        return None
    related = model_field.related_model
    pk = related._meta.pk.to_python(value)
    return related.objects.get(pk=pk)


def canonical_value(model_field, value):
    """Return the model field's typed value without losing decimal precision."""
    if isinstance(model_field, models.ForeignKey):
        if value in (None, ''):
            return None
        if not isinstance(value, model_field.related_model):
            value = _related_instance(model_field, value)
        return value.pk
    if value in (None, ''):
        return None if model_field.null else value
    return model_field.to_python(value)


def classify_review(original, reviewed, *, source_state, disposition):
    """Classify a reviewed value against the value the LLM originally gave."""
    original_missing = original in (None, '')
    reviewed_missing = reviewed in (None, '')
    if disposition == 'preserve':
        return {'data_accuracy': None, 'review_change': None, 'applied': False}
    if source_state == 'unresolved' and reviewed_missing:
        change = ReviewChangeChoices.OMITTED_UNRESOLVED
    elif disposition == 'clear' and not original_missing:
        change = ReviewChangeChoices.CLEARED
    elif source_state == 'unresolved' and not reviewed_missing:
        change = ReviewChangeChoices.EDITED
    elif original_missing and not reviewed_missing:
        change = ReviewChangeChoices.FILLED_MISSING
    elif not original_missing and original != reviewed:
        change = ReviewChangeChoices.EDITED
    elif not original_missing and reviewed_missing and disposition == 'clear':
        change = ReviewChangeChoices.CLEARED
    else:
        change = ReviewChangeChoices.ACCEPTED
    inaccurate = change in (ReviewChangeChoices.EDITED, ReviewChangeChoices.FILLED_MISSING,
                            ReviewChangeChoices.CLEARED, ReviewChangeChoices.OMITTED_UNRESOLVED)
    return {
        'data_accuracy': DataAccuracyChoices.INACCURATE if inaccurate else DataAccuracyChoices.ACCURATE,
        'review_change': change,
        'applied': disposition != 'preserve',
    }


def _to_jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, (uuid.UUID,)):
        return str(value)
    return value


def _snapshot_instance(instance):
    out = {}
    for field in instance._meta.fields:
        out[field.name] = _to_jsonable(getattr(instance, field.attname))
    return out


def _fingerprint(job):
    results = ExtractionResult.objects.filter(extraction_job=job).select_related(
        'database_field', 'record').order_by('id')
    items = []
    for result in results:
        items.append({
            'id': result.id,
            'record': result.record_id,
            'field': result.database_field_id,
            'state': result.result_state,
            'extracted': result.extracted_data,
            'edited': result.edited_data if result.data_edited else None,
            'edited_flag': result.data_edited,
            'accuracy': result.data_accuracy,
            'review_change': result.review_change,
            'source_kind': result.source_kind,
        })
    records = list(job.extracted_records.order_by('id').values(
        'id', 'database_table_id', 'parent_record_id', 'record_index'))
    fields = list(DatabaseField.objects.filter(
        clientapp_database_table__extractedrecord__extraction_job=job,
        is_active=True,
    ).order_by('id').values(
        'id', 'clientapp_database_table_id', 'clientapp_field_name', 'field_type',
        'lookup_field', 'lookup_content_type_id', 'lookup_table_value_field_name',
        'lookup_table_pk_field_name', 'field_validation', 'relation_content_type_id',
    ))
    patient = getattr(job.processed_file.file_upload, 'patient_id_id', None)
    return hashlib.sha256(_json_dumps({
        'records': records, 'results': items, 'fields': fields,
        'patient': str(patient), 'revision': job.review_revision,
    }).encode()).hexdigest()


def _source_token(job):
    return signing.dumps({'job': job.id, 'fingerprint': _fingerprint(job),
                          'version': REVIEW_SCHEMA_VERSION})


def _check_source_token(job, token):
    try:
        data = signing.loads(token)
    except signing.BadSignature:
        raise ReviewValidationError({'__all__': ['The review form is no longer valid. Refresh it and enter the values again.']})
    if data.get('job') != job.id or data.get('version') != REVIEW_SCHEMA_VERSION:
        raise ReviewValidationError({'__all__': ['This review form belongs to a different extraction job.']})
    if data.get('fingerprint') != _fingerprint(job):
        raise ReviewConflictError('The extraction results or related rules changed after this review was opened.')


def _has_model_perm(user, table, action):
    model = _model_name(table)
    return user.has_perm(f'client_app.{action}_{model}')


def _check_permissions(job, user, preview=False):
    if not user.has_perm('extractor.view_extractionjob') or not user.has_perm('extractor.view_extractionresult'):
        raise PermissionDenied
    if not user.has_perm('extractor.change_extractionresult'):
        raise PermissionDenied
    if not preview and not user.has_perm('extractor.add_recordcreation'):
        raise PermissionDenied


def patient_scoped_queryset(database_table, patient):
    _assert_supported_table(database_table)
    model = _model_for_table(database_table)
    path = (database_table.clientapp_table_fk_fields or {}).get('patient_path')
    if model is None or patient is None or not path:
        raise ReviewValidationError({'__all__': ['This table cannot be matched to the job patient.']})
    lookup = '__'.join(step['field'] for step in path)
    return model.objects.filter(**{lookup: patient})


def _target_queryset(table, patient):
    return patient_scoped_queryset(table, patient)


def _target_instance(table, patient, pk, errors, label='record'):
    try:
        return _target_queryset(table, patient).get(pk=pk)
    except Exception:
        errors.setdefault('__all__', []).append(
            f"Selected {label} for {_model_name(table)} does not exist for this patient.")
        return None


def _field_model_field(table, db_field):
    try:
        return _model_for_table(table)._meta.get_field(db_field.clientapp_field_name)
    except Exception:
        return None


def _parse_lookup_raw(raw):
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        parsed = None
    return parsed if isinstance(parsed, dict) else None


def _result_payload(result):
    if result is None:
        return {'state': 'not_found', 'extracted': None, 'edited': None,
                'edited_flag': False, 'lookup': None, 'has_result': False}
    return {
        'state': result.result_state,
        'extracted': result.extracted_data,
        'edited': result.edited_data if result.data_edited else None,
        'edited_flag': result.data_edited,
        'lookup': _parse_lookup_raw(result.extracted_data),
        'has_result': True,
    }


def _clean_field(db_field, model_field, value, instance=None):
    if db_field.lookup_field:
        if value in (None, ''):
            return None, None
        obj = _related_instance(model_field, value)
        return obj.pk, {'label': build_lookup_label(obj, db_field), 'code': str(obj.pk)}
    if value in (None, ''):
        return model_field.to_python(value) if value == '' else None, None
    return model_field.to_python(value), None


def _required_field(model_field):
    return not model_field.null and not model_field.blank and not model_field.has_default()


def _is_blank(value):
    return value is None or value == ''


def _classification(db_field, model_field, result_info, proposed_value, action):
    raw = result_info['extracted']
    if db_field.lookup_field:
        parsed = _parse_lookup_raw(raw)
        original = parsed.get('code') if parsed else raw
        target_field = model_field.target_field
        try:
            original = target_field.to_python(original) if original not in (None, '') else None
        except ValidationError:
            original = raw
        proposed_value = target_field.to_python(proposed_value) if proposed_value not in (None, '') else None
    else:
        try:
            original = model_field.to_python(raw) if raw not in (None, '') else None
        except (ValidationError, ValueError, TypeError):
            original = raw
    if result_info['state'] == 'not_found':
        original = None
    decision = classify_review(original, proposed_value,
                               source_state=result_info['state'], disposition=action)
    decision['data_edited'] = decision['review_change'] in (
        ReviewChangeChoices.EDITED, ReviewChangeChoices.FILLED_MISSING, ReviewChangeChoices.CLEARED)
    return decision


def _validate_payload(job, payload):
    if not isinstance(payload, dict):
        raise ReviewValidationError({'__all__': ['Invalid review submission.']})
    if payload.get('schema_version') != REVIEW_SCHEMA_VERSION:
        raise ReviewValidationError({'__all__': ['This review form is out of date. Refresh it and try again.']})
    if int(payload.get('job_revision', -1)) != job.review_revision:
        raise ReviewConflictError('This job changed after the review form was opened.')
    _check_source_token(job, payload.get('source_token', ''))
    records = payload.get('records')
    if not isinstance(records, list):
        raise ReviewValidationError({'__all__': ['Invalid record list.']})


def _resolve_parent(record, entry, planned, errors):
    assignments = {}
    for rel in _relationship_fields(record):
        model = rel.relation_content_type.model_class()
        name = rel.clientapp_field_name
        if model is None:
            continue
        if model._meta.model_name == 'patient':
            assignments[f'{name}_id'] = record.extraction_job.processed_file.file_upload.patient_id_id
            continue
        if entry['operation'] == 'update' and entry['instance'] is not None:
            current_pk = getattr(entry['instance'], f'{name}_id')
            assignments[f'{name}_id'] = current_pk
            posted = (entry.get('parents') or {}).get(name)
            if posted and posted.get('kind') == 'existing' and str(posted.get('pk')) not in ('', str(current_pk)):
                errors[name] = ['Existing records cannot be moved to a different parent.']
            continue
        choice = (entry.get('parents') or {}).get(name)
        if not choice:
            errors[name] = ['Select a parent record.']
            continue
        kind = choice.get('kind')
        if kind == 'record':
            parent_id = int(choice.get('record_id') or 0)
            parent_plan = planned.get(parent_id)
            if parent_plan is None:
                errors[name] = ['The selected extracted parent is not part of this save.']
            elif _model_name(parent_plan['record'].database_table) != rel.relation_content_type.model:
                errors[name] = ['The selected parent has the wrong record type.']
            elif parent_plan['operation'] == 'skip':
                errors[name] = ['The selected parent is marked Leave pending. Choose another parent.']
            else:
                assignments[name] = parent_plan['future_pk']
        elif kind == 'existing':
            table = parent_table_for_relation(record, rel)
            target = _target_instance(table, record.extraction_job.processed_file.file_upload.patient_id,
                                    choice.get('pk'), errors, 'parent record')
            if target is not None:
                assignments[f'{name}_id'] = target.pk
        elif kind == 'patient':
            assignments[f'{name}_id'] = record.extraction_job.processed_file.file_upload.patient_id_id
        else:
            errors[name] = ['Choose a valid parent record.']
    return assignments


def parent_table_for_relation(record, relation_field):
    from extractor.models import DatabaseTable
    table = DatabaseTable.objects.filter(
        clientapp_content_type=relation_field.relation_content_type).first()
    if table is None:
        raise ReviewValidationError({'__all__': ['No configured table exists for the selected parent type.']})
    return table


def _plan_records(job, payload):
    records = {r.id: r for r in job.extracted_records.select_related(
        'database_table__clientapp_content_type').order_by('id')}
    if set(records) != {int(item.get('id') or -1) for item in payload['records']}:
        raise ReviewValidationError({'__all__': ['Every displayed extracted record must be included exactly once.']})
    if len(payload['records']) != len(records):
        raise ReviewValidationError({'__all__': ['Every displayed extracted record must be included exactly once.']})
    seen = set()
    errors = {}
    planned = {}
    patient = job.processed_file.file_upload.patient_id
    if patient is None:
        raise ReviewValidationError({'__all__': ['Link the source file to a patient before saving extracted data.']})
    for item in payload['records']:
        rid = int(item.get('id') or -1)
        if rid in seen:
            errors.setdefault('__all__', []).append(f'Record {rid} was submitted more than once.')
            continue
        seen.add(rid)
        record = records.get(rid)
        if record is None:
            continue
        table = record.database_table
        _assert_supported_table(table)
        operation = item.get('operation')
        if operation not in ('create', 'update', 'link', 'skip'):
            errors[rid] = {'action': ['Choose a valid action.']}
            continue
        latest = RecordCreation.objects.filter(
            extracted_record=record, record_created=True,
            operation__in=(RecordOperationChoices.CREATE, RecordOperationChoices.UPDATE,
                           RecordOperationChoices.LINK)).order_by('-created_at').first()
        existing = RecordCreation.objects.filter(
            extracted_record=record, operation=RecordOperationChoices.CREATE,
            record_created=True).first()
        entry_errors = {}
        target_pk = item.get('target_pk')
        target = None
        if operation == 'create' and latest:
            operation = 'link'
            target_pk = latest.created_record_pk
        if operation in ('update', 'link'):
            if latest and str(latest.created_record_pk) != str(target_pk):
                entry_errors['target'] = ['This extracted record is already linked to a different database record.']
            else:
                target = _target_instance(table, patient, target_pk, entry_errors)
        if operation in ('update', 'link') and target is None:
            entry_errors.setdefault('target', []).append('Select an existing record for this patient.')
        model = _model_for_table(table)
        future_pk = None
        if operation == 'create':
            pk_field = model._meta.pk
            future_pk = pk_field.default() if callable(pk_field.default) else pk_field.get_default()
        elif target is not None:
            future_pk = target.pk
        planned[rid] = {
            'record': record, 'operation': operation, 'instance': target,
            'future_pk': future_pk, 'entry_errors': entry_errors,
            'fields': {}, 'parents': {}, 'warnings': [], 'field_decisions': {},
        }
        if entry_errors:
            errors[rid] = entry_errors
    if errors:
        raise ReviewValidationError(errors)
    # Resolve parents after every planned record is known.
    for item in payload['records']:
        rid = int(item['id'])
        plan = planned[rid]
        if plan['operation'] == 'skip':
            continue
        entry_errors = plan['entry_errors']
        plan['parents'] = _resolve_parent(plan['record'], item, planned, entry_errors)
        if entry_errors:
            errors[rid] = entry_errors
    if errors:
        raise ReviewValidationError(errors)
    # Reject duplicate writers to the same clinical row.
    writers = {}
    for rid, plan in planned.items():
        if plan['operation'] in ('create', 'update') and plan['future_pk'] is not None:
            key = (_model_name(plan['record'].database_table), str(plan['future_pk']))
            previous = writers.get(key)
            if previous is not None:
                errors.setdefault(rid, {})['target'] = ['Another extracted record is already writing to this database record.']
            writers[key] = rid
    if errors:
        raise ReviewValidationError(errors)
    # Topological order by references to extracted records.
    deps = {rid: set() for rid in planned}
    for item in payload['records']:
        rid = int(item['id'])
        if planned[rid]['operation'] == 'skip':
            continue
        for rel in _relationship_fields(planned[rid]['record']):
            choice = (item.get('parents') or {}).get(rel.clientapp_field_name) or {}
            if choice.get('kind') == 'record':
                parent_id = int(choice.get('record_id') or 0)
                if parent_id in deps:
                    deps[rid].add(parent_id)
    ordered = []
    ready = [rid for rid, ds in deps.items() if not ds]
    while ready:
        rid = ready.pop(0)
        ordered.append(rid)
        for other, ds in deps.items():
            if rid in ds:
                ds.remove(rid)
                if not ds and other not in ordered and other not in ready:
                    ready.append(other)
    if len(ordered) != len(deps):
        raise ReviewValidationError({'__all__': ['The selected parent relationships contain a cycle.']})
    return planned, ordered


def _field_inputs(record, item, plan, entry_errors):
    result_map = {r.database_field_id: r for r in record.results.select_related('database_field')}
    fields = {}
    for db_field in _extractable_fields(record):
        model_field = _field_model_field(record.database_table, db_field)
        if model_field is None or model_field.name in SYSTEM_FIELD_NAMES:
            continue
        result = result_map.get(db_field.id)
        info = _result_payload(result)
        submitted = (item.get('fields') or {}).get(str(db_field.id), {})
        action = submitted.get('action', 'apply')
        if action not in ('apply', 'clear', 'preserve'):
            entry_errors[db_field.clientapp_field_name] = ['Choose a valid field action.']
            continue
        if plan['operation'] == 'update' and action == 'preserve':
            continue
        raw_value = submitted.get('value')
        if result is None and action == 'apply' and raw_value in (None, ''):
            continue
        if action == 'preserve' or (
                action == 'apply' and plan['operation'] == 'update' and raw_value in (None, '')
        ):
            if result is not None and result.result_state == 'unresolved' and not _required_field(model_field):
                decision = _classification(db_field, model_field, info, None, 'apply')
                decision['applied'] = False
                plan['field_decisions'][db_field.id] = {
                    'result_id': result.id,
                    'action': 'preserve',
                    'value': None,
                    **decision,
                }
                plan['warnings'].append(f"{db_field.clientapp_field_name}: extracted value has no lookup match and will preserve the existing value.")
            continue
        if action == 'clear':
            if _required_field(model_field):
                entry_errors[db_field.clientapp_field_name] = ['This field is required and cannot be cleared.']
                continue
            value = None if model_field.null else ''
        elif raw_value in (None, ''):
            if result is not None and result.result_state == 'unresolved':
                info = dict(info)
                info['unresolved'] = True
                value = None
            else:
                value = None if model_field.null else ''
        else:
            try:
                value, lookup_data = _clean_field(db_field, model_field, raw_value, plan['instance'])
                if lookup_data:
                    info['lookup_edited'] = lookup_data
            except Exception:
                entry_errors[db_field.clientapp_field_name] = ['Enter a valid value.']
                continue
        decision = _classification(db_field, model_field, info, value, action)
        if result is not None and result.result_state == 'unresolved' and value in (None, ''):
            decision['applied'] = False
        else:
            decision['applied'] = True
        fields[db_field.clientapp_field_name] = value
        plan['field_decisions'][db_field.id] = {
            'result_id': result.id if result else None,
            'action': action,
            'value': _to_jsonable(value),
            **decision,
        }
        if result is not None and result.result_state == 'unresolved' and value in (None, '') and not _required_field(model_field):
            plan['warnings'].append(f"{db_field.clientapp_field_name}: extracted value has no lookup match and will be omitted.")
    return fields


def _prepare_instances(planned, ordered):
    created = {}
    plans = []
    for rid in ordered:
        plan = planned[rid]
        if plan['operation'] == 'skip':
            continue
        record = plan['record']
        model = _model_for_table(record.database_table)
        if plan['operation'] == 'link':
            continue
        if plan['operation'] == 'update':
            instance = plan['instance']
            for name, value in plan['fields'].items():
                setattr(instance, name, value)
        else:
            values = {model._meta.pk.name: plan['future_pk']}
            values.update(plan['fields'])
            for name, pk in plan['parents'].items():
                values[f'{name}_id'] = pk
            instance = model(**values)
        if hasattr(instance, 'prepare_for_save'):
            instance.prepare_for_save()
        plans.append(plan | {'planned_instance': instance})
    return plans


def prepare_review(job, user, payload, request_key):
    _check_permissions(job, user)
    if job.extraction_status not in ('completed', 'partial'):
        raise ReviewValidationError({'__all__': ['Save is available after extraction reaches a completed or partial result.']})
    _validate_payload(job, payload)
    digest = hashlib.sha256(_json_dumps(payload).encode()).hexdigest()
    existing = ExtractionReviewBatch.objects.filter(
        extraction_job=job, prepared_by=user, request_key=request_key).first()
    if existing:
        if existing.payload_digest != digest:
            raise ReviewConflictError('This request was already used with different review data.')
        if existing.status == ReviewStatusChoices.PENDING and existing.expires_at > timezone.now():
            return existing
        raise ReviewConflictError('This preview has already been replaced or approved.')
    planned, ordered = _plan_records(job, payload)
    errors = {}
    for item in payload['records']:
        rid = int(item['id'])
        plan = planned[rid]
        if plan['operation'] == 'link' and not user.has_perm(f"client_app.view_{_model_name(plan['record'].database_table)}"):
            plan['entry_errors']['operation'] = ['You do not have permission to view this type of record.']
        if plan['operation'] == 'skip':
            continue
        if plan['operation'] == 'create' and not user.has_perm(f"client_app.add_{_model_name(plan['record'].database_table)}"):
            plan['entry_errors']['operation'] = ['You do not have permission to create this type of record.']
        if plan['operation'] == 'update' and not user.has_perm(f"client_app.change_{_model_name(plan['record'].database_table)}"):
            plan['entry_errors']['operation'] = ['You do not have permission to update this type of record.']
        plan['fields'] = _field_inputs(plan['record'], item, plan, plan['entry_errors'])
        if plan['entry_errors']:
            errors[rid] = plan['entry_errors']
    if errors:
        raise ReviewValidationError(errors)
    prepared_plans = _prepare_instances(planned, ordered)
    errors = {}
    for plan in prepared_plans:
        instance = plan['planned_instance']
        rel_names = [f.clientapp_field_name for f in _relationship_fields(plan['record'])]
        try:
            if plan['operation'] == 'create':
                instance.full_clean(exclude=rel_names)
            else:
                instance.full_clean()
        except ValidationError as exc:
            errors[plan['record'].id] = exc.message_dict if hasattr(exc, 'message_dict') else {'__all__': exc.messages}
        plan['before'] = _snapshot_instance(plan['instance']) if plan['operation'] == 'update' else None
        plan['after'] = _snapshot_instance(instance)
        candidates = find_duplicate_candidates(plan['record'].database_table, plan['record']) if plan['operation'] == 'create' else []
        if candidates:
            plan['warnings'].append(
                f"Possible duplicate: {len(candidates)} existing record(s) match this record.")
    if errors:
        raise ReviewValidationError(errors)
    snapshot_records = []
    for item in payload['records']:
        rid = int(item['id'])
        plan = planned[rid]
        record = plan['record']
        before_map = plan.get('before') or {}
        after_map = plan.get('after') or {}
        snapshot_records.append({
            'record_id': rid,
            'model': _model_name(record.database_table),
            'operation': plan['operation'],
            'target_pk': str(plan['future_pk']) if plan['future_pk'] is not None else None,
            'parents': {k: str(v) for k, v in plan['parents'].items()},
            'fields': {k: _to_jsonable(v) for k, v in plan.get('fields', {}).items()},
            'before': before_map,
            'after': after_map,
            'rows': [{'name': name, 'before': before_map.get(name), 'after': after}
                     for name, after in after_map.items()],
            'warnings': plan.get('warnings', []),
            'field_decisions': plan.get('field_decisions', {}),
            'source_results': {
                r.database_field_id: _result_payload(r)
                for r in record.results.select_related('database_field')
            },
        })
    duplicate_warning = any(r['warnings'] and 'Possible duplicate' in ' '.join(r['warnings']) for r in snapshot_records)
    snapshot = {
        'schema_version': REVIEW_SCHEMA_VERSION,
        'job_id': job.id,
        'job_revision': job.review_revision,
        'source_fingerprint': _fingerprint(job),
        'patient_pk': str(job.processed_file.file_upload.patient_id.pk),
        'input': payload,
        'records': snapshot_records,
        'warnings': {'duplicates': duplicate_warning},
        'prepared_by': {'id': user.id, 'username': user.username},
    }
    with transaction.atomic():
        ExtractionReviewBatch.objects.filter(
            extraction_job=job, prepared_by=user,
            status=ReviewStatusChoices.PENDING).update(status=ReviewStatusChoices.SUPERSEDED)
        batch = ExtractionReviewBatch.objects.create(
            extraction_job=job,
            prepared_by=user,
            expires_at=timezone.now() + REVIEW_EXPIRY,
            request_key=request_key,
            source_revision=job.review_revision,
            payload_digest=digest,
            snapshot=_json_dumps(snapshot),
        )
    return batch


def get_review_context(job, user, payload=None):
    data = {'job': job, 'source_token': _source_token(job),
            'job_revision': job.review_revision,
            'request_key': str(uuid.uuid4()),
            'can_edit': user.has_perm('extractor.change_extractionresult')}
    if payload is not None:
        data['payload'] = payload
    return data


def _require_pending(batch, user):
    if batch.prepared_by_id != user.id:
        raise PermissionDenied
    if batch.status == ReviewStatusChoices.APPROVED:
        return False
    if batch.status != ReviewStatusChoices.PENDING or batch.expires_at <= timezone.now():
        raise ReviewConflictError('This preview is no longer available. Prepare a fresh preview.')
    return True


def approve_review(batch_id, user, *, confirm, acknowledge_duplicates):
    _check_permissions(batch := ExtractionReviewBatch.objects.select_related(
        'extraction_job__processed_file__file_upload').get(id=batch_id), user)
    if not confirm:
        raise ReviewValidationError({'confirm': ['Confirm the values shown in the preview before saving.']})
    snapshot = _json_loads(batch.snapshot)
    if snapshot['warnings'].get('duplicates') and not acknowledge_duplicates:
        raise ReviewValidationError({'acknowledge_duplicates': ['Acknowledge the duplicate warning before saving.']})
    with transaction.atomic():
        batch = ExtractionReviewBatch.objects.select_for_update().select_related(
            'extraction_job__processed_file__file_upload').get(id=batch_id)
        job = ExtractionJob.objects.select_for_update().get(id=batch.extraction_job_id)
        if not _require_pending(batch, user):
            return batch
        if job.review_revision != batch.source_revision or snapshot['source_fingerprint'] != _fingerprint(job):
            raise ReviewConflictError('The source data changed after this preview was prepared.')
        for record_plan in snapshot['records']:
            table = ExtractionJob.objects.get(id=job.id).extracted_records.get(
                id=record_plan['record_id']).database_table
            operation = record_plan['operation']
            if operation == 'create':
                required = f"client_app.add_{record_plan['model']}"
            elif operation == 'update':
                required = f"client_app.change_{record_plan['model']}"
            else:
                required = f"client_app.view_{record_plan['model']}"
            if not user.has_perm(required):
                raise PermissionDenied
        receipt = _apply_snapshot(batch, job, snapshot, user)
        batch.status = ReviewStatusChoices.APPROVED
        batch.approved_by = user
        batch.approved_at = timezone.now()
        batch.receipt = _json_dumps(receipt)
        batch.save(update_fields=['status', 'approved_by', 'approved_at', 'receipt', 'updated_at'])
        job.review_revision += 1
        job.save(update_fields=['review_revision', 'updated_at'])
    return batch


def _apply_snapshot(batch, job, snapshot, user):
    operations = []
    saved_records = {}
    result_links = []
    for item in snapshot['records']:
        record = job.extracted_records.select_related('database_table__clientapp_content_type').get(id=item['record_id'])
        model = _model_for_table(record.database_table)
        operation = item['operation']
        if operation == 'skip':
            continue
        if operation == 'link':
            target_pk = item['target_pk']
            creation = RecordCreation.objects.create(
                extraction_job=job, database_table=record.database_table,
                extracted_record=record, review_batch=batch,
                created_record_pk=target_pk, operation=RecordOperationChoices.LINK,
                record_created=True, record_created_by=user)
            operations.append({'record_id': record.id, 'model': item['model'], 'operation': operation,
                               'target_pk': target_pk, 'record_creation_id': creation.id,
                               'after': _snapshot_instance(model.objects.get(pk=target_pk))})
            saved_records[record.id] = target_pk
            continue
        if operation == 'update':
            instance = model.objects.select_for_update().get(pk=item['target_pk'])
            expected_parent = {name: pk for name, pk in item['parents'].items()}
            for name, pk in expected_parent.items():
                if str(getattr(instance, name)) != str(pk):
                    raise ReviewConflictError('A selected existing record changed its parent after the preview.')
            for name, value in item['fields'].items():
                db_field = DatabaseField.objects.get(
                    clientapp_database_table=record.database_table,
                    clientapp_field_name=name)
                model_field = model._meta.get_field(name)
                clean, _ = _clean_field(db_field, model_field, value, instance)
                setattr(instance, name, clean)
        else:
            values = {model._meta.pk.name: item['target_pk']}
            values.update({name: _restore_model_value(model, name, value) for name, value in item['fields'].items()})
            values.update(item['parents'])
            instance = model(**values)
        if hasattr(instance, 'prepare_for_save'):
            instance.prepare_for_save()
        instance.full_clean()
        instance.save()
        saved_records[record.id] = instance.pk
        after = _snapshot_instance(instance)
        planned_after = item.get('after') or {}
        for key, expected in planned_after.items():
            if key in ('created_at', 'updated_at'):
                continue
            if after.get(key) != expected:
                raise ReviewConflictError(f'{instance._meta.model_name}.{key} changed before save.')
        creation = RecordCreation.objects.create(
            extraction_job=job, database_table=record.database_table,
            extracted_record=record, review_batch=batch,
            created_record_pk=str(instance.pk), operation=operation,
            record_created=True, record_created_by=user)
        operations.append({'record_id': record.id, 'model': item['model'], 'operation': operation,
                           'target_pk': str(instance.pk), 'record_creation_id': creation.id,
                           'after': after})
        result_links.append((creation, item['field_decisions'], record))
    now = timezone.now()
    for creation, decisions, record in result_links:
        for field_id, decision in decisions.items():
            result = ExtractionResult.objects.filter(
                record=record, database_field_id=field_id).first()
            if result is None:
                db_field = DatabaseField.objects.get(id=field_id)
                result = ExtractionResult.objects.create(
                    extraction_job=job, database_field=db_field, record=record,
                    extracted_data='', result_state='not_found',
                    source_kind=ResultSourceChoices.MANUAL_SUPPLEMENT)
            result.data_accuracy = decision['data_accuracy']
            result.data_edited = decision['data_edited']
            result.edited_data = decision['value'] if decision['data_edited'] else None
            result.review_change = decision['review_change']
            result.verified_by = user
            result.verification_date_time = now
            result.revision_history = (result.revision_history or []) + [{
                'batch_id': str(batch.id), 'action': decision['review_change'],
                'applied': decision['applied'], 'user': user.id, 'at': now.isoformat(),
            }]
            result.save()
            if decision['applied']:
                RecordCreationField.objects.create(
                    record_creation=creation, extraction_result=result)
    return {
        'schema_version': REVIEW_SCHEMA_VERSION,
        'approved_by': {'id': user.id, 'username': user.username},
        'approved_at': now.isoformat(),
        'operations': operations,
        'pending_record_ids': [item['record_id'] for item in snapshot['records'] if item['operation'] == 'skip'],
    }


def _restore_model_value(model, name, value):
    field = model._meta.get_field(name)
    if isinstance(field, models.ForeignKey):
        return None if value in (None, '') else field.related_model.objects.get(pk=value)
    if value in (None, ''):
        return None if field.null else value
    return field.to_python(value)


def _review_editable_fields(record):
    for field in _extractable_fields(record):
        model_field = _field_model_field(record.database_table, field)
        if (model_field is None or not model_field.concrete or model_field.primary_key or
                not model_field.editable or model_field.many_to_many or
                model_field.name in SYSTEM_FIELD_NAMES):
            continue
        if model_field.is_relation and model_field.related_model._meta.app_label != 'lookup':
            continue
        yield field, model_field


def _existing_review_values(record, instance):
    fields = {}
    for db_field, model_field in _review_editable_fields(record):
        value = getattr(instance, model_field.attname)
        text = _format_existing_cell(instance, db_field)['text']
        fields[str(db_field.id)] = {
            'value': '' if value is None else str(_to_jsonable(value)),
            'text': text,
        }
    parents = {
        field.name: str(getattr(instance, field.attname))
        for field in instance._meta.fields if isinstance(field, models.ForeignKey)
        and field.related_model._meta.app_label == 'client_app'
    }
    return {'fields': fields, 'parents': parents}


def review_options(job, user, *, record_id, kind, field_id=None, query='', page=1, selected_pk=None):
    from django.db.models.functions import Cast

    _check_permissions(job, user, preview=True)
    if page < 1:
        raise ReviewValidationError({'page': ['Page must be at least one.']})
    record = job.extracted_records.select_related('database_table__clientapp_content_type').get(id=record_id)
    patient = job.processed_file.file_upload.patient_id
    field = None
    if kind == 'lookup':
        allowed = {str(f.id): (f, mf) for f, mf in _review_editable_fields(record)}
        pair = allowed.get(str(field_id))
        if not pair or not pair[0].lookup_field or not isinstance(pair[1], models.ForeignKey):
            raise ReviewValidationError({'field': ['Choose an available lookup field.']})
        field, model_field = pair
        model = model_field.related_model
        if (not field.lookup_content_type or field.lookup_content_type.model_class() != model or
                model._meta.app_label != 'lookup'):
            raise ReviewValidationError({'field': ['The lookup configuration does not match this field.']})
        qs = model._default_manager.complex_filter(model_field.get_limit_choices_to())
        label_fields = field.lookup_label_fields or [field.lookup_table_value_field_name]
        search_fields = [name for name in label_fields if name in {
            f.name for f in model._meta.fields if isinstance(f, (models.CharField, models.TextField))}]
    elif kind in ('target', 'parent', 'values'):
        table = record.database_table
        if kind == 'parent':
            field = record.database_table.databasefield_set.get(id=field_id, is_active=True)
            model_field = _field_model_field(table, field)
            if (not field.relation_content_type or not isinstance(model_field, models.ForeignKey) or
                    field.relation_content_type.model_class() != model_field.related_model or
                    model_field.related_model._meta.app_label != 'client_app'):
                raise ReviewValidationError({'field': ['Choose a valid parent field.']})
            table = parent_table_for_relation(record, field)
        if not _has_model_perm(user, table, 'view'):
            raise PermissionDenied
        qs = _target_queryset(table, patient)
        if kind == 'values':
            try:
                instance = qs.get(pk=selected_pk)
            except (qs.model.DoesNotExist, ValidationError, ValueError, TypeError):
                raise ReviewValidationError({'target': ['Choose an existing record for this patient.']})
            return _existing_review_values(record, instance)
        search_fields = [f.name for f in qs.model._meta.fields
                         if type(f) in (models.CharField, models.TextField)]
    else:
        raise ReviewValidationError({'kind': ['Choose a valid option type.']})
    if selected_pk:
        qs = qs.filter(pk=selected_pk)
    elif query:
        qs = qs.annotate(review_option_pk=Cast('pk', output_field=models.CharField()))
        condition = models.Q(review_option_pk__icontains=query)
        for name in search_fields:
            condition |= models.Q(**{f'{name}__icontains': query})
        qs = qs.filter(condition)
    start = (page - 1) * OPTION_PAGE_SIZE
    items = list(qs.order_by('pk')[start:start + OPTION_PAGE_SIZE + 1])
    results = []
    for obj in items[:OPTION_PAGE_SIZE]:
        label = build_lookup_label(obj, field) if kind == 'lookup' else str(obj)
        results.append({'id': str(obj.pk), 'text': f'{label} ({obj.pk})'})
    return {'results': results, 'pagination': {'more': len(items) > OPTION_PAGE_SIZE}}

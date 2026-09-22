"""
Patient-page data assembly.

Builds the per-patient view of extracted staging data organized by the
client_app model hierarchy, alongside the records that already exist in
client_app, so reviewers can compare "exists vs extracted" per table.
"""

import json
import os
from logging import getLogger

from django.contrib.contenttypes.models import ContentType

from extractor.models import (
    DatabaseTable, DatabaseField, ExtractedRecord, ExtractionResult,
    ExtractionJob, RecordCreation,
)
from extractor.services.schema_discovery import SchemaDiscoveryService
from extractor.services.semantic_search import build_lookup_label
from extractor.services.record_writer import find_duplicate_candidates, resolve_record_pk, effective_result_value

log = getLogger(__name__)

# Model fields never shown as grid columns
_SKIP_FIELD_NAMES = {'id', 'created_at', 'updated_at'}

# Lookup models that hold measurement units — their fields pair with numerics
_UNIT_LOOKUP_MODELS = {
    'lookupsizeunits', 'lookupvolumeunits', 'lookupdoseunits',
    'lookupmassunits', 'lookuplabresultsunits', 'lookupexpressionunits',
}
# Tokens used to pair a unit field with a numeric field sharing its meaning
_UNIT_TOKENS = ('dose', 'size', 'volume', 'dimension', 'distance',
                'expression', 'result', 'medication')
_NUMERIC_TYPES = {'int', 'float'}


def _is_unit_field(db_field):
    return (db_field.lookup_field and db_field.lookup_content_type and
            db_field.lookup_content_type.model in _UNIT_LOOKUP_MODELS)


def _unit_pairing(db_table):
    """
    {numeric_db_field_id: unit_db_field} — pairs each numeric field with the
    unit field that measures it, within one table. For each numeric field the
    best unit wins: a semantic token match (dose→dose_units) outranks a short
    name-prefix match (volume_dose_prescribed → radiation_dose_units), while a
    long prefix still wins (lesion_size_* → lesion_size_unit).
    """
    fields = list(db_table.databasefield_set.filter(is_active=True)
                      .select_related('lookup_content_type'))
    numerics = [f for f in fields if f.field_type in _NUMERIC_TYPES]
    units = [f for f in fields if _is_unit_field(f)]
    pairs = {}
    for num in numerics:
        name = num.clientapp_field_name
        best, best_score = None, 0
        for unit in units:
            stem = unit.clientapp_field_name
            for suffix in ('_units', '_unit'):
                if stem.endswith(suffix):
                    stem = stem[:-len(suffix)]
            score = 0
            if name.startswith(stem):
                score = len(stem)
            # Semantic match (dose→radiation_dose_units) outranks a mere
            # prefix (volume_dose_prescribed vs volume_units)
            if any(t in name and t in stem for t in _UNIT_TOKENS):
                score = max(score, 100 + len(stem))
            if score > best_score:
                best, best_score = unit, score
        if best:
            pairs[num.id] = best
    return pairs


def _is_lookup_json(value):
    return isinstance(value, dict) and 'code' in value


def _cell_value(result, *, original=False):
    """Effective display value for an ExtractionResult."""
    if result.result_state == 'not_found' and (original or not result.data_edited):
        return {'text': '—', 'kind': 'not_found'}
    raw = result.extracted_data if original or (
        result.result_state == 'unresolved' and not result.data_edited
    ) else effective_result_value(result)
    try:
        parsed = json.loads(raw) if raw is not None else None
    except (TypeError, json.JSONDecodeError):
        parsed = raw
    if _is_lookup_json(parsed):
        label = parsed.get('label') or ''
        code = parsed.get('code')
        text = f"{label} ({code})" if code not in (None, '') else str(label)
        return {'text': text, 'kind': 'unresolved' if result.result_state == 'unresolved' else 'lookup',
                'code': code, 'label': label}
    if parsed is None or parsed == '':
        return {'text': '—', 'kind': 'not_found'}
    kind = 'unresolved' if result.result_state == 'unresolved' else 'value'
    return {'text': str(parsed), 'kind': kind}


def _grid_columns(db_table):
    """Extractable columns for a table's grid, in model declaration order."""
    model = db_table.clientapp_content_type.model_class()
    field_order = {field.name: index for index, field in enumerate(model._meta.fields)} if model else {}
    cols = []
    for f in db_table.databasefield_set.filter(is_active=True).order_by('pk'):
        if not f.is_extractable():
            continue
        if f.clientapp_field_name in _SKIP_FIELD_NAMES:
            continue
        cols.append(f)
    cols.sort(key=lambda field: field_order.get(field.clientapp_field_name, len(field_order)))
    return cols


def _lookup_options_map(db_table):
    """{database_field_id: [{'code','label'}]} — dropdown options for lookup corrections."""
    out = {}
    for f in db_table.databasefield_set.filter(is_active=True, lookup_field=True).select_related('lookup_content_type'):
        model_class = f.lookup_content_type.model_class() if f.lookup_content_type else None
        if not model_class:
            continue
        pk_field = f.lookup_table_pk_field_name or 'pk'
        out[f.id] = [
            {'code': getattr(obj, pk_field), 'label': build_lookup_label(obj, f)}
            for obj in model_class.objects.all()
        ]
    return out


def _format_existing_cell(row, db_field):
    """Value of a live client_app row for one configured column."""
    name = db_field.clientapp_field_name
    try:
        value = getattr(row, name)
    except AttributeError:
        return {'text': '—', 'kind': 'not_found'}
    if db_field.lookup_field and value is not None:
        label = getattr(value, db_field.lookup_table_value_field_name or 'label', str(value))
        code = getattr(value, db_field.lookup_table_pk_field_name or 'pk', '')
        return {'text': f"{label} ({code})", 'kind': 'lookup'}
    if value is None or value == '':
        return {'text': '—', 'kind': 'not_found'}
    return {'text': str(value), 'kind': 'existing'}


def get_existing_rows(db_table, patient, columns):
    """
    Live client_app rows for this patient in the given table.
    Uses the table's recorded patient_path FK chain to filter.
    """
    model_class = db_table.clientapp_content_type.model_class()
    if not model_class or patient is None:
        return []
    path = (db_table.clientapp_table_fk_fields or {}).get('patient_path')
    if not path:
        return []
    lookup = '__'.join(step['field'] for step in path)
    rows = model_class.objects.filter(**{lookup: patient})
    out = []
    for row in rows:
        cells = [_format_existing_cell(row, c) for c in columns]
        out.append({
            'pk': row.pk,
            'cells': cells,
            'pairs': [{'name': c.clientapp_field_name, 'cell': cell}
                      for c, cell in zip(columns, cells)],
        })
    return out


def resolve_lookup_row(db_field, code):
    """
    Fetch the lookup object for a stored code and return ordered
    (field_name, value) pairs — all fields except pk and audit stamps —
    for the expandable "lookup details" display.
    """
    if not db_field.lookup_field or not db_field.lookup_content_type or code in (None, ''):
        return None
    model_class = db_field.lookup_content_type.model_class()
    if not model_class:
        return None
    pk_field = db_field.lookup_table_pk_field_name or 'pk'
    try:
        obj = model_class.objects.get(**{pk_field: code})
    except model_class.DoesNotExist:
        return None
    skip = {pk_field, 'created_at', 'updated_at'}
    pairs = []
    for f in model_class._meta.get_fields():
        if f.name in skip or not hasattr(f, 'attname'):
            continue
        pairs.append((f.name, getattr(obj, f.name)))
    return pairs


def _existing_rows_for_parent(child_table, parent_rec, columns):
    """
    Existing client_app rows under the concrete parent of an extracted
    record — children of its created row or unique dedup match. Empty when
    the parent doesn't resolve to a specific row yet.
    """
    pk = resolve_record_pk(parent_rec)
    model_class = child_table.clientapp_content_type.model_class()
    path = (child_table.clientapp_table_fk_fields or {}).get('patient_path') or []
    if pk in (None, '') or model_class is None or not path:
        return []
    # patient_path[0] is the child's FK to its immediate parent
    rows = model_class.objects.filter(**{path[0]['field']: pk})
    out = []
    for row in rows:
        cells = [_format_existing_cell(row, c) for c in columns]
        out.append({
            'pk': row.pk,
            'cells': cells,
            'pairs': [{'name': c.clientapp_field_name, 'cell': cell}
                      for c, cell in zip(columns, cells)],
        })
    return out


def _patient_jobs(patient):
    """All extraction jobs whose source file belongs to this patient."""
    return ExtractionJob.objects.filter(
        processed_file__file_upload__patient_id=patient
    ).select_related('processed_file__file_upload', 'response_model__client')


def build_patient_data_tree(patient):
    """
    Per-table grid data for the patient page — all staging records across
    every job for this patient. Thin wrapper over build_records_data_tree.
    """
    records = _record_qs().filter(extraction_job__in=_patient_jobs(patient))
    return build_records_data_tree(records, patient)


def build_job_data_tree(extraction_job):
    """
    Same record grid scoped to one extraction job — the canonical review
    view on the job detail page. Existing-row comparison and write-back
    use the job file's patient (may be None).
    """
    records = _record_qs().filter(extraction_job=extraction_job)
    upload = getattr(extraction_job.processed_file, 'file_upload', None)
    patient = getattr(upload, 'patient_id', None)
    return build_records_data_tree(records, patient)


def _record_qs():
    return ExtractedRecord.objects.select_related(
        'database_table__clientapp_content_type',
        'extraction_job__processed_file__file_upload',
    ).order_by('extraction_job_id', 'record_index')


def _input_kind(model_field, db_field):
    if db_field.lookup_field:
        return 'lookup'
    if model_field is None:
        return 'text'
    if getattr(model_field, 'choices', None):
        return 'choice'
    internal = model_field.get_internal_type()
    if internal in ('BooleanField', 'NullBooleanField'):
        return 'boolean'
    if internal in ('DateField', 'DateTimeField', 'TimeField'):
        return internal.lower()
    if internal in ('IntegerField', 'PositiveIntegerField', 'SmallIntegerField', 'BigIntegerField'):
        return 'integer'
    if internal in ('FloatField', 'DecimalField'):
        return 'decimal'
    if internal == 'TextField':
        return 'textarea'
    return 'text'


def _input_value(result, db_field, *, original=False):
    if result is None:
        return ''
    raw = result.extracted_data if original else effective_result_value(result)
    if original and result.result_state == 'not_found':
        return ''
    if db_field.lookup_field:
        try:
            parsed = json.loads(raw) if raw else None
        except (TypeError, json.JSONDecodeError):
            parsed = raw
        value = parsed.get('code') if isinstance(parsed, dict) else parsed
        return '' if value is None else str(value)
    return '' if raw is None else str(raw)


def _lookup_selected(result, db_field):
    if result is None:
        return None
    raw = effective_result_value(result)
    try:
        parsed = json.loads(raw) if raw else None
    except (TypeError, json.JSONDecodeError):
        parsed = None
    if not isinstance(parsed, dict) or parsed.get('code') in (None, ''):
        return None
    return {'code': str(parsed['code']), 'label': parsed.get('label') or str(parsed['code'])}


def _row_label(row):
    parts = [p['cell']['text'] for p in row.get('pairs', []) if p['cell'].get('kind') not in ('not_found',)]
    return ' · '.join(parts[:3]) or str(row.get('pk'))


def _review_parent_fields(rec, patient, records_by_table):
    """Parent choices for the extracted record's real relationship fields."""
    out = []
    for rel in rec.database_table.databasefield_set.filter(
            is_active=True, field_validation__is_relationship=True,
            relation_content_type__isnull=False).select_related('relation_content_type'):
        if rel.relation_content_type.model == 'patient':
            continue
        parent_table = DatabaseTable.objects.filter(
            clientapp_content_type=rel.relation_content_type).first()
        extracted_choices = []
        existing_choices = []
        if parent_table:
            extracted_choices = [
                {'id': r.id, 'label': f"Extracted {parent_table.clientapp_content_type.model} record {r.record_index}"}
                for r in records_by_table.get(parent_table.id, [])
            ]
            existing_choices = [
                {'pk': row['pk'], 'label': f"#{str(row['pk'])[:8]} — {_row_label(row)}"}
                for row in get_existing_rows(parent_table, patient, _grid_columns(parent_table))
            ]
        default_record_id = rec.parent_record_id if (
            rec.parent_record and
            rec.parent_record.database_table.clientapp_content_type_id == rel.relation_content_type_id
        ) else None
        out.append({
            'field': rel,
            'field_id': rel.id,
            'name': rel.clientapp_field_name,
            'model': rel.relation_content_type.model,
            'extracted_choices': extracted_choices,
            'existing_choices': existing_choices,
            'default_record_id': default_record_id,
        })
    return out


def build_records_data_tree(records, patient):
    """
    Per-table grid data for a set of extracted staging records. Extracted
    records nest under their real parent record (parent_record) — child
    table grids appear inside the parent's detail panel, scoped to that
    parent. `patient` scopes the existing client_app rows shown for
    comparison; None yields no existing rows and no duplicate counts.
    """
    records = list(records)

    records_by_id = {rec.id: rec for rec in records}
    children_by_parent = {}
    root_records_by_table = {}
    for rec in records:
        if rec.parent_record_id and rec.parent_record_id in records_by_id:
            children_by_parent.setdefault(rec.parent_record_id, []).append(rec)
        else:
            root_records_by_table.setdefault(rec.database_table_id, []).append(rec)

    # Only tables that actually produced extracted records
    tables = (DatabaseTable.objects
              .filter(id__in={rec.database_table_id for rec in records})
              .select_related('clientapp_content_type'))

    # Reuse discovery's depth ordering (patient=0, direct children=1, ...)
    structure = SchemaDiscoveryService.get_hierarchical_table_structure()
    depth_of = {t['id']: (t['depth'] or 99) for t in structure}

    latest_operations = {}
    for rc in RecordCreation.objects.filter(
            extracted_record__in=records, record_created=True).order_by('created_at'):
        latest_operations[rc.extracted_record_id] = rc

    records_by_table = {}
    for rec in records:
        records_by_table.setdefault(rec.database_table_id, []).append(rec)

    # Presentation pieces shared by root and child nodes
    table_meta = {}
    for table in tables:
        columns = _grid_columns(table)
        options = {}
        # Attach dropdown options to column objects for template access
        for col in columns:
            col.options = options.get(col.id)
        model_class = table.clientapp_content_type.model_class()
        table_meta[table.id] = {
            'table': table,
            'depth': depth_of.get(table.id, 99),
            'display_name': model_class._meta.verbose_name.title()
                            if model_class else str(table),
            'columns': columns,
            'unit_pairs': _unit_pairing(table),
            'options': options,
        }

    def make_grid_record(rec):
        meta = table_meta[rec.database_table_id]
        columns = meta['columns']
        unit_pairs = meta['unit_pairs']
        results = {
            r.database_field_id: r
            for r in ExtractionResult.objects.filter(record=rec)
                    .select_related('database_field')
        }
        cells = []
        for col in columns:
            res = results.get(col.id)
            cells.append(_cell_value(res) if res else {'text': '—', 'kind': 'not_found'})
        state = {
            'unreviewed': sum(1 for r in results.values() if r.data_accuracy == 'unreviewed'),
            'unresolved': sum(1 for r in results.values() if r.result_state == 'unresolved'),
            'not_found': sum(1 for r in results.values() if r.result_state == 'not_found'),
        }
        upload = rec.extraction_job.processed_file.file_upload
        fname = upload.original_filename or os.path.basename(upload.file.name)
        # Resolved lookup details per lookup result (expandable panel data)
        lookup_details = {}
        for col in columns:
            res = results.get(col.id)
            if not res or not col.lookup_field:
                continue
            raw = effective_result_value(res)
            try:
                parsed = json.loads(raw) if raw else None
            except (TypeError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict) and parsed.get('code') not in (None, ''):
                pairs = resolve_lookup_row(col, parsed['code'])
                if pairs:
                    lookup_details[col.id] = pairs
        # Detail rows for the expandable panel: (column, result, cell, lookup pairs, unit pair)
        detail = []
        for col, cell in zip(columns, cells):
            unit_field = unit_pairs.get(col.id)
            unit_result = results.get(unit_field.id) if unit_field else None
            needs_unit = (
                unit_field is not None
                and cell['kind'] in ('value', 'lookup')
                and (unit_result is None or unit_result.result_state in ('not_found', 'unresolved'))
            )
            model_field = None
            model_class = meta['table'].clientapp_content_type.model_class()
            if model_class:
                try:
                    model_field = model_class._meta.get_field(col.clientapp_field_name)
                except Exception:
                    model_field = None
            result = results.get(col.id)
            original_value = _input_value(result, col, original=True)
            baseline = _input_value(result, col)
            separate_extraction = bool(result and result.source_kind == 'llm' and
                                       result.result_state != 'not_found' and
                                       result.extracted_data not in (None, ''))
            corrected = bool(result and result.data_edited and baseline != original_value)
            detail.append({
                'field': col,
                'model_field': model_field,
                'input_kind': _input_kind(model_field, col),
                'input_value': baseline if corrected or not separate_extraction else '',
                'baseline': baseline,
                'original_value': original_value,
                'separate_extraction': separate_extraction,
                'original_cell': _cell_value(result, original=True) if result else None,
                'lookup_selected': _lookup_selected(result, col) if corrected or not separate_extraction else None,
                'result': result,
                'cell': cell,
                'lookup_detail': lookup_details.get(col.id),
                'unit_field': unit_field,
                'unit_result': unit_result,
                'unit_cell': _cell_value(unit_result) if unit_result else None,
                'needs_unit': needs_unit,
            })

        # Child table grids holding only this record's children, with
        # existing rows scoped to the resolved parent instance.
        by_table = {}
        for cr in children_by_parent.get(rec.id, []):
            by_table.setdefault(cr.database_table_id, []).append(cr)
        child_nodes = []
        for ct_id in sorted(by_table, key=lambda i: depth_of.get(i, 99)):
            cmeta = table_meta[ct_id]
            child_nodes.append({
                'table': cmeta['table'],
                'depth': cmeta['depth'],
                'display_name': cmeta['display_name'],
                'columns': cmeta['columns'],
                'existing': _existing_rows_for_parent(
                    cmeta['table'], rec, cmeta['columns']),
                'records': [make_grid_record(cr) for cr in by_table[ct_id]],
                'lookup_options': cmeta['options'],
                'children': [],
            })

        latest = latest_operations.get(rec.id)
        return {
            'record': rec,
            'cells': cells,
            'detail': detail,
            'state': state,
            'source': fname,
            'created_pk': latest.created_record_pk if latest else None,
            'mapped_operation': latest.operation if latest else None,
            'target_options': [
                {'pk': row['pk'], 'label': f"#{str(row['pk'])[:8]} — {_row_label(row)}"}
                for row in get_existing_rows(meta['table'], patient, columns)
            ],
            'parent_fields': _review_parent_fields(rec, patient, records_by_table),
            'lookup_details': lookup_details,
            'dup_count': len(find_duplicate_candidates(meta['table'], rec)),
            'child_nodes': child_nodes,
        }

    nodes = []
    for table_id in sorted(root_records_by_table,
                           key=lambda i: (depth_of.get(i, 99),
                                          table_meta[i]['table'].clientapp_content_type.model)):
        meta = table_meta[table_id]
        nodes.append({
            'table': meta['table'],
            'depth': meta['depth'],
            'display_name': meta['display_name'],
            'columns': meta['columns'],
            'existing': get_existing_rows(meta['table'], patient, meta['columns']),
            'records': [make_grid_record(rec) for rec in root_records_by_table[table_id]],
            'lookup_options': meta['options'],
            'children': [],
        })

    # Only real parent_record links nest records. Orphaned child-table rows stay
    # at table level so a parent can be chosen explicitly during review.
    return nodes

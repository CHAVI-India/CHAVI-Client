"""
Response-model table hierarchy helpers.

The clinical tables in client_app form a single-parent chain toward Patient
(e.g. Pathology -> Diagnosis -> Patient). Schema discovery stores that chain
on ``DatabaseTable.clientapp_table_fk_fields['patient_path']``. These helpers
are the single source of truth for:

- which ancestor tables a selected table requires (``ancestor_tables``),
- how a response model's tables nest into a tree (``build_table_tree``),
- the JSON key a child table uses inside a parent record (``child_key``),
- which fields identify a record for dedup (``identity_field_names``).
"""

from logging import getLogger

from extractor.models import DatabaseTable, ResponseModelTable
from extractor.services.record_writer import get_match_fields

log = getLogger(__name__)


def _patient_path_steps(db_table):
    """patient_path steps minus the terminal patient step (parent first)."""
    path = (db_table.clientapp_table_fk_fields or {}).get('patient_path') or []
    return [s for s in path if s.get('model') != 'client_app.patient']


def ancestor_tables(db_table):
    """
    DatabaseTables a selected table needs extracted before it can be written
    back — every model on its patient_path chain, immediate parent first.

    Empty for depth-1 tables (parent is Patient, already known from the
    upload) and for tables without a patient_path (infra/DICOM models).
    """
    ancestors = []
    for step in _patient_path_steps(db_table):
        app_label, _, model = step.get('model', '').partition('.')
        if not app_label or not model:
            continue
        table = DatabaseTable.objects.filter(
            clientapp_content_type__app_label=app_label,
            clientapp_content_type__model=model,
        ).first()
        if table is not None:
            ancestors.append(table)
    return ancestors


def identity_field_names(db_table):
    """Field names identifying a record for dedup — union of match key-sets."""
    names = []
    for key_set in get_match_fields(db_table):
        for name in key_set:
            if name not in names:
                names.append(name)
    return names


def child_key(child_table):
    """JSON key a child table's records use inside a parent record."""
    return child_table.clientapp_content_type.model.lower().replace(' ', '_')


def build_table_tree(response_model):
    """
    Nest a response model's tables into (roots, children).

    A table nests under the ResponseModelTable for its immediate parent —
    the first patient_path step. Tables whose parent is Patient, absent, or
    not part of the response model are roots. children maps
    ``{parent ResponseModelTable.id: [child ResponseModelTable, ...]}``.
    """
    model_tables = list(
        ResponseModelTable.objects.filter(response_model=response_model)
        .select_related('database_table__clientapp_content_type'))
    by_model = {
        mt.database_table.clientapp_content_type.model: mt for mt in model_tables}

    roots, children = [], {}
    for mt in model_tables:
        steps = _patient_path_steps(mt.database_table)
        parent_mt = None
        if steps:
            parent_model = steps[0].get('model', '').partition('.')[-1]
            parent_mt = by_model.get(parent_model)
            if parent_mt is mt:
                parent_mt = None
        if parent_mt is None:
            roots.append(mt)
        else:
            children.setdefault(parent_mt.id, []).append(mt)
    return roots, children

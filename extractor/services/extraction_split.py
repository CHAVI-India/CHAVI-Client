"""
Planning, prompt building and response merging for split (chunked)
stage-2 extraction.

Pure logic: no LLM calls, no ORM writes. The caller
(extractor.services.instructor_extractor) owns the LLM round-trips,
stage_trace bookkeeping and saving.
"""
from logging import getLogger

from extractor.models import ResponseModelTableField

log = getLogger(__name__)


def topological_tables(roots, children):
    """
    Response-model tables in parent-first order (depth-first pre-order).

    roots: [ResponseModelTable]; children: {parent_mt.id: [child_mt, ...]}
    as returned by model_hierarchy.build_table_tree.
    """
    ordered = []

    def walk(mt):
        ordered.append(mt)
        for child in children.get(mt.id, []):
            walk(child)

    for root in roots:
        walk(root)
    return ordered


def active_extractable_fields(model_table):
    """A table's active, extractable DatabaseFields, in configured order."""
    rows = ResponseModelTableField.objects.filter(
        response_model_table=model_table,
        field__is_active=True,
    ).select_related('field', 'field__lookup_content_type').order_by('order')
    return [tf.field for tf in rows if tf.field.is_extractable()]


def plan_table_chunks(fields, batch_size):
    """
    Split one table's fields into ordered call chunks.

    Lookup (choice) fields come first — each in chunks of at most
    batch_size — followed by the non-lookup (reasoning) fields, so a
    call never mixes choice questions with reasoning questions.
    Returns [{'kind': 'lookup' | 'plain', 'fields': [DatabaseField, ...]}].
    """
    batch = max(1, int(batch_size))
    lookup = [f for f in fields if f.lookup_field]
    plain = [f for f in fields if not f.lookup_field]
    chunks = []
    for kind, group in (('lookup', lookup), ('plain', plain)):
        for i in range(0, len(group), batch):
            chunks.append({'kind': kind, 'fields': group[i:i + batch]})
    return chunks


def plan_extraction_calls(response_model, batch_size):
    """
    The full stage-2 call plan: one entry per table chunk, in
    parent-first topological order.

    Returns [{'index', 'model_table', 'kind', 'fields', 'ancestry'}] where
    'ancestry' is the list of ancestor ResponseModelTables, immediate
    parent LAST. A table with zero extractable fields produces no entry
    (its children, if any, cannot be anchored).
    """
    from extractor.services.model_hierarchy import build_table_tree

    roots, children = build_table_tree(response_model)
    plan = []

    def walk(mt, ancestry):
        for chunk in plan_table_chunks(active_extractable_fields(mt), batch_size):
            plan.append({
                'model_table': mt,
                'kind': chunk['kind'],
                'fields': chunk['fields'],
                'ancestry': list(ancestry),
            })
        for child in children.get(mt.id, []):
            walk(child, ancestry + [mt])

    for root in roots:
        walk(root, [])
    for i, call in enumerate(plan):
        call['index'] = i
    return plan

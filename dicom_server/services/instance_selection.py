"""Instance-level selection math over a study-tree dict.

Pure functions (no DB access) shared by BatchRetrieveView so the server — not
the browser — validates selections and decides which series to retrieve. The
study-tree shape is the JSON stored on RetrievalBatchPatient.studies (see the
help_text on that field in dicom_server/models.py).

Reference hierarchy used (populated by qr_client._find_instances_on_assoc):
  RTDOSE   -> referenced_plan_uids              (exactly one plan per dose)
  RTPLAN   -> referenced_structure_set_uids
  RTSTRUCT -> referenced_series_uids            (the image series)
"""


class SelectionError(ValueError):
    """Unknown UID or malformed selection — message is safe to show to the user."""


def _series_by_uid(study):
    return {se.get('series_instance_uid'): se
            for se in (study.get('series') or [])}


def _sop_index(study):
    """{sop_instance_uid: (series_dict, instance_dict)} for all RT instances."""
    out = {}
    for se in study.get('series') or []:
        for inst in se.get('rt_instances') or []:
            sop = inst.get('sop_instance_uid')
            if sop:
                out[sop] = (se, inst)
    return out


def sop_series_uid(study, sop_uid):
    """SeriesInstanceUID containing this SOP instance, or None."""
    hit = _sop_index(study).get(sop_uid)
    if not hit:
        return None
    return hit[0].get('series_instance_uid') or None


def instance_ancestors(study, sop_uid):
    """Ancestors of one RT instance, closed transitively.

    Returns (ancestor_sop_uids, ancestor_series_uids): a dose pulls its plan
    and that plan's struct set; a plan pulls its struct set; a struct set
    pulls the image series it references (only when that series is in the
    study)."""
    idx = _sop_index(study)
    series = _series_by_uid(study)
    sops, seuids = [], []
    seen = {sop_uid}
    stack = [sop_uid]
    while stack:
        cur = stack.pop()
        hit = idx.get(cur)
        if not hit:
            continue
        se, inst = hit
        mod = (se.get('modality') or '').upper()
        if mod == 'RTDOSE':
            refs = inst.get('referenced_plan_uids') or []
        elif mod == 'RTPLAN':
            refs = inst.get('referenced_structure_set_uids') or []
        else:
            refs = []
        for ref in refs:
            if ref in idx and ref not in seen:
                seen.add(ref)
                sops.append(ref)
                stack.append(ref)
        if mod == 'RTSTRUCT':
            for ref in inst.get('referenced_series_uids') or []:
                if ref in series and ref not in seuids:
                    seuids.append(ref)
    return sops, seuids


def normalize_selection(study, series_uids, sop_uids):
    """Validate a selection and close it under ancestors.

    series_uids: series-level picks (any modality, e.g. image series).
    sop_uids: RT instance picks (must belong to the study's rt_instances).
    Either may be None.

    Returns {'series_uids': [...], 'sop_uids': [...]} (both sorted) where
    series_uids is everything to C-MOVE — user picks plus the containing
    series of every selected and ancestor RT instance plus referenced image
    series — and sop_uids is the closed instance set stored for ingest
    filtering. Raises SelectionError for unknown UIDs.
    """
    series = _series_by_uid(study)
    idx = _sop_index(study)
    out_series, out_sops = set(), set()
    for u in series_uids or []:
        if u not in series:
            raise SelectionError(f'unknown series UID {u!r}')
        out_series.add(u)
    for u in sop_uids or []:
        if u not in idx:
            raise SelectionError(f'unknown SOP instance UID {u!r}')
        out_sops.add(u)
        a_sops, a_series = instance_ancestors(study, u)
        out_sops.update(a_sops)
        out_series.update(a_series)
        for s in [u] + a_sops:
            containing = sop_series_uid(study, s)
            if containing:
                out_series.add(containing)
    return {'series_uids': sorted(out_series), 'sop_uids': sorted(out_sops)}

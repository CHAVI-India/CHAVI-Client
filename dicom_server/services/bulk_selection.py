"""Declarative selection of DICOM objects for scheduled bulk retrieval.

Server-side port of the study/series/RT filtering + parent->child logic used by
the interactive batch_select UI (templates/dicom_server/batch_select.html) so an
unattended scheduled run can retrieve exactly the requested objects instead of
every study.
"""
import re
from dataclasses import dataclass, field

APPROVAL_ANY = ''
APPROVAL_APPROVED = 'approved'
APPROVAL_UNAPPROVED = 'unapproved'


@dataclass
class SelectionCriteria:
    """Declarative 'what to retrieve'. Empty values = no constraint on that
    axis. When every series-level axis is empty the whole (new) study is
    retrieved, matching the UI default."""
    modalities: list = field(default_factory=list)   # e.g. ['CT', 'RTPLAN']
    approval: str = APPROVAL_ANY                     # '' | 'approved' | 'unapproved'
    series_description: str = ''                     # substring, case-insensitive
    rt_label: str = ''                               # substring on plan/struct label/name
    study_date_from: str = ''                        # 'YYYY-MM-DD' or ''
    study_date_to: str = ''
    search: str = ''                                 # description/accession substring

    def series_filter_active(self) -> bool:
        return bool(
            self.modalities or self.approval
            or self.series_description or self.rt_label
        )


def _series_modality(se):
    return (se.get('modality') or '').upper()


def _study_mods(study):
    return [m for m in re.split(r'[,/\\ ]+', (study.get('modalities') or '')) if m]


def _dcm_date_to_iso(d):
    d = d or ''
    return f'{d[:4]}-{d[4:6]}-{d[6:8]}' if len(d) == 8 and d.isdigit() else ''


def _rt_labels(se):
    out = []
    for inst in se.get('rt_instances') or []:
        for k in ('structure_set_label', 'structure_set_name',
                  'rt_plan_label', 'rt_plan_name'):
            v = (inst.get(k) or '').strip()
            if v:
                out.append(v)
    return out


def _plan_approval_state(se):
    return APPROVAL_APPROVED if any(
        (i.get('approval_status') or '').upper() == 'APPROVED'
        for i in (se.get('rt_instances') or [])
    ) else APPROVAL_UNAPPROVED


def _series_by_uid(study):
    return {se.get('series_instance_uid'): se for se in (study.get('series') or [])}


def ancestors_of(study, seuid):
    by = _series_by_uid(study)
    out, seen, queue = [], {seuid}, [seuid]
    while queue:
        cur = queue.pop(0)
        for p in (by.get(cur) or {}).get('parent_series_uids') or []:
            if p in by and p not in seen:
                seen.add(p)
                out.append(p)
                queue.append(p)
    return out


def descendants_of(study, seuid):
    by = _series_by_uid(study)
    children = {}
    for se in by.values():
        for p in se.get('parent_series_uids') or []:
            children.setdefault(p, []).append(se.get('series_instance_uid'))
    out, seen, queue = [], {seuid}, [seuid]
    while queue:
        cur = queue.pop(0)
        for c in children.get(cur) or []:
            if c not in seen:
                seen.add(c)
                out.append(c)
                queue.append(c)
    return out


def _series_passes_approval(study, se, approval):
    mod = _series_modality(se)
    if mod == 'RTPLAN':
        return _plan_approval_state(se) == approval
    if mod == 'RTDOSE' and se.get('parent_series_uids'):
        parents = [x for x in study.get('series') or []
                   if x.get('series_instance_uid') in set(se['parent_series_uids'])]
        return any(_series_passes_approval(study, p, approval) for p in parents)
    return True


def _approval_visible(study, se, approval):
    if _series_passes_approval(study, se, approval):
        return True
    for d in descendants_of(study, se.get('series_instance_uid')):
        child = next((x for x in study.get('series') or []
                      if x.get('series_instance_uid') == d), None)
        if child and _series_passes_approval(study, child, approval):
            return True
    return False


def series_visible(se, study, c):
    mod = _series_modality(se)
    if c.modalities and mod not in [m.upper() for m in c.modalities]:
        return False
    if c.series_description and c.series_description.lower() not in \
            (se.get('series_description') or '').lower():
        return False
    if c.rt_label:
        needle = c.rt_label.lower()
        if not any(needle in lab.lower() for lab in _rt_labels(se)):
            return False
    if c.approval and not _approval_visible(study, se, c.approval):
        return False
    return True


def study_visible(study, c):
    """Study-level gate (mirrors the UI's studyVisible; already_local is handled
    by the caller via new_only)."""
    if c.search:
        needle = c.search.lower()
        study_match = ((study.get('study_description') or '') + ' ' +
                       (study.get('accession_number') or '')).lower()
        if needle not in study_match and not any(
            needle in (se.get('series_description') or '').lower()
            for se in study.get('series') or []
        ):
            return False
    if c.modalities:
        mods = [m.upper() for m in c.modalities]
        study_hit = any(m.upper() in mods for m in _study_mods(study))
        ser_hit = any(_series_modality(se) in mods for se in study.get('series') or [])
        if not study_hit and not ser_hit:
            return False
    if c.approval and not any(
        _approval_visible(study, se, c.approval)
        for se in study.get('series') or []
    ):
        return False
    iso = _dcm_date_to_iso(study.get('study_date'))
    if c.study_date_from and (not iso or iso < c.study_date_from):
        return False
    if c.study_date_to and (not iso or iso > c.study_date_to):
        return False
    return True


def select_study(study, c):
    """Return (study_instance_uid, [series_uids]|None) for a study, or None if it
    yields nothing under the criteria. A None series list means 'whole study'."""
    suid = study.get('study_instance_uid')
    if not suid or not study_visible(study, c):
        return None
    series = study.get('series') or []
    if not c.series_filter_active() or not series:
        return suid, None
    chosen = set()
    for se in series:
        if series_visible(se, study, c):
            uid = se.get('series_instance_uid')
            if uid:
                chosen.add(uid)
    for uid in list(chosen):
        chosen.update(ancestors_of(study, uid))
    if not chosen:
        return None
    return suid, sorted(chosen)


def build_selections_for_patient(studies, c, new_only=False):
    """Flatten a patient's study tree into a `selections` list for its
    RetrievalJob. `new_only` skips studies already stored locally."""
    out = []
    for study in studies or []:
        if new_only and study.get('already_local'):
            continue
        sel = select_study(study, c)
        if sel is None:
            continue
        suid, series_uids = sel
        out.append({
            'study_instance_uid': suid,
            'series_instance_uids': series_uids,
            'remote_patient_id': study.get('remote_patient_id'),
        })
    return out

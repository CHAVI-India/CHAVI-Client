"""Unit tests for instance-level selection math — pure functions over the
study-tree dict (the JSON shape stored on RetrievalBatchPatient.studies)."""
from django.test import TestCase

from dicom_server.services.instance_selection import (
    SelectionError, instance_ancestors, normalize_selection, sop_series_uid,
)

# ARIA-like study: one CT, one RTSTRUCT series with 2 struct sets, one
# RTPLAN series with 2 plans (shared series UID, different SOP UIDs), one
# RTDOSE series with 2 doses (each references one plan).
STUDY = {
    'study_instance_uid': '1.2.3',
    'series': [
        {'series_instance_uid': 'ct', 'series_description': 'CECT',
         'modality': 'CT', 'series_number': 1, 'instances': 196},
        {'series_instance_uid': 'ss', 'series_description':
         'ARIA RadOnc Structure Sets', 'modality': 'RTSTRUCT',
         'series_number': 13, 'instances': 2,
         'rt_instances': [
             {'sop_instance_uid': 'ss1', 'instance_number': '1',
              'structure_set_label': 'CT_FINAL',
              'referenced_series_uids': ['ct']},
             {'sop_instance_uid': 'ss2', 'instance_number': '2',
              'structure_set_label': 'Setup',
              'referenced_series_uids': ['ct']},
         ]},
        {'series_instance_uid': 'pl', 'series_description': 'ARIA RadOnc Plans',
         'modality': 'RTPLAN', 'series_number': 14, 'instances': 2,
         'rt_instances': [
             {'sop_instance_uid': 'p1', 'instance_number': '1',
              'rt_plan_label': 'final', 'approval_status': 'APPROVED',
              'referenced_structure_set_uids': ['ss1']},
             {'sop_instance_uid': 'p2', 'instance_number': '2',
              'rt_plan_label': 'final_v2', 'approval_status': 'UNAPPROVED',
              'referenced_structure_set_uids': ['ss1']},
         ]},
        {'series_instance_uid': 'ds', 'series_description': 'Eclipse Doses',
         'modality': 'RTDOSE', 'series_number': 15, 'instances': 2,
         'rt_instances': [
             {'sop_instance_uid': 'd1', 'instance_number': '1',
              'referenced_plan_uids': ['p1']},
             {'sop_instance_uid': 'd2', 'instance_number': '2',
              'referenced_plan_uids': ['p2']},
         ]},
    ],
}

# Struct set whose referenced image series is NOT in the study (orphan).
ORPHAN_STUDY = {
    'study_instance_uid': '9',
    'series': [
        {'series_instance_uid': 'ssX', 'modality': 'RTSTRUCT',
         'instances': 1,
         'rt_instances': [
             {'sop_instance_uid': 'sX', 'referenced_series_uids': ['nope']},
         ]},
    ],
}


class SopSeriesUidTests(TestCase):
    def test_plan_maps_to_its_containing_series(self):
        self.assertEqual(sop_series_uid(STUDY, 'p1'), 'pl')
        self.assertEqual(sop_series_uid(STUDY, 'd2'), 'ds')

    def test_unknown_sop_is_none(self):
        self.assertIsNone(sop_series_uid(STUDY, 'zzz'))
        self.assertIsNone(sop_series_uid(STUDY, ''))


class InstanceAncestorsTests(TestCase):
    def test_plan_pulls_struct_set_and_image_series(self):
        sops, seuids = instance_ancestors(STUDY, 'p1')
        self.assertEqual(sops, ['ss1'])
        self.assertEqual(seuids, ['ct'])

    def test_dose_pulls_plan_and_struct_set_and_image_series(self):
        sops, seuids = instance_ancestors(STUDY, 'd1')
        self.assertEqual(sops, ['p1', 'ss1'])
        self.assertEqual(seuids, ['ct'])

    def test_struct_set_pulls_only_its_image_series(self):
        sops, seuids = instance_ancestors(STUDY, 'ss1')
        self.assertEqual(sops, [])
        self.assertEqual(seuids, ['ct'])

    def test_orphan_struct_set_has_no_series_ancestors(self):
        sops, seuids = instance_ancestors(ORPHAN_STUDY, 'sX')
        self.assertEqual(sops, [])
        self.assertEqual(seuids, [])

    def test_unknown_sop_is_empty(self):
        self.assertEqual(instance_ancestors(STUDY, 'zzz'), ([], []))


class NormalizeSelectionTests(TestCase):
    def test_plan_selection_closes_under_ancestors_and_excludes_dose_series(self):
        self.assertEqual(
            normalize_selection(STUDY, None, ['p1']),
            {'series_uids': ['ct', 'pl', 'ss'], 'sop_uids': ['p1', 'ss1']},
        )

    def test_dose_selection_closes_through_plan(self):
        self.assertEqual(
            normalize_selection(STUDY, None, ['d1']),
            {'series_uids': ['ct', 'ds', 'pl', 'ss'],
             'sop_uids': ['d1', 'p1', 'ss1']},
        )

    def test_series_only_selection(self):
        self.assertEqual(
            normalize_selection(STUDY, ['ct'], None),
            {'series_uids': ['ct'], 'sop_uids': []},
        )

    def test_mixed_selection(self):
        self.assertEqual(
            normalize_selection(STUDY, ['ct'], ['p2']),
            {'series_uids': ['ct', 'pl', 'ss'], 'sop_uids': ['p2', 'ss1']},
        )

    def test_orphan_struct_set_still_pulls_its_own_series(self):
        self.assertEqual(
            normalize_selection(ORPHAN_STUDY, None, ['sX']),
            {'series_uids': ['ssX'], 'sop_uids': ['sX']},
        )

    def test_unknown_sop_raises(self):
        with self.assertRaises(SelectionError):
            normalize_selection(STUDY, None, ['zzz'])

    def test_unknown_series_raises(self):
        with self.assertRaises(SelectionError):
            normalize_selection(STUDY, ['nope'], None)

    def test_empty_selections_yield_empty_result(self):
        self.assertEqual(
            normalize_selection(STUDY, None, None),
            {'series_uids': [], 'sop_uids': []},
        )

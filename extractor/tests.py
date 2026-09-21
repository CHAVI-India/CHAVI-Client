from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from extractor.models import (
    ClientConfiguration, DatabaseField, DatabaseTable, EntityTypeChoices,
    ExtractedRecord, ExtractionJob, FileUpload, ProcessedText,
    RecordCreation, ResponseModel, ResponseModelTable, ResponseModelTableField,
)
from extractor.services.model_hierarchy import (
    ancestor_tables, build_table_tree, child_key, identity_field_names)
from extractor.services.pydantic_builder import PydanticModelBuilder
from extractor.services.instructor_extractor import InstructorExtractionService
from extractor.services.record_writer import RecordWriteError, _resolve_parent_fks
from extractor.services.patient_data import build_patient_data_tree


PATIENT_STEP = {'field': 'patient', 'model': 'client_app.patient',
                'pk_field': 'patient_id'}


def make_table(model_name, patient_path):
    """DatabaseTable for a client_app model with an explicit patient_path."""
    ct = ContentType.objects.get(app_label='client_app', model=model_name)
    return DatabaseTable.objects.create(
        clientapp_content_type=ct,
        clientapp_table_pk_field_name='pk',
        clientapp_table_fk_fields={'patient_path': patient_path} if patient_path else {},
    )


def make_field(table, name, **kwargs):
    return DatabaseField.objects.create(
        clientapp_database_table=table,
        clientapp_field_name=name,
        field_type=kwargs.pop('field_type', EntityTypeChoices.STRING),
        **kwargs,
    )


def make_response_model():
    client = ClientConfiguration.objects.create(
        llm_model_name='test-model', model_provider='ollama',
        model_api_key='x', model_base_url='http://localhost:11434')
    return ResponseModel.objects.create(client=client, name='test-rm')


class HierarchyTests(TestCase):
    def setUp(self):
        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.pathology = make_table('pathology', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.lesion = make_table('lesion', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.lesionresponse = make_table('lesionresponse', [
            {'field': 'lesion', 'model': 'client_app.lesion', 'pk_field': 'pk'},
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.symptom = make_table('symptom', [PATIENT_STEP])

    def test_ancestor_tables(self):
        self.assertEqual(ancestor_tables(self.pathology), [self.diagnosis])
        self.assertEqual(ancestor_tables(self.lesionresponse),
                         [self.lesion, self.diagnosis])
        self.assertEqual(ancestor_tables(self.symptom), [])

    def test_ancestors_never_include_patient_or_infra(self):
        names = {t.clientapp_content_type.model for t in
                 ancestor_tables(self.lesionresponse)}
        self.assertNotIn('patient', names)
        self.assertNotIn('dicomstudy', names)

    def test_identity_field_names(self):
        self.diagnosis.match_fields = [['diagnosis', 'diagnosis_date'],
                                       ['cancer_site', 'cancer_side']]
        self.assertEqual(
            set(identity_field_names(self.diagnosis)),
            {'diagnosis', 'diagnosis_date', 'cancer_site', 'cancer_side'})

    def test_child_key(self):
        self.assertEqual(child_key(self.pathology), 'pathology')
        self.assertEqual(child_key(self.lesionresponse), 'lesionresponse')

    def test_build_table_tree_nests_under_immediate_parent(self):
        rm = make_response_model()
        rmt_diag = ResponseModelTable.objects.create(
            response_model=rm, database_table=self.diagnosis)
        rmt_path = ResponseModelTable.objects.create(
            response_model=rm, database_table=self.pathology, auto_added=True)
        rmt_sym = ResponseModelTable.objects.create(
            response_model=rm, database_table=self.symptom)

        roots, children = build_table_tree(rm)
        self.assertEqual({r.id for r in roots}, {rmt_diag.id, rmt_sym.id})
        self.assertEqual(children, {rmt_diag.id: [rmt_path]})

    def test_build_table_tree_missing_parent_is_root(self):
        rm = make_response_model()
        rmt_path = ResponseModelTable.objects.create(
            response_model=rm, database_table=self.pathology)
        roots, children = build_table_tree(rm)
        self.assertEqual(roots, [rmt_path])
        self.assertEqual(children, {})


class ExtractionModelTests(TestCase):
    def setUp(self):
        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.pathology = make_table('pathology', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt_diag = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.diagnosis)
        self.rmt_path = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.pathology, auto_added=True)
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_diag,
            field=make_field(self.diagnosis, 'diagnosis_date'))
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_path,
            field=make_field(self.pathology, 'date_pathology'))

    def test_extraction_model_nests_children(self):
        model = PydanticModelBuilder.build_extraction_model(self.rm)
        self.assertEqual(set(model.model_fields), {'diagnosis'})

        inst = model(diagnosis=[{
            'diagnosis_date': '2024-01-01',
            'pathology': [{'date_pathology': '2024-02-02'}],
        }])
        rec = inst.diagnosis[0]
        self.assertEqual(rec.diagnosis_date, '2024-01-01')
        self.assertEqual(rec.pathology[0].date_pathology, '2024-02-02')

    def test_generated_code_nests_and_validates(self):
        code = PydanticModelBuilder.build_pydantic_model(self.rm)
        self.assertIn('pathology: Optional[List[Pathology]]', code)
        result = PydanticModelBuilder.validate_generated_code(code)
        self.assertTrue(result['valid'], result['errors'])

    def test_validation_flags_missing_parent(self):
        rm = make_response_model()
        ResponseModelTable.objects.create(
            response_model=rm, database_table=self.pathology)
        result = PydanticModelBuilder.validate_model_configuration(rm)
        self.assertFalse(result['valid'])
        self.assertTrue(any('diagnosis' in e for e in result['errors']))


class SaveAndWriteBackTests(TestCase):
    def setUp(self):
        from client_app.models import Patient, SiteConfiguration
        SiteConfiguration.objects.create(
            chavi_center_id='C1', center_name='Test Center')
        self.patient = Patient.objects.create(patient_id='P1')

        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.pathology = make_table('pathology', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt_diag = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.diagnosis)
        self.rmt_path = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.pathology, auto_added=True)
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_diag,
            field=make_field(self.diagnosis, 'diagnosis_date'))
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_path,
            field=make_field(self.pathology, 'date_pathology'))

        # The pathology.diagnosis FK marked as an internal relationship —
        # this is what _resolve_parent_fks resolves.
        make_field(
            self.pathology, 'diagnosis',
            field_validation={'is_relationship': True},
            relation_content_type=ContentType.objects.get(
                app_label='client_app', model='diagnosis'))

        self.user = User.objects.create(username='tester')
        self.upload = FileUpload.objects.create(
            patient_id=self.patient, file='scan.pdf')
        self.processed = ProcessedText.objects.create(file_upload=self.upload)
        self.job = ExtractionJob.objects.create(
            response_model=self.rm, processed_file=self.processed,
            extracted_by=self.user)

    def test_save_extraction_results_links_children(self):
        InstructorExtractionService.save_extraction_results(
            self.job,
            {'diagnosis': [{'diagnosis_date': '2024-01-01',
                            'pathology': [{'date_pathology': '2024-02-02'}]}]},
            self.user)

        parent = ExtractedRecord.objects.get(database_table=self.diagnosis)
        child = ExtractedRecord.objects.get(database_table=self.pathology)
        self.assertEqual(child.parent_record, parent)
        self.assertEqual(child.record_index, 0)

    def test_parent_fk_uses_created_record(self):
        parent = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.diagnosis)
        child = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.pathology,
            parent_record=parent)
        RecordCreation.objects.create(
            extraction_job=self.job, database_table=self.diagnosis,
            extracted_record=parent, created_record_pk='77',
            record_created=True, record_created_by=self.user)

        fks = _resolve_parent_fks(child)
        self.assertEqual(fks['diagnosis_id'], '77')

    def test_parent_fk_links_unique_existing_match(self):
        parent = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.diagnosis)
        child = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.pathology,
            parent_record=parent)
        match = {'pk': 'D9', 'matched_on': ['diagnosis'], 'row': None}
        with patch('extractor.services.record_writer.find_duplicate_candidates',
                   return_value=[match]):
            fks = _resolve_parent_fks(child)
        self.assertEqual(fks['diagnosis_id'], 'D9')

    def test_parent_fk_errors_without_match(self):
        parent = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.diagnosis)
        child = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.pathology,
            parent_record=parent)
        with patch('extractor.services.record_writer.find_duplicate_candidates',
                   return_value=[]):
            with self.assertRaises(RecordWriteError):
                _resolve_parent_fks(child)

    def test_parent_fk_errors_on_ambiguous_match(self):
        parent = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.diagnosis)
        child = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.pathology,
            parent_record=parent)
        matches = [{'pk': 'D9', 'matched_on': [], 'row': None},
                   {'pk': 'D10', 'matched_on': [], 'row': None}]
        with patch('extractor.services.record_writer.find_duplicate_candidates',
                   return_value=matches):
            with self.assertRaises(RecordWriteError):
                _resolve_parent_fks(child)


class PatientDataTreeTests(TestCase):
    def setUp(self):
        from client_app.models import Patient, SiteConfiguration
        SiteConfiguration.objects.create(
            chavi_center_id='C1', center_name='Test Center')
        self.patient = Patient.objects.create(patient_id='P1')

        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.pathology = make_table('pathology', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        rm = make_response_model()
        self.user = User.objects.create(username='tester')
        upload = FileUpload.objects.create(
            patient_id=self.patient, file='scan.pdf')
        processed = ProcessedText.objects.create(file_upload=upload)
        self.job = ExtractionJob.objects.create(
            response_model=rm, processed_file=processed,
            extracted_by=self.user)

        self.parent_rec = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.diagnosis,
            record_index=0)
        self.child_rec = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.pathology,
            parent_record=self.parent_rec, record_index=0)

    def test_child_record_nests_under_parent(self):
        roots = build_patient_data_tree(self.patient)
        self.assertEqual(len(roots), 1)
        diag_node = roots[0]
        self.assertEqual(
            diag_node['table'].clientapp_content_type.model, 'diagnosis')
        self.assertEqual(len(diag_node['records']), 1)

        rec = diag_node['records'][0]
        self.assertEqual(rec['record'].id, self.parent_rec.id)
        self.assertEqual(len(rec['child_nodes']), 1)

        path_node = rec['child_nodes'][0]
        self.assertEqual(
            path_node['table'].clientapp_content_type.model, 'pathology')
        self.assertEqual(
            [r['record'].id for r in path_node['records']],
            [self.child_rec.id])

    def test_orphan_child_stays_at_table_level(self):
        orphan = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.pathology,
            record_index=1)
        roots = build_patient_data_tree(self.patient)
        # diagnosis root + pathology node nested under it by depth
        diag_node = roots[0]
        path_nodes = diag_node['children']
        self.assertEqual(len(path_nodes), 1)
        self.assertEqual(
            [r['record'].id for r in path_nodes[0]['records']], [orphan.id])

    @staticmethod
    def _record_ids(nodes):
        ids = set()
        for n in nodes:
            for r in n['records']:
                ids.add(r['record'].id)
                ids |= PatientDataTreeTests._record_ids(r['child_nodes'])
            ids |= PatientDataTreeTests._record_ids(n['children'])
        return ids

    def test_build_job_data_tree_scopes_to_job(self):
        from extractor.services.patient_data import build_job_data_tree
        other_job = ExtractionJob.objects.create(
            response_model=self.job.response_model,
            processed_file=self.job.processed_file,
            extracted_by=self.user)
        other_rec = ExtractedRecord.objects.create(
            extraction_job=other_job, database_table=self.pathology,
            record_index=0)

        ids = self._record_ids(build_job_data_tree(self.job))
        self.assertIn(self.parent_rec.id, ids)
        self.assertIn(self.child_rec.id, ids)
        self.assertNotIn(other_rec.id, ids)

    def test_build_records_data_tree_no_patient(self):
        from extractor.services.patient_data import build_records_data_tree
        records = ExtractedRecord.objects.filter(extraction_job=self.job)
        roots = build_records_data_tree(records, None)
        diag_node = roots[0]
        # no patient -> no existing-row comparison and no dup counts
        self.assertEqual(diag_node['existing'], [])
        self.assertEqual(
            [r['dup_count'] for r in diag_node['records']], [0])


class LookupMiningTests(TestCase):
    """Snippet-mining pre-pass: batched LLM call -> embedding match -> options."""

    def setUp(self):
        from lookup.models import LookupLaterality
        from extractor.models import EmbeddingConfiguration

        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.pathology = make_table('pathology', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt_diag = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.diagnosis)
        self.rmt_path = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.pathology, auto_added=True)

        lookup_ct = ContentType.objects.get_for_model(LookupLaterality)
        self.hist_field = make_field(
            self.pathology, 'histological_type',
            lookup_field=True, lookup_content_type=lookup_ct,
            lookup_table_pk_field_name='code',
            lookup_table_value_field_name='label',
            help_text='The primary histological classification')
        self.margin_field = make_field(
            self.pathology, 'margin_status',
            lookup_field=True, lookup_content_type=lookup_ct,
            lookup_table_pk_field_name='code',
            lookup_table_value_field_name='label',
            help_text='Select the margin status')
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_path, field=self.hist_field)
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_path, field=self.margin_field)

        self.embed_config = EmbeddingConfiguration.objects.create(
            model_name='test-embed', embedding_dimension=384,
            candidate_threshold=0.5, similarity_threshold=0.7,
            top_k_results=2, is_active=True)

    def test_iter_lookup_fields(self):
        pairs = list(InstructorExtractionService._iter_lookup_fields(self.rm))
        self.assertEqual(
            {f.clientapp_field_name for _, f in pairs},
            {'histological_type', 'margin_status'})
        self.assertTrue(all(mt == self.rmt_path for mt, _ in pairs))

    def test_schema_line_uses_resolved_options(self):
        opts = {self.hist_field.id: [
            {'code': 'XH4CR9', 'label': 'Squamous cell carcinoma, keratinizing, NOS',
             'similarity': 0.88}]}
        line = InstructorExtractionService._field_schema_line(
            self.hist_field, resolved_options=opts)
        self.assertIn(
            'Valid Options (most relevant): Squamous cell carcinoma, keratinizing, NOS',
            line)

    def test_schema_line_empty_options_falls_back(self):
        line = InstructorExtractionService._field_schema_line(
            self.hist_field, resolved_options={})
        self.assertIn('Lookup Table: lookuplaterality', line)

    def test_resolve_dedupes_by_code_keeps_best(self):
        fake = [
            [{'code': 'A', 'label': 'a', 'similarity': 0.6},
             {'code': 'B', 'label': 'b', 'similarity': 0.9}],
            [{'code': 'A', 'label': 'a', 'similarity': 0.8}],
        ]
        with patch(
                'extractor.services.instructor_extractor.SemanticSearchService.find_similar_lookup_entries',
                side_effect=fake):
            opts = InstructorExtractionService.resolve_snippets_to_options(
                self.hist_field, ['s1', 's2'])
        # sorted by similarity, deduped, capped at top_k_results=2
        self.assertEqual([o['code'] for o in opts], ['B', 'A'])
        self.assertEqual(opts[1]['similarity'], 0.8)

    def test_mine_lookup_snippets_maps_entries_to_fields(self):
        from extractor.services.instructor_extractor import (
            FieldSnippetEntry, LookupSnippetMap)

        result = LookupSnippetMap(entries=[
            FieldSnippetEntry(table='Pathology', field='histological_type',
                              snippets=['squamous cell carcinoma']),
            FieldSnippetEntry(table='bogus', field='nope', snippets=['x']),
        ])
        completion = type('C', (), {'usage': type('U', (), {'total_tokens': 42})()})()
        client = type('FakeClient', (), {})()
        client.chat = type('Chat', (), {})()
        client.chat.completions = type('Comp', (), {})()
        client.chat.completions.create_with_completion = lambda **kw: (result, completion)

        fields = list(InstructorExtractionService._iter_lookup_fields(self.rm))
        cfg = self.rm.client
        snippet_map, tokens = InstructorExtractionService.mine_lookup_snippets(
            client, fields, 'doc text', cfg)

        self.assertEqual(
            snippet_map,
            {('pathology', 'histological_type'): ['squamous cell carcinoma']})
        self.assertEqual(tokens, 42)

    def test_mine_lookup_options_degrades_on_error(self):
        with patch.object(
                InstructorExtractionService, 'mine_lookup_snippets',
                side_effect=RuntimeError('llm down')):
            resolved, tokens = InstructorExtractionService.mine_lookup_options(
                object(), self.rm, 'doc', self.rm.client)
        self.assertEqual(resolved, {})
        self.assertEqual(tokens, 0)

    def test_mine_lookup_options_resolves_per_field(self):
        with patch.object(
                InstructorExtractionService, 'mine_lookup_snippets',
                return_value=({('pathology', 'histological_type'): ['snippet']}, 7)), \
             patch.object(
                 InstructorExtractionService, 'resolve_snippets_to_options',
                 return_value=[{'code': 'X', 'label': 'x', 'similarity': 0.9}]):
            resolved, tokens = InstructorExtractionService.mine_lookup_options(
                object(), self.rm, 'doc', self.rm.client)
        self.assertEqual(tokens, 7)
        self.assertEqual(list(resolved), [self.hist_field.id])
        self.assertEqual(resolved[self.hist_field.id][0]['code'], 'X')

    def test_lookup_validator_enforces_labels_via_context(self):
        from lookup.models import LookupLaterality
        from pydantic import ValidationError

        LookupLaterality.objects.create(code='L', label='Left')
        LookupLaterality.objects.create(code='R', label='Right')
        # diagnosis needs one field for the extraction model to build
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_diag,
            field=make_field(self.diagnosis, 'diagnosis_date'))

        rules = InstructorExtractionService.build_lookup_rules(self.rm, {})
        self.assertIn('left', rules['pathology.histological_type']['allowed'])
        self.assertIn('right', rules['pathology.histological_type']['allowed'])

        model = PydanticModelBuilder.build_extraction_model(self.rm)
        ctx = {PydanticModelBuilder.LOOKUP_CONTEXT_KEY: rules}
        bad = {'diagnosis': [{'pathology': [{'histological_type': 'Bogus'}]}]}

        with self.assertRaises(ValidationError):
            model.model_validate(bad, context=ctx)

        ok = model.model_validate(
            {'diagnosis': [{'pathology': [{'histological_type': 'left'}]}]},
            context=ctx)
        self.assertEqual(ok.diagnosis[0].pathology[0].histological_type, 'left')

        # no context -> unconstrained (wizard preview path)
        model.model_validate(bad)

    def test_lookup_rules_carry_mined_candidates(self):
        from lookup.models import LookupLaterality

        LookupLaterality.objects.create(code='L', label='Left')
        resolved = {self.hist_field.id: [
            {'code': 'L', 'label': 'Left', 'similarity': 0.9}]}
        rules = InstructorExtractionService.build_lookup_rules(self.rm, resolved)
        self.assertEqual(
            rules['pathology.histological_type']['candidates'], ['Left'])

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from extractor.models import (
    ClientConfiguration, DatabaseField, DatabaseTable, EntityTypeChoices,
    ExtractedRecord, ExtractionJob, ExtractionResult, FileUpload, ProcessedText,
    RecordCreation, ResponseModel, ResponseModelTable, ResponseModelTableField,
)
from extractor.services.model_hierarchy import (
    ancestor_tables, build_table_tree, child_key, identity_field_names)
from extractor.services.pydantic_builder import PydanticModelBuilder
from extractor.services.instructor_extractor import InstructorExtractionService
from extractor.services.record_writer import RecordWriteError, _resolve_parent_fks, effective_result_value
from extractor.services.review import classify_review, get_review_context, prepare_review, approve_review
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
        # The orphan is shown at table level; depth alone must not imply a parent.
        self.assertEqual(
            [node['table'].clientapp_content_type.model for node in roots],
            ['diagnosis', 'pathology'])
        path_node = roots[1]
        self.assertEqual(
            [r['record'].id for r in path_node['records']], [orphan.id])

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


class StagedPipelineTests(TestCase):
    """Approval-gated pipeline: stage_prepare -> stage_mine -> stage_extract,
    driven by the job status and the advance_extraction_job dispatcher."""

    def setUp(self):
        from lookup.models import LookupLaterality

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
        lookup_ct = ContentType.objects.get_for_model(LookupLaterality)
        self.hist_field = make_field(
            self.pathology, 'histological_type',
            lookup_field=True, lookup_content_type=lookup_ct,
            lookup_table_pk_field_name='code',
            lookup_table_value_field_name='label')
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_path, field=self.hist_field)

        self.user = User.objects.create(username='tester')
        upload = FileUpload.objects.create(file='scan.pdf')
        self.processed = ProcessedText.objects.create(
            file_upload=upload, content_length=5)
        self.job = ExtractionJob.objects.create(
            response_model=self.rm, processed_file=self.processed,
            extracted_by=self.user)
        self.content = 'pathology report: squamous cell carcinoma, left side'

    @staticmethod
    def _fake_client(create_fn=None, mining_result=None):
        completion = type('C', (), {'usage': type('U', (), {'total_tokens': 11})()})()
        fake = type('FakeClient', (), {})()
        fake.chat = type('Chat', (), {})()
        fake.chat.completions = type('Comp', (), {})()
        fake.chat.completions.create_with_completion = (
            create_fn or (lambda **kw: (mining_result, completion)))
        return fake

    def test_stage_prepare_writes_prompt_and_awaits(self):
        result = InstructorExtractionService.stage_prepare(self.job, self.content)
        self.assertIsNone(result)
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status, 'awaiting_mining')
        self.assertEqual(len(self.job.stage_trace), 1)
        entry = self.job.stage_trace[0]
        self.assertEqual((entry['stage'], entry['kind']), ('mining', 'prompt'))
        self.assertIn('histological_type', entry['messages'][0]['content'])
        self.assertIn(self.content, entry['messages'][0]['content'])

    def test_stage_mine_builds_extraction_prompt_and_awaits(self):
        from extractor.services.instructor_extractor import (
            FieldSnippetEntry, LookupSnippetMap)
        InstructorExtractionService.stage_prepare(self.job, self.content)

        mined = LookupSnippetMap(entries=[
            FieldSnippetEntry(table='Pathology', field='histological_type',
                              snippets=['squamous cell carcinoma'])])
        fake = self._fake_client(mining_result=mined)
        with patch.object(InstructorExtractionService, '_get_llm_client',
                          return_value=fake):
            result = InstructorExtractionService.stage_mine(self.job, self.content)

        self.assertIsNone(result)
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status, 'awaiting_extraction')
        kinds = [(e['stage'], e['kind']) for e in self.job.stage_trace]
        self.assertEqual(kinds, [
            ('mining', 'prompt'), ('mining', 'result'), ('extraction', 'prompt')])
        self.assertTrue(self.job.prompt_snapshot)
        self.assertIn(
            'squamous cell carcinoma',
            self.job.stage_trace[1]['snippets']['pathology.histological_type'])

    def test_stage_mine_rechecks_empty_fields(self):
        from extractor.services.instructor_extractor import (
            FieldSnippetEntry, LookupSnippetMap)
        InstructorExtractionService.stage_prepare(self.job, self.content)

        calls = []
        completion = type('C', (), {'usage': type('U', (), {'total_tokens': 5})()})()
        def create(**kw):
            calls.append(kw)
            if len(calls) == 1:
                return LookupSnippetMap(entries=[]), completion
            return LookupSnippetMap(entries=[
                FieldSnippetEntry(table='pathology', field='histological_type',
                                  snippets=['squamous cell carcinoma'])]), completion
        fake = self._fake_client(create_fn=create)
        with patch.object(InstructorExtractionService, '_get_llm_client',
                          return_value=fake):
            InstructorExtractionService.stage_mine(self.job, self.content)

        self.assertEqual(len(calls), 2)  # mining + empty-field recheck
        self.job.refresh_from_db()
        mine_result = self.job.stage_trace[1]
        self.assertIn(
            'squamous cell carcinoma',
            mine_result['snippets']['pathology.histological_type'])
        self.assertIn('pathology.histological_type',
                      mine_result['rechecked_fields'])

    def test_stage_extract_sends_approved_messages_and_completes(self):
        InstructorExtractionService.stage_prepare(self.job, self.content)
        # Park at awaiting_extraction with a stored prompt + mining result
        self.job.extraction_status = 'awaiting_extraction'
        self.job.stage_trace.append({
            'stage': 'mining', 'kind': 'result', 'resolved_options': {},
            'snippets': {}, 'tokens': 3, 'at': '2026-01-01T00:00:00'})
        self.job.stage_trace.append({
            'stage': 'extraction', 'kind': 'prompt',
            'messages': [{'role': 'user', 'content': 'APPROVED-PROMPT'}],
            'at': '2026-01-01T00:00:00'})
        self.job.save()

        captured = {}
        completion = type('C', (), {'usage': type('U', (), {'total_tokens': 42})()})()
        def create(**kw):
            captured.update(kw)
            return (kw['response_model'].model_validate(
                {'diagnosis': [{'diagnosis_date': '2024-01-01'}]}), completion)
        fake = self._fake_client(create_fn=create)

        with patch.object(InstructorExtractionService, '_get_llm_client',
                          return_value=fake):
            result = InstructorExtractionService.stage_extract(self.job, self.content)

        self.assertTrue(result['success'])
        # The approved prompt went out verbatim — not a rebuild
        self.assertEqual(captured['messages'],
                         [{'role': 'user', 'content': 'APPROVED-PROMPT'}])
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status, 'completed')
        self.assertEqual(self.job.tokens_used, 45)
        self.assertTrue(ExtractionResult.objects.filter(
            extraction_job=self.job).exists())
        self.assertEqual(
            self.job.stage_trace[-1]['coverage']['extracted'], 1)

    def test_stage_mine_fails_on_changed_content(self):
        InstructorExtractionService.stage_prepare(self.job, self.content)
        result = InstructorExtractionService.stage_mine(
            self.job, 'different document text')
        self.assertFalse(result['success'])
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status, 'failed')

    def test_advance_dispatches_stage_by_status(self):
        from extractor.tasks import advance_extraction_job

        for status, method in [
                ('pending', 'stage_prepare'),
                ('awaiting_mining', 'stage_mine'),
                ('awaiting_extraction', 'stage_extract')]:
            self.job.extraction_status = status
            self.job.save()
            with patch.object(InstructorExtractionService, method,
                              return_value=None) as m:
                advance_extraction_job(self.job.id)
            m.assert_called_once()

        self.job.extraction_status = 'completed'
        self.job.save()
        with patch.object(InstructorExtractionService, 'stage_extract') as m:
            advance_extraction_job(self.job.id)
        m.assert_not_called()

    def test_get_or_create_job_reuses_awaiting_job(self):
        self.job.extraction_status = 'awaiting_mining'
        self.job.save()
        job2, created = InstructorExtractionService.get_or_create_job(
            self.processed, self.rm, self.user)
        self.assertFalse(created)
        self.assertEqual(job2, self.job)

    def test_continue_dispatches_only_when_awaiting(self):
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(
            codename='add_extractionjob', content_type__app_label='extractor')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)

        self.job.extraction_status = 'awaiting_mining'
        self.job.save()
        with patch('extractor.views.advance_extraction_job') as adv:
            resp = self.client.post(
                f'/extractor/extraction/jobs/{self.job.id}/continue/')
        adv.delay.assert_called_once_with(self.job.id)
        self.assertEqual(resp.status_code, 302)

        self.job.extraction_status = 'completed'
        self.job.save()
        with patch('extractor.views.advance_extraction_job') as adv:
            resp = self.client.post(
                f'/extractor/extraction/jobs/{self.job.id}/continue/')
        adv.delay.assert_not_called()
        self.assertEqual(resp.status_code, 302)

    def test_continue_cancel_marks_skipped(self):
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(
            codename='add_extractionjob', content_type__app_label='extractor')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)

        self.job.extraction_status = 'awaiting_extraction'
        self.job.save()
        with patch('extractor.views.advance_extraction_job') as adv:
            self.client.post(
                f'/extractor/extraction/jobs/{self.job.id}/continue/',
                {'action': 'cancel'})
        adv.delay.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status, 'skipped')


class ReviewValueTests(TestCase):
    def make_result(self, **kwargs):
        table = make_table('diagnosis', [PATIENT_STEP])
        field = make_field(table, 'diagnosis_date')
        extracted_data = kwargs.pop('extracted_data', '')
        return ExtractionResult(
            extraction_job_id=0,
            database_field=field,
            extracted_data=extracted_data,
            **kwargs)

    def test_clear_does_not_restore_original(self):
        result = self.make_result(extracted_data='12.50', data_edited=True,
                                  edited_data='')
        self.assertEqual(effective_result_value(result), '')

    def test_filled_missing_value_has_its_own_flag(self):
        change = classify_review(None, Decimal('12.50'),
                                 source_state='not_found', disposition='apply')
        self.assertEqual(change['data_accuracy'], 'inaccurate')
        self.assertEqual(change['review_change'], 'filled_missing')

    def test_equivalent_value_is_accepted(self):
        change = classify_review(Decimal('12.50'), Decimal('12.5'),
                                 source_state='extracted', disposition='apply')
        self.assertEqual(change['data_accuracy'], 'accurate')
        self.assertEqual(change['review_change'], 'accepted')

    def test_zero_and_false_are_values_not_missing(self):
        self.assertEqual(classify_review(None, 0, source_state='not_found',
                                       disposition='apply')['review_change'],
                         'filled_missing')
        self.assertEqual(classify_review(None, False, source_state='not_found',
                                       disposition='apply')['review_change'],
                         'filled_missing')


class ReviewDropdownTests(TestCase):
    def setUp(self):
        from client_app.models import Patient, SiteConfiguration
        from lookup.models import LookupLaterality

        SiteConfiguration.objects.create(chavi_center_id='C1', center_name='Test Center')
        self.patient = Patient.objects.create(patient_id='P1')
        self.user = User.objects.create_superuser(username='review-ui', password='test-password')
        self.table = make_table('diagnosis', [PATIENT_STEP])
        self.field = make_field(
            self.table, 'cancer_side', lookup_field=True,
            lookup_content_type=ContentType.objects.get_for_model(LookupLaterality),
            lookup_table_pk_field_name='code', lookup_table_value_field_name='label')
        self.right = LookupLaterality.objects.create(code='R', label='Right')
        LookupLaterality.objects.create(code='L', label='Left')
        upload = FileUpload.objects.create(patient_id=self.patient, file='synthetic.pdf')
        self.job = ExtractionJob.objects.create(
            response_model=make_response_model(),
            processed_file=ProcessedText.objects.create(file_upload=upload),
            extracted_by=self.user, extraction_status='completed')
        self.record = ExtractedRecord.objects.create(extraction_job=self.job, database_table=self.table)
        self.result = ExtractionResult.objects.create(
            extraction_job=self.job, record=self.record, database_field=self.field,
            extracted_data='{"code": "R", "label": "Right"}')

    def test_review_fields_follow_model_order_in_parent_and_child_records(self):
        from extractor.services.patient_data import build_job_data_tree

        make_field(self.table, 'diagnosis_date')
        make_field(self.table, 'cancer_system')
        pathology = make_table('pathology', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        for name in ('tumor_focality', 'specimen_type', 'date_pathology'):
            make_field(pathology, name)
        ExtractedRecord.objects.create(extraction_job=self.job, database_table=pathology,
                                       parent_record=self.record)
        parent = build_job_data_tree(self.job)[0]['records'][0]
        self.assertEqual([row['field'].clientapp_field_name for row in parent['detail']],
                         ['cancer_system', 'diagnosis_date', 'cancer_side'])
        child = parent['child_nodes'][0]['records'][0]
        self.assertEqual([row['field'].clientapp_field_name for row in child['detail']],
                         ['date_pathology', 'specimen_type', 'tumor_focality'])

    def test_selecting_same_lookup_code_is_accurate_after_an_earlier_edit(self):
        from client_app.models import Diagnosis
        from extractor.services.review import _classification, _result_payload

        self.result.data_edited = True
        self.result.edited_data = '{"code": "L", "label": "Left"}'
        decision = _classification(self.field, Diagnosis._meta.get_field('cancer_side'),
                                   _result_payload(self.result), 'R', 'apply')
        self.assertEqual(decision['review_change'], 'accepted')
        self.assertEqual(decision['data_accuracy'], 'accurate')
        self.assertFalse(decision['data_edited'])

    def test_lookup_endpoint_lists_searches_and_pages_real_choices(self):
        from lookup.models import LookupLaterality
        from extractor.services.review import review_options

        data = review_options(self.job, self.user, record_id=self.record.id,
                              kind='lookup', field_id=self.field.id)
        self.assertTrue({'L', 'R'}.issubset({row['id'] for row in data['results']}))
        data = review_options(self.job, self.user, record_id=self.record.id,
                              kind='lookup', field_id=self.field.id, query='right')
        self.assertIn('R', [row['id'] for row in data['results']])
        self.assertTrue(all('right' in row['text'].lower() for row in data['results']))
        LookupLaterality.objects.bulk_create([
            LookupLaterality(code=f'T{i:02}', label=f'Test {i}') for i in range(30)])
        data = review_options(self.job, self.user, record_id=self.record.id,
                              kind='lookup', field_id=self.field.id, query='Test')
        self.assertEqual(len(data['results']), 25)
        self.assertTrue(data['pagination']['more'])

    def test_extracted_lookup_is_separate_from_empty_correction_control(self):
        import re
        from django.template.loader import render_to_string
        from extractor.services.patient_data import build_job_data_tree

        with patch('extractor.services.patient_data._lookup_options_map',
                   side_effect=AssertionError('Do not load complete lookup tables')):
            tree = build_job_data_tree(self.job)
        html = render_to_string('extractor/record_grid_node.html',
                                {'node': tree[0], 'level': 0})
        self.assertRegex(html, r'data-extracted-value[^>]*>Right \(R\)')
        self.assertIn('data-baseline="R"', html)
        control = re.search(r'<select[^>]*data-field-id[^>]*>(.*?)</select>', html, re.S).group(1)
        self.assertNotIn('value="R" selected', control)
        self.assertIn('<option value="">', control)

    def test_lookup_rejects_unrelated_or_nonlookup_field(self):
        from extractor.services.review import review_options, ReviewValidationError

        other = make_field(self.table, 'diagnosis_date')
        with self.assertRaises(ReviewValidationError):
            review_options(self.job, self.user, record_id=self.record.id,
                           kind='lookup', field_id=other.id)


class ReviewApprovalServiceTests(TestCase):
    def setUp(self):
        from client_app.models import Patient, SiteConfiguration
        from django.contrib.auth.models import Permission

        SiteConfiguration.objects.create(
            chavi_center_id='C1', center_name='Test Center')
        self.patient = Patient.objects.create(patient_id='P1')
        self.table = make_table('patientassessment', [PATIENT_STEP])
        self.patient_field = make_field(
            self.table, 'patient',
            field_validation={'is_relationship': True},
            relation_content_type=ContentType.objects.get(
                app_label='client_app', model='patient'))
        self.date_field = make_field(self.table, 'date_assessment',
                                     field_type=EntityTypeChoices.DATE)
        self.rm = make_response_model()
        self.user = User.objects.create(username='reviewer')
        for codename in (
                'view_extractionjob', 'view_extractionresult',
                'change_extractionresult', 'add_recordcreation',
                'add_patientassessment'):
            self.user.user_permissions.add(Permission.objects.get(codename=codename))
        upload = FileUpload.objects.create(patient_id=self.patient, file='scan.pdf')
        processed = ProcessedText.objects.create(file_upload=upload)
        self.job = ExtractionJob.objects.create(
            response_model=self.rm, processed_file=processed,
            extracted_by=self.user, extraction_status='completed')
        self.record = ExtractedRecord.objects.create(
            extraction_job=self.job, database_table=self.table)
        self.result = ExtractionResult.objects.create(
            extraction_job=self.job, database_field=self.date_field,
            record=self.record, extracted_data='', result_state='not_found')

    def payload(self):
        token = get_review_context(self.job, self.user)['source_token']
        return {
            'schema_version': 1,
            'job_revision': self.job.review_revision,
            'source_token': token,
            'records': [{
                'id': self.record.id,
                'operation': 'create',
                'parents': {},
                'fields': {str(self.date_field.id): {'action': 'apply', 'value': '2024-01-01'}},
            }],
        }

    def test_preview_then_approval_saves_record_and_history(self):
        from client_app.models import PatientAssessment
        import uuid

        payload = self.payload()
        batch = prepare_review(self.job, self.user, payload, uuid.uuid4())
        self.assertEqual(PatientAssessment.objects.count(), 0)
        self.assertEqual(batch.status, 'pending')

        approved = approve_review(batch.id, self.user, confirm=True,
                                  acknowledge_duplicates=False)
        self.assertEqual(approved.status, 'approved')
        saved = PatientAssessment.objects.get()
        self.assertEqual(str(saved.patient_id), str(self.patient.pk))
        self.assertEqual(saved.date_assessment.isoformat(), '2024-01-01')
        self.result.refresh_from_db()
        self.assertEqual(self.result.data_accuracy, 'inaccurate')
        self.assertEqual(self.result.review_change, 'filled_missing')
        self.assertTrue(approved.receipt)
        self.job.refresh_from_db()
        self.assertEqual(self.job.review_revision, 1)

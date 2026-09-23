from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import SimpleTestCase, TestCase

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


class InferenceContractTests(SimpleTestCase):
    def setUp(self):
        from types import SimpleNamespace

        table = DatabaseTable(clientapp_content_type=ContentType(
            app_label='client_app', model='patientassessment'))
        self.rm = ResponseModel(name='offline')
        self.table = ResponseModelTable(id=1, database_table=table)
        self.fields = [DatabaseField(
            clientapp_database_table=table, clientapp_field_name=name, field_type=kind,
            field_validation=validation) for name, kind, validation in (
                ('count', 'int', {'min_value': 0}),
                ('measurement', 'float', {'max_digits': 6, 'decimal_places': 2}),
                ('present', 'bool', {}))]
        query = Mock()
        query.select_related.return_value.order_by.return_value = query
        query.exists.return_value = True
        query.__iter__ = Mock(side_effect=lambda: iter(
            [SimpleNamespace(field=f) for f in self.fields]))
        self.enterContext(patch('extractor.services.pydantic_builder.build_table_tree',
                                return_value=([self.table], {})))
        self.enterContext(patch.object(ResponseModelTable.objects, 'filter', return_value=query))
        self.enterContext(patch.object(ResponseModelTableField.objects, 'filter', return_value=query))
        self.source = 'No events. The finding is absent. Measurement was not assessed.'
        self.record = {'count': 0, 'measurement': None, 'present': False,
                       'field_assessments': [
                           {'field': 'count', 'basis': 'clinical_inference',
                            'quotes': ['No events.'], 'rationale': 'Zero is inferred.'},
                           {'field': 'measurement', 'basis': 'unknown', 'quotes': [],
                            'rationale': 'Not assessed.'},
                           {'field': 'present', 'basis': 'inferred',
                            'quotes': ['The finding is absent.'], 'rationale': 'Absent finding.'}]}
        self.model = PydanticModelBuilder.build_extraction_model(self.rm)

    def parse(self, record=None, source=None):
        return self.model.model_validate({'patientassessment': [record or self.record]},
                                         context={'source_text': self.source if source is None else source})

    def test_runtime_schema_and_scalar_types(self):
        rec = self.parse().patientassessment[0]
        self.assertEqual(rec.count, 0)
        self.assertIs(rec.present, False)
        self.assertIsNone(rec.measurement)
        self.assertEqual(len(rec.field_assessments), 3)
        self.assertIn('field_assessments', self.model.model_json_schema()['$defs']['patientassessment']['required'])

    def test_runtime_rejects_invalid_assessments(self):
        from copy import deepcopy
        from pydantic import ValidationError

        changes = [
            lambda r: r.pop('field_assessments'),
            lambda r: r['field_assessments'].pop(),
            lambda r: r['field_assessments'].append(r['field_assessments'][0]),
            lambda r: r['field_assessments'][0].update(field='other'),
            lambda r: r['field_assessments'][0].update(quotes=['invented']),
            lambda r: r['field_assessments'][0].update(basis='explicit', quotes=[]),
            lambda r: r['field_assessments'][0].update(quotes=[' ']),
            lambda r: r['field_assessments'][0].update(quotes=['x' * 401]),
            lambda r: r['field_assessments'][0].update(quotes=['No events.'] * 4),
            lambda r: r['field_assessments'][0].update(rationale=' '),
            lambda r: r['field_assessments'][0].update(rationale='x' * 401),
            lambda r: r['field_assessments'][0].update(basis='unknown'),
            lambda r: r['field_assessments'][0].update(extra='untrusted'),
            lambda r: r['field_assessments'][1].update(basis='explicit'),
            lambda r: r['field_assessments'][2].update(basis='calculated'),
            lambda r: r.update(count=1),
            lambda r: r.update(count=-1),
            lambda r: r.update(present=True),
        ]
        for index, change in enumerate(changes):
            record = deepcopy(self.record)
            change(record)
            with self.subTest(case=index), self.assertRaises(ValidationError):
                self.parse(record)
        with self.assertRaises(ValidationError):
            self.parse(source='')

    def test_generated_schema_and_validation_match_runtime(self):
        from pydantic import ValidationError

        code = PydanticModelBuilder.build_pydantic_model(self.rm)
        self.assertTrue(PydanticModelBuilder.validate_generated_code(code)['valid'])
        namespace = {}
        exec(code, namespace)
        model = namespace['OfflineModel']
        parsed = model.model_validate({'patientassessment': [self.record]},
                                      context={'source_text': self.source})
        self.assertEqual(parsed.model_dump(), self.parse().model_dump())
        with self.assertRaises(ValidationError):
            model.model_validate({'patientassessment': [self.record]}, context={'source_text': ''})

    def test_textual_inference_needs_reason_not_quote(self):
        self.record['field_assessments'][0].update(
            quotes=[], rationale='No events in this specimen implies zero events.')
        self.assertEqual(self.parse().patientassessment[0].field_assessments[0].quotes, [])

    def test_legacy_and_reserved_field(self):
        legacy = PydanticModelBuilder.build_extraction_model(self.rm, include_field_assessments=False)
        self.assertEqual(legacy(patientassessment=[{'count': 0}]).patientassessment[0].count, 0)
        self.fields[0].clientapp_field_name = 'field_assessments'
        for builder in (PydanticModelBuilder.build_extraction_model, PydanticModelBuilder.build_pydantic_model):
            with self.assertRaisesMessage(ValueError, 'reserved'):
                builder(self.rm)

    def test_explicit_and_calculated_preserve_decimal(self):
        self.record['measurement'] = '12.50'
        self.record['field_assessments'][1].update(
            basis='calculated', quotes=['25 divided by 2.'], rationale='25 / 2 = 12.50.')
        self.record['present'] = True
        self.record['field_assessments'][2].update(basis='explicit', rationale='')
        parsed = self.parse(source=self.source + ' 25 divided by 2.').patientassessment[0]
        self.assertEqual(parsed.measurement, Decimal('12.50'))
        self.assertIs(parsed.present, True)


    def test_prompt_is_generic_and_has_record_local_fields(self):
        with patch('extractor.services.instructor_extractor.build_table_tree', return_value=([self.table], {})), \
                patch('extractor.services.instructor_extractor.InstructorMessage.objects.filter') as messages:
            messages.return_value.order_by.return_value = []
            prompt = InstructorExtractionService.get_messages(self.rm, self.source)[-1]['content']
            legacy = InstructorExtractionService.get_messages(
                self.rm, self.source, include_field_assessments=False)[-1]['content']
        self.assertIn('field_assessments required for: count, measurement, present', prompt)
        self.assertIn('Do not treat silence', prompt)
        self.assertIn('clinical_inference', prompt)
        self.assertIn('unassessed', prompt)
        self.assertIn('exact arithmetic', prompt)
        self.assertIn('Do not wrap the response in markdown or code fences', prompt)
        self.assertIn('copied character-for-character', prompt)
        self.assertIn('leave quotes empty', prompt)
        self.assertIn('<document>\n' + self.source, prompt)
        self.assertNotIn('lymph_node', prompt)
        self.assertNotIn('field_assessments', legacy)
        self.assertIn('return only the integer number', legacy)

    def test_assessment_version_is_explicit(self):
        from types import SimpleNamespace

        for snapshot, expected in ((None, False), ({}, False), ({'field_assessment_version': 1}, True)):
            self.assertEqual(InstructorExtractionService.uses_field_assessments(
                SimpleNamespace(config_snapshot=snapshot)), expected)
        for version in (2, True, '1'):
            with self.assertRaises(ValueError):
                InstructorExtractionService.uses_field_assessments(
                    SimpleNamespace(config_snapshot={'field_assessment_version': version}))

    def test_strip_assessments_only_at_record_nodes(self):
        from types import SimpleNamespace

        child = SimpleNamespace(id=2, database_table=DatabaseTable(
            clientapp_content_type=ContentType(app_label='client_app', model='pathology')))
        record = dict(self.record, pathology=[dict(self.record)],
                      payload={'field_assessments': 'legitimate clinical dictionary key'})
        with patch('extractor.services.instructor_extractor.build_table_tree',
                   return_value=([self.table], {1: [child]})):
            clean = InstructorExtractionService.clinical_values_only(
                self.rm, {'patientassessment': [record]})['patientassessment'][0]
        self.assertNotIn('field_assessments', clean)
        self.assertNotIn('field_assessments', clean['pathology'][0])
        self.assertEqual(clean['payload']['field_assessments'], 'legitimate clinical dictionary key')
        self.assertIn('field_assessments', record)

    def stage_job(self):
        from types import SimpleNamespace

        self.rm.client = ClientConfiguration(llm_model_name='offline', model_max_tokens=4096,
                                            request_timeout=60)
        return SimpleNamespace(
            id=1, config_snapshot={'field_assessment_version': 1}, input_content_hash='',
            response_model=self.rm, extracted_by=None, save=Mock(),
            stage_trace=[{'stage': 'extraction', 'kind': 'prompt',
                          'messages': [{'role': 'user', 'content': 'APPROVED'}]}])

    def mock_stage(self, create):
        from contextlib import nullcontext

        client = Mock()
        client.chat.completions.create_with_completion.side_effect = create
        self.enterContext(patch.object(InstructorExtractionService, '_get_llm_client', return_value=client))
        self.enterContext(patch.object(InstructorExtractionService, 'build_lookup_rules', return_value={'x': {}}))
        self.enterContext(patch('extractor.services.instructor_extractor.build_table_tree',
                                return_value=([self.table], {})))
        self.enterContext(patch('django.db.transaction.atomic', side_effect=nullcontext))
        coverage = Mock()
        coverage.values.return_value.annotate.return_value = [{'result_state': 'extracted', 'n': 2}]
        self.enterContext(patch.object(ExtractionResult.objects, 'filter', return_value=coverage))
        saved = self.enterContext(patch.object(InstructorExtractionService, 'save_extraction_results'))
        return client, saved

    def test_stage_preserves_approved_prompt_and_hides_plain_metadata(self):
        import json
        from types import SimpleNamespace

        def create(**kwargs):
            self.assertEqual(kwargs['messages'], [{'role': 'user', 'content': 'APPROVED'}])
            self.assertEqual(kwargs['context']['source_text'], self.source)
            return self.parse(), SimpleNamespace(usage=SimpleNamespace(total_tokens=12))
        client, saved = self.mock_stage(create)
        job = self.stage_job()
        result = InstructorExtractionService.stage_extract(job, self.source)
        self.assertTrue(result['success'])
        self.assertEqual(client.chat.completions.create_with_completion.call_count, 1)
        self.assertIn('field_assessments', saved.call_args.args[1]['patientassessment'][0])
        self.assertNotIn('field_assessments', result['data']['patientassessment'][0])
        self.assertNotIn('field_assessments', job.stage_trace[-1]['data']['patientassessment'][0])
        self.assertIn('field_assessments', json.loads(job.raw_llm_response)['patientassessment'][0])

    def test_lookup_fallback_cannot_disable_evidence_validation(self):
        from instructor.core import InstructorRetryException
        from types import SimpleNamespace

        calls = []
        def create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise InstructorRetryException('retry', n_attempts=2, total_usage=None, failed_attempts=[Mock()])
            self.assertNotIn('lookup_rules', kwargs['context'])
            self.assertEqual(kwargs['context']['source_text'], self.source)
            invalid = self.parse()
            invalid.patientassessment[0].field_assessments[0].quotes = ['SENSITIVE FABRICATION']
            return invalid, SimpleNamespace(usage=None)
        client, saved = self.mock_stage(create)
        with self.assertRaisesMessage(ValueError, 'evidence could not be validated') as failure:
            InstructorExtractionService.stage_extract(self.stage_job(), self.source)
        self.assertNotIn('SENSITIVE', str(failure.exception))
        self.assertEqual(client.chat.completions.create_with_completion.call_count, 2)
        saved.assert_not_called()

    def test_new_prompts_freeze_assessment_version_in_both_paths(self):
        from types import SimpleNamespace

        self.enterContext(patch('extractor.services.instructor_extractor.build_table_tree',
                                return_value=([self.table], {})))
        messages = self.enterContext(patch('extractor.services.instructor_extractor.InstructorMessage.objects.filter'))
        messages.return_value.order_by.return_value = []
        job = self.stage_job()
        job.response_model_id = 1
        job.processed_file = SimpleNamespace(id=1, version=1, content_length=len(self.source), processing_warning='')
        job.stage_trace = []
        with patch.object(InstructorExtractionService, '_iter_lookup_fields', return_value=[]):
            InstructorExtractionService.stage_prepare(job, self.source)
        self.assertEqual(job.config_snapshot['field_assessment_version'], 1)
        self.assertEqual(job.extraction_status, 'awaiting_extraction')
        self.assertIn('NUMERIC AND BOOLEAN ASSESSMENT', job.stage_trace[-1]['messages'][-1]['content'])
        job = self.stage_job()
        job.config_snapshot = {'preserved': 'setting'}
        job.stage_trace = []
        with patch.object(InstructorExtractionService, '_get_llm_client'), \
                patch.object(InstructorExtractionService, '_iter_lookup_fields', return_value=[(self.table, self.fields[0])]), \
                patch.object(InstructorExtractionService, 'mine_lookup_snippets', return_value=({}, 0)), \
                patch.object(InstructorExtractionService, 'recheck_empty_snippets', return_value=({}, 0, [])):
            InstructorExtractionService.stage_mine(job, self.source)
        self.assertEqual(job.config_snapshot['field_assessment_version'], 1)
        self.assertEqual(job.config_snapshot['preserved'], 'setting')
        self.assertEqual(job.extraction_status, 'awaiting_extraction')
        self.assertIn('NUMERIC AND BOOLEAN ASSESSMENT', job.stage_trace[-1]['messages'][-1]['content'])

    def test_legacy_stage_does_not_require_assessments(self):
        from types import SimpleNamespace

        def create(**kwargs):
            self.assertNotIn('source_text', kwargs['context'])
            value = kwargs['response_model'](patientassessment=[{'count': 0}])
            return value, SimpleNamespace(usage=None)
        client, saved = self.mock_stage(create)
        job = self.stage_job()
        job.config_snapshot = {}
        result = InstructorExtractionService.stage_extract(job, self.source)
        self.assertTrue(result['success'])
        self.assertNotIn('field_assessments', result['data']['patientassessment'][0])
        saved.assert_called_once()

    def test_save_passes_scalar_and_assessment_to_correct_rows(self):
        job = self.stage_job()
        with patch('extractor.services.instructor_extractor.build_table_tree', return_value=([self.table], {})), \
                patch.object(ExtractedRecord.objects, 'create', return_value=Mock()), \
                patch.object(ExtractionResult.objects, 'create') as saved, \
                patch.object(InstructorExtractionService, '_find_evidence') as old_evidence:
            InstructorExtractionService.save_extraction_results(
                job, self.parse().model_dump(mode='json'), None, content=self.source)
        results = {call.kwargs['database_field'].clientapp_field_name: call.kwargs
                   for call in saved.call_args_list}
        self.assertEqual(set(results), {'count', 'measurement', 'present'})
        self.assertEqual(results['count']['extracted_data'], '0')
        self.assertEqual(results['count']['extraction_basis'], 'clinical_inference')
        self.assertEqual(results['count']['inference_note'], 'Zero is inferred.')
        self.assertEqual(results['count']['evidence'], 'No events.')
        self.assertEqual(results['present']['extracted_data'], 'False')
        self.assertEqual(results['measurement']['result_state'], 'not_found')
        self.assertEqual(results['measurement']['extraction_basis'], 'unknown')
        old_evidence.assert_not_called()

    def test_encrypted_note_round_trip_without_database(self):
        from django.db import connection

        field = ExtractionResult._meta.get_field('inference_note')
        ciphertext = field.get_db_prep_save('Synthetic private explanation', connection)
        self.assertNotIn('Synthetic private explanation', ciphertext)
        self.assertEqual(field.from_db_value(ciphertext, None, connection), 'Synthetic private explanation')


class InferenceModelTests(TestCase):
    def setUp(self):
        self.table = make_table('patientassessment', [PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt = ResponseModelTable.objects.create(response_model=self.rm, database_table=self.table)
        self.fields = {}
        for name, kind, validation in (
            ('pulse', EntityTypeChoices.INTEGER, {'min_value': 0}),
            ('height', EntityTypeChoices.FLOAT, {'max_digits': 10, 'decimal_places': 2}),
            ('finding_present', EntityTypeChoices.BOOLEAN, {}),
        ):
            field = make_field(self.table, name, field_type=kind, field_validation=validation)
            ResponseModelTableField.objects.create(response_model_table=self.rmt, field=field)
            self.fields[name] = field
        self.source = 'No events were observed. The finding is absent. Height was not assessed.'
        self.record = {
            'pulse': 0, 'height': None, 'finding_present': False,
            'field_assessments': [
                {'field': 'pulse', 'basis': 'inferred', 'quotes': ['No events were observed.'],
                 'rationale': 'No observed events supports zero.'},
                {'field': 'height', 'basis': 'unknown', 'quotes': ['Height was not assessed.'],
                 'rationale': 'Height was not assessed.'},
                {'field': 'finding_present', 'basis': 'inferred', 'quotes': ['The finding is absent.'],
                 'rationale': 'The finding was described as absent.'},
            ],
        }

    def validate(self, record=None, source=None):
        return PydanticModelBuilder.build_extraction_model(self.rm).model_validate(
            {'patientassessment': [self.record if record is None else record]},
            context={'source_text': self.source if source is None else source})

    def test_assessments_preserve_zero_false_and_null(self):
        record = self.validate().patientassessment[0]
        self.assertEqual(record.pulse, 0)
        self.assertIs(record.finding_present, False)
        self.assertIsNone(record.height)
        self.assertEqual(record.field_assessments[0].basis, 'inferred')

    def test_invalid_assessments_rejected(self):
        from copy import deepcopy
        from pydantic import ValidationError

        changes = [
            lambda r: r.pop('field_assessments'),
            lambda r: r['field_assessments'].pop(),
            lambda r: r['field_assessments'].append(r['field_assessments'][0]),
            lambda r: r['field_assessments'][0].update(field='unconfigured'),
            lambda r: r['field_assessments'][0].update(quotes=['Fabricated evidence']),
            lambda r: r['field_assessments'][0].update(quotes=[]),
            lambda r: r['field_assessments'][0].update(quotes=[' ']),
            lambda r: r['field_assessments'][0].update(quotes=['x' * 401]),
            lambda r: r['field_assessments'][0].update(quotes=['No events were observed.'] * 4),
            lambda r: r['field_assessments'][0].update(rationale=' '),
            lambda r: r['field_assessments'][0].update(rationale='x' * 401),
            lambda r: r['field_assessments'][0].update(basis='unknown'),
            lambda r: r['field_assessments'][0].update(extra='untrusted'),
            lambda r: r['field_assessments'][1].update(basis='explicit'),
            lambda r: r['field_assessments'][2].update(basis='calculated'),
            lambda r: r.update(pulse=1),
            lambda r: r.update(pulse=-1),
            lambda r: r.update(finding_present=True),
        ]
        for index, change in enumerate(changes):
            record = deepcopy(self.record)
            change(record)
            with self.subTest(case=index), self.assertRaises(ValidationError):
                self.validate(record)
        with self.assertRaises(ValidationError):
            self.validate(source='')

    def test_clinical_calculated_and_explicit_values(self):
        self.record['field_assessments'][0]['basis'] = 'clinical_inference'
        self.validate()
        self.record['height'] = '12.50'
        self.record['field_assessments'][1].update(
            basis='calculated', quotes=['No events were observed.'], rationale='25 / 2 = 12.50.')
        self.assertEqual(self.validate().patientassessment[0].height, Decimal('12.50'))
        self.record['finding_present'] = True
        self.record['field_assessments'][2].update(basis='explicit', rationale='')
        self.assertIs(self.validate().patientassessment[0].finding_present, True)

    def test_legacy_model_does_not_require_metadata(self):
        model = PydanticModelBuilder.build_extraction_model(self.rm, include_field_assessments=False)
        value = model.model_validate({'patientassessment': [{'pulse': 0}]})
        self.assertEqual(value.patientassessment[0].pulse, 0)
        self.assertNotIn('field_assessments', value.patientassessment[0].model_fields)

    def test_generated_code_matches_assessment_validation(self):
        from pydantic import ValidationError

        code = PydanticModelBuilder.build_pydantic_model(self.rm)
        self.assertTrue(PydanticModelBuilder.validate_generated_code(code)['valid'])
        namespace = {}
        exec(code, namespace)
        model = namespace['TestRmModel']
        parsed = model.model_validate({'patientassessment': [self.record]},
                                      context={'source_text': self.source})
        self.assertEqual(parsed.patientassessment[0].field_assessments[0].basis, 'inferred')
        with self.assertRaises(ValidationError):
            model.model_validate({'patientassessment': [self.record]}, context={'source_text': ''})

    def test_eligibility_and_reserved_collision(self):
        from extractor.services.pydantic_builder import supports_field_assessment

        field = self.fields['pulse']
        self.assertTrue(supports_field_assessment(field))
        for kwargs in ({'lookup_field': True}, {'is_active': False},
                       {'field_validation': {'is_relationship': True}},
                       {'field_type': EntityTypeChoices.STRING}):
            for key, value in kwargs.items():
                setattr(field, key, value)
            self.assertFalse(supports_field_assessment(field))
            field.refresh_from_db()
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt, field=make_field(self.table, 'field_assessments'))
        for builder in (PydanticModelBuilder.build_extraction_model, PydanticModelBuilder.build_pydantic_model):
            with self.assertRaisesMessage(ValueError, 'reserved'):
                builder(self.rm)


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


    def test_nested_numeric_assessments_stay_with_their_record(self):
        for name, kind in (('lymph_nodes_in_specimen', 'int'), ('lymph_nodes_removed', 'bool')):
            ResponseModelTableField.objects.create(response_model_table=self.rmt_path,
                                                    field=make_field(self.pathology, name, field_type=kind))
        self.job.config_snapshot = {'field_assessment_version': 1}
        self.job.save()
        payload = {'diagnosis': [{'diagnosis_date': '2024-01-01', 'pathology': [
            {'lymph_nodes_in_specimen': count, 'lymph_nodes_removed': removed,
             'field_assessments': [
                 {'field': 'lymph_nodes_in_specimen', 'basis': 'explicit', 'quotes': [quote], 'rationale': ''},
                 {'field': 'lymph_nodes_removed', 'basis': 'explicit', 'quotes': [quote], 'rationale': ''}]}
            for count, removed, quote in ((0, False, 'Specimen A: none.'), (2, True, 'Specimen B: two.'))]}]}
        InstructorExtractionService.save_extraction_results(self.job, payload, self.user)
        children = ExtractedRecord.objects.filter(database_table=self.pathology).order_by('record_index')
        self.assertEqual(children.count(), 2)
        for record, expected, quote in zip(children, ('0', '2'), ('Specimen A: none.', 'Specimen B: two.')):
            result = record.results.get(database_field__clientapp_field_name='lymph_nodes_in_specimen')
            self.assertEqual(result.extracted_data, expected)
            self.assertEqual(result.evidence, quote)
            self.assertEqual(result.extraction_basis, 'explicit')
        self.assertEqual(children[0].results.get(
            database_field__clientapp_field_name='lymph_nodes_removed').extracted_data, 'False')


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


class InferenceReviewContractTests(SimpleTestCase):
    def test_preview_preserves_zero_false_and_escapes_assessment(self):
        from types import SimpleNamespace
        from django.conf import settings
        from django.template import Context, Engine

        engine = Engine(dirs=[str(settings.BASE_DIR / 'templates')], loaders=[
            ('django.template.loaders.locmem.Loader', {'base.html': '{% block content %}{% endblock %}'}),
            'django.template.loaders.filesystem.Loader'])
        rows = [{'name': name, 'before': value, 'after': value} for name, value in (
            ('zero', 0), ('false', False), ('decimal', Decimal('0.00')), ('null', None), ('empty', ''))]
        rows[0]['extraction'] = {'value': '0', 'basis': 'clinical_inference',
                                 'label': 'Clinically inferred', 'note': '<script>note</script>',
                                 'evidence': '<b>source</b>'}
        html = engine.get_template('extractor/extraction_review_preview.html').render(Context({
            'extraction_job': SimpleNamespace(id=1),
            'batch': SimpleNamespace(status='approved'),
            'snapshot': {'records': [{'model': 'example', 'operation': 'create', 'rows': rows}]},
        }))
        self.assertIn('text-gray-900">0</td>', html)
        self.assertIn('text-gray-900">False</td>', html)
        self.assertIn('text-gray-900">0.00</td>', html)
        self.assertEqual(html.count('text-gray-900">—</td>'), 2)
        self.assertIn('not explicitly reported', html)
        self.assertIn('&lt;script&gt;note&lt;/script&gt;', html)
        self.assertIn('&lt;b&gt;source&lt;/b&gt;', html)
        self.assertNotIn('<script>note</script>', html)

    def test_field_notes_describe_original_not_corrected_value(self):
        from types import SimpleNamespace
        from django.template.loader import render_to_string

        result = ExtractionResult(extracted_data='0', extraction_basis='clinical_inference',
                                  inference_note='<b>Likely absence</b>', evidence='No reported events.',
                                  data_edited=True, edited_data='3')
        detail = {'field': SimpleNamespace(id=1, clientapp_field_name='count'),
                  'result': result, 'original_cell': {'text': '0'}, 'cell': {'text': '3'},
                  'input_kind': 'integer', 'baseline': '3', 'original_value': '0'}
        html = render_to_string('extractor/record_detail_body.html', {
            'rec': {'record': SimpleNamespace(id=1), 'detail': [detail]}})
        self.assertIn('not explicitly reported', html)
        self.assertIn('Original LLM extraction: &lt;b&gt;Likely absence&lt;/b&gt;', html)
        self.assertIn('Last reviewed value: 3', html)
        self.assertIn('No reported events.', html)

    def test_payload_retains_original_assessment_after_edit(self):
        from extractor.services.review import _assessment_payload, _result_payload

        result = ExtractionResult(extracted_data='0', extraction_basis='inferred',
                                  inference_note='Absence described.', evidence='No events.',
                                  data_edited=True, edited_data='3')
        self.assertEqual(_assessment_payload(result)['value'], '0')
        self.assertEqual(_result_payload(result)['edited'], '3')
        result.result_state = 'not_found'
        self.assertIsNone(_assessment_payload(result)['value'])
        self.assertIsNone(_assessment_payload(ExtractionResult(extracted_data='0')))


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

    def inferred_result(self):
        field = make_field(self.table, 'pulse', field_type='int')
        return ExtractionResult.objects.create(
            extraction_job=self.job, database_field=field, record=self.record,
            extracted_data='0', extraction_basis='inferred',
            inference_note='Synthetic inference explanation.', evidence='Synthetic source quotation.')

    def test_inference_snapshot_and_normal_approval_preserve_zero(self):
        import json
        import uuid
        from client_app.models import PatientAssessment
        from django.db import connection

        result = self.inferred_result()
        payload = self.payload()
        payload['records'][0]['fields'][str(result.database_field_id)] = {'action': 'apply', 'value': '0'}
        batch = prepare_review(self.job, self.user, payload, uuid.uuid4())
        snapshot = json.loads(batch.snapshot)
        row = next(row for row in snapshot['records'][0]['rows'] if row['name'] == 'pulse')
        self.assertEqual(row['after'], 0)
        self.assertEqual(row['extraction']['note'], result.inference_note)
        approved = approve_review(batch.id, self.user, confirm=True, acknowledge_duplicates=False)
        self.assertEqual(PatientAssessment.objects.get().pulse, 0)
        result.refresh_from_db()
        self.assertEqual(result.extraction_basis, 'inferred')
        self.assertEqual(result.review_change, 'accepted')
        self.assertEqual(json.loads(approved.snapshot)['records'][0]['rows'], snapshot['records'][0]['rows'])
        with connection.cursor() as cursor:
            cursor.execute('SELECT inference_note, evidence FROM extractor_extractionresult WHERE id = %s', [result.id])
            note, evidence = cursor.fetchone()
        self.assertNotIn('Synthetic inference explanation.', note)
        self.assertNotIn('Synthetic source quotation.', evidence)

    def test_changed_inference_invalidates_pending_preview(self):
        import uuid
        from extractor.services.review import ReviewConflictError

        result = self.inferred_result()
        payload = self.payload()
        payload['records'][0]['fields'][str(result.database_field_id)] = {'action': 'apply', 'value': '0'}
        batch = prepare_review(self.job, self.user, payload, uuid.uuid4())
        result.inference_note = 'Changed explanation.'
        result.save(update_fields=['inference_note'])
        with self.assertRaises(ReviewConflictError):
            approve_review(batch.id, self.user, confirm=True, acknowledge_duplicates=False)

    def test_blank_new_metadata_keeps_legacy_fingerprint(self):
        from extractor.services.review import _fingerprint

        original = _fingerprint(self.job)
        self.result.extraction_basis = ''
        self.result.inference_note = ''
        self.result.save(update_fields=['extraction_basis', 'inference_note'])
        self.assertEqual(_fingerprint(self.job), original)


class EmbeddingIndexTests(TestCase):
    """
    Index build/swap semantics: versioned uniqueness, per-row resume,
    stale repair, and safe finalization.

    LookupLaterality's pk ('code') is in NON_SEMANTIC_FIELDS, so each record
    produces exactly one 'label' embedding — keeps row counting simple.
    """

    def setUp(self):
        from lookup.models import LookupLaterality
        from extractor.models import EmbeddingConfiguration

        self.model = LookupLaterality
        self.ct = ContentType.objects.get_for_model(LookupLaterality)
        self.config = EmbeddingConfiguration.objects.create(
            model_name='test-embed', model_provider='sentence-transformers',
            embedding_dimension=384, is_active=True)
        # Unique labels so "this text was encoded" assertions can't collide
        # with migration-seeded lookup rows.
        for code, label in (('TESTL', 'zz-laterality-left'),
                            ('TESTR', 'zz-laterality-right'),
                            ('TESTB', 'zz-laterality-bilateral')):
            LookupLaterality.objects.create(code=code, label=label)
        self.record_count = self.model.objects.count()

        # The builder calls close_old_connections() — harmless in production
        # but fatal inside TestCase's wrapping transaction.
        for target in (
                'extractor.services.embedding_index.close_old_connections',
                'extractor.tasks.close_old_connections'):
            patcher = patch(target, lambda: None)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def _provider(texts_seen=None):
        provider = Mock()
        def embed(texts):
            if texts_seen is not None:
                texts_seen.extend(texts)
            return [[0.1] * 384 for _ in texts]
        provider.embed_texts.side_effect = embed
        return provider

    def _build_table(self, target_version=1, provider=None):
        from extractor.services.embedding_index import compute_lookup_table_embeddings
        with patch('extractor.services.embedding_index.get_provider',
                   return_value=provider or self._provider()):
            return compute_lookup_table_embeddings(
                self.config, self.ct, target_version)

    def test_refresh_writes_new_version_and_swaps(self):
        """Regression: refresh inserts must not collide with the live generation."""
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import compute_lookup_embeddings

        self._build_table(target_version=1)
        self.assertEqual(LookupEmbedding.objects.filter(
            content_type=self.ct, index_version=1).count(), self.record_count)

        with patch('extractor.services.embedding_index.get_provider',
                   return_value=self._provider()):
            compute_lookup_embeddings(self.config, refresh=True)

        self.config.refresh_from_db()
        self.assertEqual(self.config.version, 2)
        self.assertEqual(LookupEmbedding.objects.filter(
            content_type=self.ct, index_version=2).count(), self.record_count)
        self.assertEqual(LookupEmbedding.objects.filter(
            content_type=self.ct, index_version=1).count(), 0)

    def test_refresh_resume_skips_existing_rows(self):
        """A row committed by a crashed build is reused, not re-encoded."""
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import compute_lookup_embeddings

        self._build_table(target_version=1)
        LookupEmbedding.objects.create(
            content_type=self.ct, object_id='TESTL', field_name='label',
            text_value='zz-laterality-left', embedding=[0.1] * 384,
            embedding_config=self.config, index_version=2)

        seen = []
        with patch('extractor.services.embedding_index.get_provider',
                   return_value=self._provider(seen)):
            compute_lookup_embeddings(self.config, refresh=True)

        self.assertNotIn('zz-laterality-left', seen)
        self.config.refresh_from_db()
        self.assertEqual(self.config.version, 2)
        self.assertEqual(LookupEmbedding.objects.filter(
            content_type=self.ct, index_version=2).count(), self.record_count)

    def test_gap_fill_reembeds_changed_text(self):
        """Changed source text replaces the stale row instead of staying stuck."""
        from extractor.models import LookupEmbedding

        self._build_table(target_version=1)
        self.model.objects.filter(code='TESTL').update(label='zz-laterality-left-v2')

        seen = []
        stats = self._build_table(target_version=1, provider=self._provider(seen))

        row = LookupEmbedding.objects.get(
            content_type=self.ct, object_id='TESTL', field_name='label',
            index_version=1)
        self.assertEqual(row.text_value, 'zz-laterality-left-v2')
        self.assertTrue(row.is_current)
        self.assertIn('zz-laterality-left-v2', seen)
        self.assertEqual(stats['count'], 1)

    def test_refresh_fully_built_still_finalizes(self):
        """A build that crashed after writing but before swapping can still activate."""
        from django.apps import apps
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import compute_lookup_embeddings

        self._build_table(target_version=1)
        # Only this table has records, so a fully-built v2 means zero new rows
        for m in apps.get_app_config('lookup').get_models():
            if m is not self.model:
                m.objects.all().delete()
        LookupEmbedding.objects.bulk_create([
            LookupEmbedding(
                content_type=self.ct, object_id=record.code, field_name='label',
                text_value=record.label, embedding=[0.1] * 384,
                embedding_config=self.config, index_version=2)
            for record in self.model.objects.all()])

        seen = []
        with patch('extractor.services.embedding_index.get_provider',
                   return_value=self._provider(seen)):
            result = compute_lookup_embeddings(self.config, refresh=True)

        self.assertEqual(seen, [])
        self.assertEqual(result['total_processed'], 0)
        self.config.refresh_from_db()
        self.assertEqual(self.config.version, 2)

    def test_failed_refresh_keeps_old_index(self):
        """Provider failure mid-refresh leaves the live version untouched."""
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import compute_lookup_embeddings

        self._build_table(target_version=1)

        failing = Mock()
        failing.embed_texts.side_effect = RuntimeError('provider down')
        with patch('extractor.services.embedding_index.get_provider',
                   return_value=failing):
            with self.assertRaises(RuntimeError):
                compute_lookup_embeddings(self.config, refresh=True)

        self.config.refresh_from_db()
        self.assertEqual(self.config.version, 1)
        self.assertEqual(LookupEmbedding.objects.filter(
            content_type=self.ct, index_version=1, is_current=True).count(),
            self.record_count)

    def test_failed_refresh_partial_rows_do_not_finalize(self):
        """A refresh with committed rows AND a failed table must not swap."""
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import compute_lookup_embeddings

        self._build_table(target_version=1)
        LookupEmbedding.objects.create(
            content_type=self.ct, object_id='TESTL', field_name='label',
            text_value='zz-laterality-left', embedding=[0.1] * 384,
            embedding_config=self.config, index_version=2)

        failing = Mock()
        failing.embed_texts.side_effect = RuntimeError('provider down')
        with patch('extractor.services.embedding_index.get_provider',
                   return_value=failing):
            with self.assertRaises(RuntimeError):
                compute_lookup_embeddings(self.config, refresh=True)

        self.config.refresh_from_db()
        self.assertEqual(self.config.version, 1)
        self.assertEqual(LookupEmbedding.objects.filter(
            content_type=self.ct, index_version=1, is_current=True).count(),
            self.record_count)
        # The partial v2 row survives for a later resume.
        self.assertTrue(LookupEmbedding.objects.filter(
            index_version=2, object_id='TESTL').exists())

    def test_count_mismatch_is_batch_failure(self):
        """A provider returning fewer vectors than texts fails the batch."""
        short = Mock()
        short.embed_texts.return_value = [[0.1] * 384]
        stats = self._build_table(target_version=1, provider=short)
        self.assertEqual(stats['count'], 0)
        self.assertEqual(stats['failed'], self.record_count)

    def test_deleted_record_row_removed(self):
        """A deleted lookup record's embedding is cleaned on the next build."""
        from extractor.models import LookupEmbedding

        self._build_table(target_version=1)
        self.model.objects.filter(code='TESTB').delete()
        self._build_table(target_version=1)

        self.assertFalse(LookupEmbedding.objects.filter(
            object_id='TESTB', index_version=1).exists())
        self.assertEqual(LookupEmbedding.objects.filter(
            index_version=1, is_current=True).count(), self.record_count - 1)

    def test_record_table_result_replaces_retry(self):
        """A redelivered table task replaces its earlier result, not appends."""
        from extractor.models import BackgroundTask
        from extractor.tasks import _record_table_result

        task = BackgroundTask.objects.create(task_id='t1', task_name='x')
        _record_table_result(
            task, {'table': 'lookuplaterality', 'count': 1, 'failed': 0}, 1, 2)
        _record_table_result(
            task, {'table': 'lookuplaterality', 'count': 3, 'failed': 0}, 1, 2)
        task.refresh_from_db()
        results = task.result_data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['count'], 3)

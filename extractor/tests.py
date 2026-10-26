import json
import os
import threading
import time
from contextlib import nullcontext
from decimal import Decimal
from unittest import mock
from unittest.mock import Mock, patch

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from extractor.models import (
    ClientConfiguration, DatabaseField, DatabaseTable, EntityTypeChoices,
    ExtractedRecord, ExtractionJob, ExtractionResult, ExtractionStatusChoices,
    FileUpload, ProcessedText,
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
            processed_file=None,
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

    def test_failed_validation_nulls_field_and_repairs(self):
        import json
        from instructor.core import InstructorRetryException
        from types import SimpleNamespace

        bad_record = {
            'count': 7, 'measurement': None, 'present': False,
            'field_assessments': [
                {'field': 'count', 'basis': 'explicit',
                 'quotes': ['FABRICATED QUOTE'], 'rationale': 'made up'},
                {'field': 'measurement', 'basis': 'unknown', 'quotes': [],
                 'rationale': 'Not assessed.'},
                {'field': 'present', 'basis': 'inferred',
                 'quotes': ['The finding is absent.'], 'rationale': 'Absent.'},
            ],
        }
        completion = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(
                content=json.dumps({'patientassessment': [bad_record]})))])

        calls = []
        def create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise InstructorRetryException(
                    'retry', n_attempts=2, total_usage=None,
                    failed_attempts=[Mock()], last_completion=completion)
            # Repair run: model returns a fully valid response
            return self.parse(), SimpleNamespace(usage=SimpleNamespace(total_tokens=9))
        client, saved = self.mock_stage(create)
        job = self.stage_job()
        result = InstructorExtractionService.stage_extract(job, self.source)
        self.assertTrue(result['success'])
        self.assertEqual(client.chat.completions.create_with_completion.call_count, 2)
        # Repair run received the sanitized payload + repair instruction,
        # still under the full validation context
        repair_messages = calls[1]['messages']
        self.assertEqual(repair_messages[0], {'role': 'user', 'content': 'APPROVED'})
        self.assertEqual(repair_messages[-1]['content'],
                         InstructorExtractionService.REPAIR_PROMPT)
        self.assertIn('"count": null', repair_messages[-2]['content'])
        self.assertEqual(calls[1]['context']['source_text'], self.source)
        saved.assert_called_once()

    def test_failed_repair_accepts_sanitized_response(self):
        import json
        from instructor.core import InstructorRetryException
        from types import SimpleNamespace

        bad_record = {
            'count': 7, 'measurement': None, 'present': False,
            'field_assessments': [
                {'field': 'count', 'basis': 'explicit',
                 'quotes': ['FABRICATED QUOTE'], 'rationale': 'made up'},
                {'field': 'measurement', 'basis': 'unknown', 'quotes': [],
                 'rationale': 'Not assessed.'},
                {'field': 'present', 'basis': 'inferred',
                 'quotes': ['The finding is absent.'], 'rationale': 'Absent.'},
            ],
        }
        completion = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(
                content=json.dumps({'patientassessment': [bad_record]})))])

        def create(**kwargs):
            raise InstructorRetryException(
                'retry', n_attempts=2, total_usage=None,
                failed_attempts=[Mock()], last_completion=completion)
        client, saved = self.mock_stage(create)
        job = self.stage_job()
        result = InstructorExtractionService.stage_extract(job, self.source)
        # Both runs failed validation — the sanitized payload is still saved
        self.assertTrue(result['success'])
        saved_data = saved.call_args.args[1]
        record = saved_data['patientassessment'][0]
        self.assertIsNone(record['count'])
        self.assertFalse(record['present'])
        self.assertIsNone(record['measurement'])

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
            file_upload=upload, content_length=5,
            deidentified=True, deid_reviewed=True)
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
        self.assertEqual(kinds[0], ('mining', 'prompt'))
        self.assertEqual(kinds[1], ('mining', 'result'))
        self.assertTrue(len(kinds) > 2)
        self.assertTrue(all(k == ('extraction', 'prompt') for k in kinds[2:]))
        self.assertTrue(all('messages' in e and e['fields']
                            for e in self.job.stage_trace[2:]))
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
        adv.delay.assert_called_once_with(
            self.job.id, approved_status='awaiting_mining')
        self.assertEqual(resp.status_code, 302)
        # The click claims the stage — a second POST must not dispatch again
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status, 'processing')
        with patch('extractor.views.advance_extraction_job') as adv:
            self.client.post(
                f'/extractor/extraction/jobs/{self.job.id}/continue/')
        adv.delay.assert_not_called()

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
            'django.template.loaders.filesystem.Loader'],
            builtins=['django_components.templatetags.component_tags'],
            libraries={'static': 'django.templatetags.static'})
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
        self.assertIn('field-value-text">0</span>', html)
        self.assertIn('field-value-text">False</span>', html)
        self.assertIn('field-value-text">0.00</span>', html)
        self.assertEqual(html.count('field-value-text">—</span>'), 4)
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


class ChunkedEmbeddingServiceTests(TestCase):
    """collect_pending_rows / embed_one_chunk tile a table into bounded,
    stable, non-overlapping chunks and make re-embedding a no-op."""

    def setUp(self):
        from lookup.models import LookupLaterality
        from extractor.models import EmbeddingConfiguration

        self.model = LookupLaterality
        self.ct = ContentType.objects.get_for_model(LookupLaterality)
        self.config = EmbeddingConfiguration.objects.create(
            model_name='test-embed', model_provider='sentence-transformers',
            embedding_dimension=384, is_active=True)
        # Start from a clean table (the test DB is seeded with XK* rows).
        LookupLaterality.objects.all().delete()
        for code, label in (('C1', 'zz-lab-a'), ('C2', 'zz-lab-b'),
                            ('C3', 'zz-lab-c'), ('C4', 'zz-lab-d')):
            LookupLaterality.objects.create(code=code, label=label)

        # The builder calls close_old_connections() — fatal inside TestCase's
        # wrapping transaction.
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

    def test_collect_pending_returns_first_chunk_and_remaining(self):
        from extractor.services.embedding_index import collect_pending_rows
        chunk, remaining = collect_pending_rows(
            self.config, self.ct, 1, chunk_size=2)
        self.assertEqual(remaining, 4)
        self.assertEqual(len(chunk), 2)
        self.assertEqual([r[0] for r in chunk], ['C1', 'C2'])
        self.assertEqual([r[1] for r in chunk], ['label', 'label'])

    def test_collect_pending_excludes_embedded_and_failed(self):
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import collect_pending_rows

        LookupEmbedding.objects.create(
            content_type=self.ct, object_id='C1', field_name='label',
            text_value='zz-lab-a', embedding=[0.1] * 384,
            embedding_config=self.config, index_version=1)

        chunk, remaining = collect_pending_rows(
            self.config, self.ct, 1,
            exclude_keys={('C2', 'label')}, chunk_size=10)
        ids = [r[0] for r in chunk]
        self.assertNotIn('C1', ids)  # already embedded
        self.assertNotIn('C2', ids)  # excluded (previously failed)
        self.assertEqual(ids, ['C3', 'C4'])
        self.assertEqual(remaining, 2)

    def test_embed_one_chunk_writes_and_reports(self):
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import embed_one_chunk

        chunk = [('C1', 'label', 'zz-lab-a'), ('C2', 'label', 'zz-lab-b')]
        count, failed, failed_keys = embed_one_chunk(
            self._provider(), self.config, self.ct, 1, chunk)
        self.assertEqual((count, failed), (2, 0))
        self.assertEqual(failed_keys, [])
        self.assertEqual(
            LookupEmbedding.objects.filter(index_version=1).count(), 2)

    def test_embed_one_chunk_returns_failed_keys_on_error(self):
        from extractor.services.embedding_index import embed_one_chunk

        failing = Mock()
        failing.embed_texts.side_effect = RuntimeError('boom')
        chunk = [('C1', 'label', 'zz-lab-a'), ('C2', 'label', 'zz-lab-b')]
        count, failed, failed_keys = embed_one_chunk(
            failing, self.config, self.ct, 1, chunk)
        self.assertEqual((count, failed), (0, 2))
        self.assertEqual(failed_keys, [('C1', 'label'), ('C2', 'label')])

    def test_embed_one_chunk_is_idempotent(self):
        from extractor.models import LookupEmbedding
        from extractor.services.embedding_index import embed_one_chunk

        chunk = [('C1', 'label', 'zz-lab-a')]
        embed_one_chunk(self._provider(), self.config, self.ct, 1, chunk)
        embed_one_chunk(self._provider(), self.config, self.ct, 1, chunk)
        self.assertEqual(
            LookupEmbedding.objects.filter(index_version=1).count(), 1)


class ChunkedEmbeddingTaskTests(TestCase):
    """embed_lookup_table_chunk tiles one table into bounded, self-perpetuating
    chunk tasks and terminates by advancing tables / finalizing."""

    def setUp(self):
        from lookup.models import LookupLaterality
        from extractor.models import EmbeddingConfiguration, BackgroundTask

        self.model = LookupLaterality
        self.ct = ContentType.objects.get_for_model(LookupLaterality)
        self.config = EmbeddingConfiguration.objects.create(
            model_name='test-embed', model_provider='sentence-transformers',
            embedding_dimension=384, is_active=True)
        self.task = BackgroundTask.objects.create(
            task_id='emb-task-1', task_name='Compute Lookup Embeddings',
            status='pending', result_data={'results': []})
        # Start from a clean table (the test DB is seeded with XK* rows).
        LookupLaterality.objects.all().delete()
        for code, label in (('C1', 'zz-lab-a'), ('C2', 'zz-lab-b'),
                            ('C3', 'zz-lab-c')):
            LookupLaterality.objects.create(code=code, label=label)

        for target in (
                'extractor.services.embedding_index.close_old_connections',
                'extractor.tasks.close_old_connections'):
            patcher = patch(target, lambda: None)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def _provider():
        p = Mock()
        p.embed_texts.side_effect = lambda texts: [[0.1] * 384 for _ in texts]
        return p

    def _run_chunk(self):
        from extractor.models import LookupEmbedding
        from extractor.tasks import (embed_lookup_table_chunk,
                                     finalize_lookup_embeddings_task)
        with patch('extractor.services.embedding_index.get_provider',
                   return_value=self._provider()), \
             patch('extractor.services.embedding_index.CHUNK_SIZE', 2), \
             patch.object(embed_lookup_table_chunk, 'apply_async') as nxt, \
             patch.object(finalize_lookup_embeddings_task, 'apply_async') as fin:
            embed_lookup_table_chunk.run(
                self.task.task_id, self.config.id, self.ct.id,
                1, False, 1, 1)
            rows = LookupEmbedding.objects.filter(index_version=1).count()
        return rows, nxt, fin

    def test_first_chunk_embeds_and_dispatches_next(self):
        rows, nxt, fin = self._run_chunk()
        self.assertEqual(rows, 2)                 # CHUNK_SIZE=2 -> first chunk
        self.assertTrue(nxt.called)               # table not done -> next chunk
        self.assertFalse(fin.called)
        # next chunk carries the same table, same table_index
        self.assertEqual(nxt.call_args[1]['args'],
                         [self.task.task_id, self.config.id, self.ct.id,
                          1, False, 1, 1])

    def test_last_chunk_finalizes_with_task_id_first(self):
        from extractor.models import LookupEmbedding
        self._run_chunk()                          # embeds C1, C2
        rows, nxt, fin = self._run_chunk()          # embeds C3 -> last
        self.assertEqual(rows, 3)
        self.assertFalse(nxt.called)
        self.assertTrue(fin.called)
        # finalize args: task_id FIRST (inflight check depends on it)
        self.assertEqual(fin.call_args[1]['args'],
                         [self.task.task_id, self.config.id, 1, False])

    def test_failed_chunk_is_recorded_not_retried(self):
        from extractor.models import LookupEmbedding
        from extractor.tasks import (embed_lookup_table_chunk,
                                     finalize_lookup_embeddings_task)
        failing = Mock()
        failing.embed_texts.side_effect = RuntimeError('down')
        with patch('extractor.services.embedding_index.get_provider',
                   return_value=failing), \
             patch('extractor.services.embedding_index.CHUNK_SIZE', 2), \
             patch.object(embed_lookup_table_chunk, 'apply_async') as nxt, \
             patch.object(finalize_lookup_embeddings_task, 'apply_async') as fin:
            # chunk 1: 2 rows fail -> recorded, next chunk dispatched
            embed_lookup_table_chunk.run(
                self.task.task_id, self.config.id, self.ct.id, 1, False, 1, 1)
            self.task.refresh_from_db()  # task saved result_data on a fresh row
            self.assertEqual(
                LookupEmbedding.objects.filter(index_version=1).count(), 0)
            self.assertTrue(nxt.called)
            self.assertEqual(
                len(self.task.result_data['failed']['lookuplaterality']), 2)
            # chunk 2: last row fails -> table exhausted -> finalize (no loop)
            embed_lookup_table_chunk.run(
                self.task.task_id, self.config.id, self.ct.id, 1, False, 1, 1)
        self.assertTrue(fin.called)

    def test_fatal_short_circuits_chain(self):
        from extractor.models import LookupEmbedding
        from extractor.tasks import (embed_lookup_table_chunk,
                                     finalize_lookup_embeddings_task)
        self.task.result_data = {'fatal': 'provider dead', 'results': []}
        self.task.save()
        with patch('extractor.services.embedding_index.get_provider') as gp, \
             patch.object(embed_lookup_table_chunk, 'apply_async') as nxt, \
             patch.object(finalize_lookup_embeddings_task, 'apply_async') as fin:
            embed_lookup_table_chunk.run(
                self.task.task_id, self.config.id, self.ct.id, 1, False, 1, 1)
        gp.assert_not_called()
        nxt.assert_not_called()
        fin.assert_not_called()
        self.assertEqual(LookupEmbedding.objects.count(), 0)

    def test_advance_dispatches_next_table_then_finalize(self):
        from django.contrib.contenttypes.models import ContentType
        from extractor.tasks import (_advance_to_next_table_or_finalize,
                                     embed_lookup_table_chunk,
                                     finalize_lookup_embeddings_task)
        tables = list(ContentType.objects.filter(app_label='lookup')
                             .order_by('id'))
        self.assertGreaterEqual(len(tables), 2)
        with patch.object(embed_lookup_table_chunk, 'apply_async') as nxt, \
             patch.object(finalize_lookup_embeddings_task, 'apply_async') as fin:
            _advance_to_next_table_or_finalize(
                'tid', self.config.id, 1, False, 1, len(tables))
        self.assertTrue(nxt.called)
        self.assertFalse(fin.called)
        # 1-based table_index=1 finished -> next is tables[1], index 2
        self.assertEqual(nxt.call_args[1]['args'],
                         ['tid', self.config.id, tables[1].id, 1, False,
                          2, len(tables)])
        with patch.object(embed_lookup_table_chunk, 'apply_async') as nxt2, \
             patch.object(finalize_lookup_embeddings_task, 'apply_async') as fin2:
            _advance_to_next_table_or_finalize(
                'tid', self.config.id, 1, False, len(tables), len(tables))
        self.assertFalse(nxt2.called)
        self.assertTrue(fin2.called)
        self.assertEqual(fin2.call_args[1]['args'],
                         ['tid', self.config.id, 1, False])


class EmbeddingDispatcherTests(TestCase):
    """compute_lookup_embeddings_task starts the build by dispatching the first
    table's first chunk (not a chain)."""

    def setUp(self):
        from lookup.models import LookupLaterality
        from extractor.models import (EmbeddingConfiguration,
                                      BackgroundTask)

        self.ct = ContentType.objects.get_for_model(LookupLaterality)
        self.config = EmbeddingConfiguration.objects.create(
            model_name='test-embed', model_provider='sentence-transformers',
            embedding_dimension=384, is_active=True)
        self.task = BackgroundTask.objects.create(
            task_id='emb-task-1', task_name='Compute Lookup Embeddings',
            status='pending')
        patcher = patch('extractor.tasks.close_old_connections',
                        lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dispatcher_starts_first_chunk(self):
        from django.contrib.contenttypes.models import ContentType
        from extractor.tasks import compute_lookup_embeddings_task
        from extractor.tasks import embed_lookup_table_chunk

        first_ct = ContentType.objects.filter(app_label='lookup') \
                                      .order_by('id').first()
        total = ContentType.objects.filter(app_label='lookup').count()
        with patch.object(embed_lookup_table_chunk, 'apply_async') as first:
            compute_lookup_embeddings_task.run(
                self.task.task_id, self.config.id, refresh=False)
        self.assertTrue(first.called)
        args = first.call_args[1]['args']
        # task_id FIRST (inflight check), config, first table, current version
        # (gap-fill), no refresh, 1-based index 1, total tables
        self.assertEqual(args[0], self.task.task_id)
        self.assertEqual(args[1], self.config.id)
        self.assertEqual(args[2], first_ct.id)
        self.assertEqual(args[3], self.config.version)
        self.assertEqual(args[4], False)
        self.assertEqual(args[5], 1)
        self.assertEqual(args[6], total)
        # dispatcher initialized result_data and marked the task running
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'running')
        self.assertEqual(self.task.result_data['results'], [])

    def test_dispatcher_marks_failed_when_no_tables(self):
        from django.contrib.contenttypes.models import ContentType
        from extractor.tasks import compute_lookup_embeddings_task
        from extractor.tasks import embed_lookup_table_chunk

        with patch.object(ContentType, 'objects') as objects_mock:
            objects_mock.filter.return_value.order_by.return_value.__iter__ \
                = lambda *a, **k: iter([])  # pretend: no lookup tables
            with patch.object(embed_lookup_table_chunk, 'apply_async') as first:
                compute_lookup_embeddings_task.run(
                    self.task.task_id, self.config.id, refresh=False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'failed')
        self.assertFalse(first.called)


# ---------------------------------------------------------------------
# Text deidentification (extractor.services.text_deidentification)
# ---------------------------------------------------------------------

class DeidRecognizerTests(SimpleTestCase):
    """Text-specific recognizer patterns — no NLP engine required."""

    def _rec(self, name):
        from extractor.services.deid_recognizers import build_text_recognizers
        return {r.name: r for r in build_text_recognizers()}[name]

    def test_abha_number(self):
        rec = self._rec('AbhaNumberRecognizer')
        results = rec.analyze("ABHA 91-2345-6789-0123", entities=["IN_ABHA"])
        self.assertTrue(results)

    def test_abha_address(self):
        rec = self._rec('AbhaAddressRecognizer')
        results = rec.analyze("health id ramesh.k@abdm", entities=["IN_ABHA"])
        self.assertTrue(results)

    def test_pincode_context_gated_low_score(self):
        rec = self._rec('IndianPinCodeRecognizer')
        results = rec.analyze("PIN 560001", entities=["IN_PINCODE"])
        self.assertTrue(results)
        # Base score stays below the analyzer threshold — context must lift it
        self.assertLess(results[0].score, 0.35)

    def test_mrn_recognizer_is_context_gated(self):
        rec = self._rec('MedicalRecordNumberRecognizer')
        results = rec.analyze("MRN 12345678", entities=["MEDICAL_RECORD_NUMBER"])
        self.assertTrue(results)
        self.assertLess(results[0].score, 0.35)

    def test_date_patterns(self):
        rec = self._rec('DatePatternRecognizer')
        for surface in ('12/03/2024', '12-03-24', '2024-03-12',
                        '12 Mar 2024', 'March 12th, 2024'):
            results = rec.analyze(f"seen on {surface}", entities=["DATE_TIME"])
            self.assertTrue(results, f"no date match for {surface}")

    def test_title_name(self):
        rec = self._rec('IndianTitleNameRecognizer')
        results = rec.analyze("Dr. Sharma referred the patient",
                              entities=["PERSON"])
        self.assertTrue(results)

    def test_patient_adhoc_recognizers(self):
        import datetime as dt
        from unittest.mock import Mock
        from extractor.services.deid_recognizers import (
            build_patient_recognizers)
        patient = Mock(patient_id='P-10293',
                       date_of_birth=dt.date(1990, 1, 5))
        recs = build_patient_recognizers(patient)
        self.assertEqual(len(recs), 2)
        pid_results = recs[0].analyze("ref P-10293", entities=["PATIENT_ID"])
        self.assertTrue(pid_results)
        dob_results = recs[1].analyze("DOB 05/01/1990", entities=["DATE_TIME"])
        self.assertTrue(dob_results)

    def test_patient_adhoc_recognizers_none(self):
        from extractor.services.deid_recognizers import (
            build_patient_recognizers)
        self.assertEqual(build_patient_recognizers(None), [])


class DeidReplacementTests(SimpleTestCase):
    """Pure splice/shift/tag logic."""

    def test_shifted_date_preserves_format(self):
        from extractor.services.text_deidentification import _shifted_date_text
        self.assertEqual(_shifted_date_text('12/03/2024', 10), '22/03/2024')
        self.assertEqual(_shifted_date_text('2024-03-12', -2), '2024-03-10')
        out = _shifted_date_text('12 Mar 2024', 30)
        self.assertIn('Apr', out)

    def test_shifted_date_preserves_all_surface_formats(self):
        """Every shape the recognizers emit must shift in place. The earlier
        version degraded anything outside 7 hardcoded patterns to <DATE>
        (e.g. '2024/03/15', '15 March 24', '15th Mar 2024',
        '15/08/2024 14:30')."""
        from extractor.services.text_deidentification import _shifted_date_text
        cases = [
            ('2024/03/15', 10, '2024/03/25'),
            ('2024.03.15', 10, '2024.03.25'),
            ('15-03-2024', 10, '25-03-2024'),
            ('15.03.2024', 10, '25.03.2024'),
            ('15/03/24', 10, '25/03/24'),
            ('15-03-24', 10, '25-03-24'),
            ('15.03.24', 10, '25.03.24'),
            ('15 March 2024', 10, '25 March 2024'),
            ('15 Mar 2024', 10, '25 Mar 2024'),
            ('15 MARCH 2024', 20, '04 APRIL 2024'),
            ('15th March 2024', 10, '25th March 2024'),
            ('21st March 2024', 10, '31st March 2024'),
            ('15 March 24', 10, '25 March 24'),
            ('March 15, 2024', 10, 'March 25, 2024'),
            ('March 15 2024', 10, 'March 25 2024'),  # no comma added
            ('Mar 15 24', 10, 'Mar 25 24'),
            ('March 2024', 32, 'April 2024'),
            ('15/08/2024 14:30', 10, '25/08/2024 14:30'),
            # time after a separating comma must not break the date shape
            ('16th September 2026, 14:59', 10, '26th September 2026, 14:59'),
            ('16/09/2026, 14:59', 10, '26/09/2026, 14:59'),
            ('September 16, 2026, 14:59', 10, 'September 26, 2026, 14:59'),
            ('28/12/2024', 10, '07/01/2025'),
            ('28/12/24', 10, '07/01/25'),
            ('99/03/25', 10, '99/04/04'),
        ]
        for surface, shift, want in cases:
            with self.subTest(surface=surface):
                self.assertEqual(_shifted_date_text(surface, shift), want)

    def test_shifted_date_round_trips_through_unshift(self):
        """Shifted surfaces must re-parse under the dayfirst convention in
        _unshift_date, or extracted dates would come back corrupted."""
        from extractor.services.text_deidentification import _shifted_date_text
        from extractor.services.instructor_extractor import (
            InstructorExtractionService)
        cases = [
            ('15 March 24', 10, '2024-03-15'),
            ('2024/03/15', 10, '2024-03-15'),
            ('15/03/24', -5, '2024-03-15'),
            ('March 15 2024', 10, '2024-03-15'),
            ('21st March 2024', 10, '2024-03-21'),
            ('15/08/2024 14:30', 7, '2024-08-15 14:30:00'),
            ('16th September 2026, 14:59', 10, '2026-09-16 14:59:00'),
        ]
        for surface, shift, want in cases:
            with self.subTest(surface=surface):
                shifted = _shifted_date_text(surface, shift)
                self.assertFalse(shifted.startswith('<DATE>'))
                self.assertEqual(
                    InstructorExtractionService._unshift_date(shifted, shift),
                    want)

    def test_unparseable_date_becomes_tag(self):
        from extractor.services.text_deidentification import _shifted_date_text
        self.assertEqual(_shifted_date_text('next Tuesday', 10), '<DATE>')

    def test_tag_numbering_consistent_per_value(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        tag_map = {}
        t1 = TextDeidentificationService._tag_for('PERSON', 'Ramesh', tag_map)
        t2 = TextDeidentificationService._tag_for('PERSON', 'Ramesh', tag_map)
        t3 = TextDeidentificationService._tag_for('PERSON', 'Suresh', tag_map)
        self.assertEqual(t1, '<PERSON_1>')
        self.assertEqual(t1, t2)
        self.assertEqual(t3, '<PERSON_2>')

    def test_patient_id_fixed_tag(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        self.assertEqual(
            TextDeidentificationService._tag_for('PATIENT_ID', 'P-1', {}),
            '<PATIENT_ID>')

    def test_apply_replacements_right_to_left(self):
        from presidio_analyzer import RecognizerResult
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        text = 'Ramesh visited on 12/03/2024 with Suresh'
        results = [
            RecognizerResult(entity_type='PERSON', start=0, end=6, score=0.9),
            RecognizerResult(entity_type='DATE_TIME', start=18, end=28, score=0.5),
            RecognizerResult(entity_type='PERSON', start=34, end=40, score=0.9),
        ]
        out = TextDeidentificationService._apply_replacements(
            text, results, 10, {})
        # First occurrence in document order gets _1
        self.assertTrue(out.startswith('<PERSON_1>'))
        self.assertIn('<PERSON_2>', out)
        self.assertIn('22/03/2024', out)
        self.assertNotIn('Ramesh', out)

    def test_resolve_overlaps_containing_span_wins_regardless_of_score(self):
        # A span that fully contains a lower-scored overlap wins regardless of
        # score (the MRN case: the full 'MR/24/012817' span must beat the NER's
        # two-letter 'MR' org tag, else the record digits leak). Here LOCATION
        # (0-10, 0.4) contains PERSON (0-6, 0.9), so it wins; the contained
        # PERSON is covered by LOCATION and drops.
        from presidio_analyzer import RecognizerResult
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        results = [
            RecognizerResult(entity_type='PERSON', start=0, end=6, score=0.9),
            RecognizerResult(entity_type='LOCATION', start=0, end=10, score=0.4),
            RecognizerResult(entity_type='DATE_TIME', start=20, end=24, score=0.5),
        ]
        kept = TextDeidentificationService._resolve_overlaps(results)
        self.assertEqual(len(kept), 2)
        self.assertEqual([r.entity_type for r in kept],
                         ['LOCATION', 'DATE_TIME'])

    def test_resolve_overlaps_keeps_highest_score_when_no_containment(self):
        # Overlapping spans that do NOT contain one another: the higher-scored
        # span wins. PERSON (0-6, 0.9) partially overlaps LOCATION (4-12, 0.4)
        # without either containing the other, so PERSON is kept.
        from presidio_analyzer import RecognizerResult
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        results = [
            RecognizerResult(entity_type='PERSON', start=0, end=6, score=0.9),
            RecognizerResult(entity_type='LOCATION', start=4, end=12, score=0.4),
        ]
        kept = TextDeidentificationService._resolve_overlaps(results)
        self.assertEqual([r.entity_type for r in kept], ['PERSON'])

    def test_resolve_overlaps_longest_wins_on_score_tie(self):
        # Equal scores and no containment: the longer span wins the tie.
        from presidio_analyzer import RecognizerResult
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        results = [
            RecognizerResult(entity_type='PERSON', start=0, end=6, score=0.5),
            RecognizerResult(entity_type='LOCATION', start=2, end=10, score=0.5),
        ]
        kept = TextDeidentificationService._resolve_overlaps(results)
        self.assertEqual([r.entity_type for r in kept], ['LOCATION'])

    def test_unshift_date_round_trip(self):
        from extractor.services.instructor_extractor import (
            InstructorExtractionService)
        # Shifted date in the deidentified text, un-shifted on save
        self.assertEqual(
            InstructorExtractionService._unshift_date('2024-03-22', 10),
            '2024-03-12')
        # Deid re-emits dates in the source's surface format — DD/MM must
        # parse day-first or ambiguous dates would be silently corrupted
        self.assertEqual(
            InstructorExtractionService._unshift_date('05/06/2024', 10),
            '2024-05-26')
        self.assertEqual(
            InstructorExtractionService._unshift_date('05/06/2024 14:30', -10),
            '2024-06-15 14:30:00')
        self.assertIsNone(
            InstructorExtractionService._unshift_date('not-a-date', 10))


class _FakeAnalyzer:
    """Stand-in analyzer: detects 'Ramesh Kumar' and dd/mm/yyyy dates."""

    def analyze(self, text, language='en', score_threshold=0.35,
                ad_hoc_recognizers=None):
        import re as _re
        from presidio_analyzer import RecognizerResult
        results = []
        for m in _re.finditer(_re.escape('Ramesh Kumar'), text):
            results.append(RecognizerResult(
                entity_type='PERSON', start=m.start(), end=m.end(), score=0.9))
        for m in _re.finditer(r'\d{2}/\d{2}/\d{4}', text):
            results.append(RecognizerResult(
                entity_type='DATE_TIME', start=m.start(), end=m.end(),
                score=0.5))
        for rec in ad_hoc_recognizers or []:
            results.extend(rec.analyze(
                text, entities=list(rec.supported_entities)))
        return results


class TextDeidPipelineTests(TestCase):
    """End-to-end deidentify() against real ProcessedText rows."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = self.settings(MEDIA_ROOT=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)

        from client_app.models import Patient, SiteConfiguration
        SiteConfiguration.objects.create(
            chavi_center_id='C1', center_name='Test Center')
        self.patient = Patient.objects.create(patient_id='P-T1')
        self.user = User.objects.create(username='deidtester')
        self.upload = FileUpload.objects.create(
            patient_id=self.patient, file='note.pdf')

    def _source_row(self, filename, content):
        path = os.path.join(self._tmp.name, filename)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return ProcessedText.objects.create(
            file_upload=self.upload, processed_file_path=filename)

    def _fake_engine(self):
        return (_FakeAnalyzer(), 'full')

    def test_text_path_creates_deid_version(self):
        from unittest.mock import patch
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        src = self._source_row(
            'v1.md',
            'Pt Ramesh Kumar seen on 12/03/2024. Ramesh Kumar stable.')
        with patch.object(TextDeidentificationService, '_get_analyzer',
                          side_effect=self._fake_engine):
            out = TextDeidentificationService.deidentify(src, user=self.user)

        self.assertTrue(out.deidentified)
        self.assertEqual(out.deidentified_source, src)
        self.assertIsNotNone(out.deid_date_shift_days)
        self.assertEqual(out.deid_entities.get('PERSON'), 2)

        from extractor.services.file_processor import FileProcessorService
        content = FileProcessorService.get_processed_content(out)
        self.assertNotIn('Ramesh Kumar', content)
        # Same original value reuses the same numbered tag
        self.assertEqual(content.count('<PERSON_1>'), 2)
        self.assertIn('.deid.', out.processed_file_path)

    def test_already_deidentified_is_noop(self):
        from unittest.mock import patch
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        src = self._source_row('v1.md', 'text')
        with patch.object(TextDeidentificationService, '_get_analyzer',
                          side_effect=self._fake_engine):
            out = TextDeidentificationService.deidentify(src)
            again = TextDeidentificationService.deidentify(out)
        self.assertIsNone(again)

    def test_csv_path_mapped_columns_and_cell_ner(self):
        from unittest.mock import patch
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        src = self._source_row(
            'v1.csv',
            'patient_name,dob,notes\n'
            'Ramesh Kumar,12/03/1970,"Ramesh Kumar seen today"\n')
        with patch.object(TextDeidentificationService, '_get_analyzer',
                          side_effect=self._fake_engine):
            out = TextDeidentificationService.deidentify(src)

        self.assertIn('patient_name', out.deid_csv_columns_flagged)
        self.assertIn('dob', out.deid_csv_columns_flagged)

        import csv as _csv, io as _io
        from extractor.services.file_processor import FileProcessorService
        rows = list(_csv.reader(
            _io.StringIO(FileProcessorService.get_processed_content(out))))
        self.assertEqual(rows[0], ['patient_name', 'dob', 'notes'])
        name_cell, dob_cell, notes_cell = rows[1]
        self.assertEqual(name_cell, '<PERSON_1>')
        self.assertNotEqual(dob_cell, '12/03/1970')
        self.assertNotIn('Ramesh Kumar', notes_cell)
        # Same value in the free-text cell reuses the column's tag
        self.assertIn('<PERSON_1>', notes_cell)

    def test_manual_edit_and_review_flags(self):
        from unittest.mock import patch
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        src = self._source_row('v1.md', 'Pt Ramesh Kumar.')
        with patch.object(TextDeidentificationService, '_get_analyzer',
                          side_effect=self._fake_engine):
            out = TextDeidentificationService.deidentify(src)

        TextDeidentificationService.save_manual_edit(
            out, 'Pt <MANUAL>.', user=self.user)
        out.refresh_from_db()
        self.assertEqual(out.deid_manual_edits, 1)

        self.assertFalse(out.deid_reviewed)
        TextDeidentificationService.mark_reviewed(out, user=self.user)
        out.refresh_from_db()
        self.assertTrue(out.deid_reviewed)
        self.assertEqual(out.deid_reviewed_by, self.user)
        self.assertIsNotNone(out.deid_reviewed_at)

    def test_deid_map_and_restore(self):
        """Each tag's original is recorded; restore puts the value back."""
        from unittest.mock import patch
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        src = self._source_row(
            'v1.md', 'Pt Ramesh Kumar seen. Ramesh Kumar stable.')
        with patch.object(TextDeidentificationService, '_get_analyzer',
                          side_effect=self._fake_engine):
            out = TextDeidentificationService.deidentify(src)

        entry = next(e for e in out.deid_map if e['tag'] == '<PERSON_1>')
        self.assertEqual(entry['original'], 'Ramesh Kumar')
        self.assertEqual(entry['count'], 2)

        n = TextDeidentificationService.restore_tag(out, '<PERSON_1>')
        self.assertEqual(n, 2)
        from extractor.services.file_processor import FileProcessorService
        content = FileProcessorService.get_processed_content(out)
        self.assertEqual(content.count('Ramesh Kumar'), 2)
        self.assertNotIn('<PERSON_1>', content)
        out.refresh_from_db()
        self.assertFalse(
            any(e['tag'] == '<PERSON_1>' for e in out.deid_map))


class DeidUnshiftOnSaveTests(TestCase):
    """save_extraction_results restores real dates for deid sources."""

    def setUp(self):
        from client_app.models import Patient, SiteConfiguration
        SiteConfiguration.objects.create(
            chavi_center_id='C1', center_name='Test Center')
        self.patient = Patient.objects.create(patient_id='P-U1')
        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt_diag = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.diagnosis)
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_diag,
            field=make_field(self.diagnosis, 'diagnosis_date',
                             field_type=EntityTypeChoices.DATE))
        self.user = User.objects.create(username='deidwriter')
        self.upload = FileUpload.objects.create(
            patient_id=self.patient, file='note.pdf')
        self.processed = ProcessedText.objects.create(
            file_upload=self.upload, deidentified=True,
            deid_date_shift_days=30)
        self.job = ExtractionJob.objects.create(
            response_model=self.rm, processed_file=self.processed,
            extracted_by=self.user)

    def test_date_fields_are_unshifted(self):
        InstructorExtractionService.save_extraction_results(
            self.job,
            {'diagnosis': [{'diagnosis_date': '2024-02-01'}]},
            self.user)
        result = ExtractionResult.objects.get(
            extraction_job=self.job,
            database_field__clientapp_field_name='diagnosis_date')
        # Shifted +30 in text -> stored as real date 30 days earlier
        self.assertEqual(result.extracted_data, '2024-01-02')

    def test_non_deid_source_is_untouched(self):
        self.processed.deidentified = False
        self.processed.save()
        InstructorExtractionService.save_extraction_results(
            self.job,
            {'diagnosis': [{'diagnosis_date': '2024-02-01'}]},
            self.user)
        result = ExtractionResult.objects.get(
            extraction_job=self.job,
            database_field__clientapp_field_name='diagnosis_date')
        self.assertEqual(result.extracted_data, '2024-02-01')

    def test_drop_entity_types_and_bare_dates(self):
        from presidio_analyzer import RecognizerResult
        from extractor.services.text_deidentification import (
            TextDeidentificationService)
        text = '45-year-old, nodes 26, lesion 3.2cm, DOB 12/03/1970'
        results = [
            RecognizerResult('AGE', 0, 2, 0.8),          # "45"
            RecognizerResult('ID', 16, 18, 0.8),         # "26"
            RecognizerResult('ID', 29, 34, 0.8),         # "3.2cm"
            RecognizerResult('DATE_TIME', 41, 51, 0.5),  # real date kept
        ]
        kept = TextDeidentificationService._filter_results(text, results)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].entity_type, 'DATE_TIME')


class ExtractionPlanTests(TestCase):
    def setUp(self):
        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.pathology = make_table('pathology', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.ihc = make_table('immunohistochemistry', [
            {'field': 'pathology', 'model': 'client_app.pathology', 'pk_field': 'pk'},
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt_d = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.diagnosis)
        self.rmt_p = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.pathology)
        self.rmt_i = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.ihc)

    def attach(self, model_table, name, order, **kwargs):
        field = make_field(model_table.database_table, name, **kwargs)
        ResponseModelTableField.objects.create(
            response_model_table=model_table, field=field, order=order)
        return field

    def _plan(self, batch):
        from extractor.services.extraction_split import plan_extraction_calls
        return plan_extraction_calls(self.rm, batch)

    def test_order_is_parents_before_children(self):
        self.attach(self.rmt_d, 'd_date', 0)
        self.attach(self.rmt_p, 'p_date', 0)
        self.attach(self.rmt_i, 'i_date', 0)
        plan = self._plan(10)
        tables = [c['model_table'].database_table for c in plan]
        self.assertEqual(tables, [self.diagnosis, self.pathology, self.ihc])
        ihc_call = plan[2]
        self.assertEqual(ihc_call['ancestry'], [self.rmt_d, self.rmt_p])
        self.assertEqual(plan[0]['ancestry'], [])

    def test_plan_is_one_call_per_table_with_all_fields(self):
        # batch size is ignored — even batch=1 keeps the whole table in
        # a single call
        for i in range(12):
            self.attach(self.rmt_d, f'site_{i}', i, lookup_field=True)
        for i in range(25):
            self.attach(self.rmt_d, f'plain_{i}', 12 + i, field_type='int')
        self.attach(self.rmt_p, 'p_date', 0)
        plan = self._plan(1)
        d_calls = [c for c in plan if c['model_table'] == self.rmt_d]
        self.assertEqual(len(d_calls), 1)
        self.assertEqual(d_calls[0]['kind'], 'table')
        self.assertEqual(len(d_calls[0]['fields']), 37)
        self.assertEqual([f.clientapp_field_name for f in d_calls[0]['fields']][:3],
                         ['site_0', 'site_1', 'site_2'])
        p_calls = [c for c in plan if c['model_table'] == self.rmt_p]
        self.assertEqual(len(p_calls), 1)
        self.assertEqual(p_calls[0]['kind'], 'table')
        self.assertEqual(len(p_calls[0]['fields']), 1)

    def test_small_table_gets_one_table_call(self):
        # all fields (lookup and plain together) in one call, in
        # configuration order
        for i in range(3):
            self.attach(self.rmt_d, f'site_{i}', i, lookup_field=True)
        for i in range(4):
            self.attach(self.rmt_d, f'plain_{i}', 3 + i)
        plan = [c for c in self._plan(10) if c['model_table'] == self.rmt_d]
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]['kind'], 'table')
        self.assertEqual([f.clientapp_field_name for f in plan[0]['fields']],
                         ['site_0', 'site_1', 'site_2',
                          'plain_0', 'plain_1', 'plain_2', 'plain_3'])

    def test_table_without_extractable_fields_makes_no_call(self):
        f = make_field(self.diagnosis, 'inactive_field', is_active=False)
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_d, field=f, order=0)
        plan = [c for c in self._plan(10) if c['model_table'] == self.rmt_d]
        self.assertEqual(plan, [])


class TablePromptTests(TestCase):
    def setUp(self):
        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.pathology = make_table('pathology', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt_d = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.diagnosis)
        self.rmt_p = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.pathology)
        # help_text is the question itself — site_0 and plain_0 carry
        # real question-form help texts, the rest use the fallback
        site_questions = {
            'site_0': 'Select the anatomical location of the cancer? (FMA code)',
        }
        for i in range(4):
            f = make_field(self.diagnosis, f'site_{i}', lookup_field=True,
                           help_text=site_questions.get(f'site_{i}', ''))
            ResponseModelTableField.objects.create(
                response_model_table=self.rmt_d, field=f, order=i)
        plain_questions = {'plain_0': 'How many lymph nodes were examined in total?'}
        for i in range(3):
            f = make_field(self.diagnosis, f'plain_{i}', field_type='int',
                           help_text=plain_questions.get(f'plain_{i}', ''))
            ResponseModelTableField.objects.create(
                response_model_table=self.rmt_d, field=f, order=4 + i)
        f = make_field(self.pathology, 'date_pathology',
                       help_text='When was the pathology report dated? (DD/MM/YYYY)')
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_p, field=f, order=0)

    def _fields_for(self, model_table):
        return [tf.field for tf in ResponseModelTableField.objects.filter(
            response_model_table=model_table,
            field__is_active=True).select_related('field').order_by('order')
            if tf.field.is_extractable()]

    def _diagnosis_fields(self):
        return self._fields_for(self.rmt_d)

    def _pathology_fields(self):
        return self._fields_for(self.rmt_p)

    def _f(self, name):
        return DatabaseField.objects.get(clientapp_field_name=name)

    def test_document_comes_before_questions(self):
        from extractor.services.extraction_split import (
            build_table_question_prompt)
        msgs = build_table_question_prompt(
            self.rm, self.rmt_p, self._pathology_fields(), 'DOC TEXT')
        content = msgs[-1]['content']
        self.assertLess(content.index('<document>'), content.index('QUESTIONS'))
        self.assertIn('DOC TEXT', content)

    def test_questions_are_questions_and_lookup_lists_choices(self):
        from extractor.services.extraction_split import (
            build_table_question_prompt)
        msgs = build_table_question_prompt(
            self.rm, self.rmt_d, self._diagnosis_fields(), 'DOC TEXT',
            resolved_options={self._f('site_0').id: [
                {'code': 'A', 'label': 'Label A'},
                {'code': 'B', 'label': 'Label B'}]})
        content = msgs[-1]['content']
        lines = content.splitlines()
        site_q = next(l for l in lines if 'site_0:' in l)
        # the field's question-form help text is used verbatim
        self.assertEqual(
            site_q.strip(),
            '1. site_0: Select the anatomical location of the cancer? '
            '(FMA code)')
        self.assertIn('select from these only', content)
        self.assertIn('Label A; Label B', content)
        # the count question reads as a natural question too
        self.assertIn('plain_0: How many lymph nodes were examined in total?',
                      content)

    def test_help_text_is_the_question_with_fallback(self):
        from extractor.services.extraction_split import _question_for
        f = self._f('site_0')
        self.assertEqual(_question_for(f),
                         'Select the anatomical location of the cancer? (FMA code)')
        # a help text without a trailing '?' gets one
        f1 = self._f('site_1')
        f1.help_text = 'Side of the body where the lesion is on'
        self.assertEqual(_question_for(f1),
                         'Side of the body where the lesion is on?')
        # a trailing period becomes the question mark
        f2 = self._f('site_2')
        f2.help_text = 'Anatomical location of the lesion.'
        self.assertEqual(_question_for(f2),
                         'Anatomical location of the lesion?')
        # no help text at all -> generated question
        f3 = self._f('site_3')
        f3.help_text = ''
        self.assertEqual(_question_for(f3), 'What is the site 3?')

    def test_docstring_is_included_as_table_context(self):
        import client_app.models as cm
        from extractor.services.extraction_split import (
            build_table_question_prompt)
        msgs = build_table_question_prompt(
            self.rm, self.rmt_d, self._diagnosis_fields(), 'DOC TEXT')
        content = msgs[-1]['content']
        doc = (cm.Diagnosis.__doc__ or '').strip()
        self.assertIn('TABLE CONTEXT:', content)
        if doc:
            self.assertIn(doc.splitlines()[0].strip(), content)

    def test_parent_records_block_present_only_for_children(self):
        from extractor.services.extraction_split import (
            build_table_question_prompt)
        parent = [{'site_0': 'Left', 'plain_0': 1}]
        msgs = build_table_question_prompt(
            self.rm, self.rmt_p, self._pathology_fields(), 'DOC',
            ancestor_records=parent)
        self.assertIn('PARENT RECORDS:', msgs[-1]['content'])
        self.assertIn('Left', msgs[-1]['content'])
        msgs2 = build_table_question_prompt(
            self.rm, self.rmt_d, self._diagnosis_fields(), 'DOC')
        self.assertNotIn('PARENT RECORDS:', msgs2[-1]['content'])

    def test_neutral_granularity_line_present(self):
        from extractor.services.extraction_split import (
            build_table_question_prompt)
        msgs = build_table_question_prompt(
            self.rm, self.rmt_p, self._pathology_fields(), 'DOC')
        content = msgs[-1]['content']
        self.assertIn('ONE record', content)
        self.assertIn('{"records": []}', content)
        self.assertNotIn('exactly ONE record object for the', content)


class GapFillTests(TestCase):
    def setUp(self):
        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt_d = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.diagnosis)
        self.f_site = make_field(self.diagnosis, 'site_0', lookup_field=True)
        self.f_plain = make_field(self.diagnosis, 'plain_0', field_type='int')
        for i, f in enumerate((self.f_site, self.f_plain)):
            ResponseModelTableField.objects.create(
                response_model_table=self.rmt_d, field=f, order=i)
        self.source = 'PATHOLOGY REPORT. 1 node involved.'

    def _client(self, create):
        client = Mock()
        client.chat.completions.create_with_completion.side_effect = create
        return client

    def _call_refill(self, client, records, asked):
        from types import SimpleNamespace
        job = SimpleNamespace(id=99)
        ctx = {'lookup_rules': {}, 'source_text': self.source}
        return InstructorExtractionService._refill_null_fields(
            job, self.rm, self.rmt_d,
            [self.f_site, self.f_plain], asked, records, self.source,
            resolved_options={}, ancestor_records=None, client=client,
            client_config=self.rm.client, validation_context=ctx)

    def test_null_fields_for_requires_all_records_empty(self):
        from extractor.services.instructor_extractor import null_fields_for
        records = [{'plain_0': 1, 'site_0': None},
                   {'plain_0': None, 'site_0': None}]
        asked = null_fields_for(records, [self.f_site, self.f_plain])
        self.assertEqual(asked, [self.f_site])

    def test_refill_fills_only_nulls_and_never_overwrites(self):
        from types import SimpleNamespace
        records = [{'site_0': 'Left', 'plain_0': None,
                    'field_assessments': [{'field': 'plain_0', 'basis': 'unknown',
                                           'quotes': [], 'rationale': 'not stated'}]}]
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=9))

        def create(**kwargs):
            wrapper = kwargs['response_model']
            from typing import get_args, get_origin
            record_cls = get_args(wrapper.model_fields['records'].annotation)[0]
            # subset model: only the asked field (plus assessments)
            self.assertEqual(set(record_cls.model_fields),
                             {'plain_0', 'field_assessments'})
            # LLM answers the focused question with plain_0=2 and
            # (temptingly) site_0='Right'
            return wrapper(records=[{'plain_0': 2, 'site_0': 'Right',
                                     'field_assessments': [
                                         {'field': 'plain_0', 'basis': 'explicit',
                                          'quotes': ['1 node involved.'],
                                          'rationale': 'stated'}]}]), \
                completion

        updated, tokens = self._call_refill(
            self._client(create), records, [self.f_plain])
        self.assertEqual(updated[0]['plain_0'], 2)
        self.assertEqual(updated[0]['site_0'], 'Left')  # not overwritten
        self.assertEqual(tokens, 9)

    def test_refill_discards_misaligned_record_counts(self):
        from types import SimpleNamespace
        records = [
            {'site_0': 'Left', 'plain_0': None,
             'field_assessments': [{'field': 'plain_0', 'basis': 'unknown',
                                    'quotes': [], 'rationale': 'a'}]},
            {'site_0': 'Right', 'plain_0': None,
             'field_assessments': [{'field': 'plain_0', 'basis': 'unknown',
                                    'quotes': [], 'rationale': 'b'}]},
        ]
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=5))

        def create(**kwargs):
            wrapper = kwargs['response_model']
            # misaligned: a single record for two pass-1 records
            return wrapper(records=[{'plain_0': 1,
                                     'field_assessments': [
                                         {'field': 'plain_0', 'basis': 'explicit',
                                          'quotes': ['1 node involved.'],
                                          'rationale': 'one'}]}]), \
                completion

        updated, tokens = self._call_refill(
            self._client(create), records, [self.f_plain])
        self.assertEqual(updated, records)  # unchanged
        self.assertEqual(tokens, 5)  # the misaligned call was still spent

    def test_refill_prompt_asks_only_null_fields_and_keeps_document_first(self):
        from types import SimpleNamespace
        records = [{'site_0': 'Left', 'plain_0': None,
                    'field_assessments': [{'field': 'plain_0', 'basis': 'unknown',
                                           'quotes': [], 'rationale': 'not stated'}]}]
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=7))
        seen = {}

        def create(**kwargs):
            seen['messages'] = kwargs['messages']
            wrapper = kwargs['response_model']
            return wrapper(records=[{'plain_0': None,
                                     'field_assessments': [
                                         {'field': 'plain_0', 'basis': 'unknown',
                                          'quotes': [],
                                          'rationale': 'still missing'}]}]), \
                completion

        self._call_refill(self._client(create), records, [self.f_plain])
        content = seen['messages'][-1]['content']
        lower = content.lower()
        self.assertIn('previous extraction pass', lower)  # focused framing
        self.assertIn('left empty', lower)
        self.assertLess(content.index('<document>'), content.index('QUESTIONS'))
        self.assertNotIn('site_0', content)  # answered field not re-asked


class ChunkModelTests(TestCase):
    def setUp(self):
        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.diagnosis)
        self.f_site = make_field(self.diagnosis, 'site_0', lookup_field=True)
        self.f_count = make_field(self.diagnosis, 'count', field_type='int')
        for i, f in enumerate((self.f_site, self.f_count)):
            ResponseModelTableField.objects.create(
                response_model_table=self.rmt, field=f, order=i)

    def _build(self, fields, **kwargs):
        return PydanticModelBuilder.build_table_response_model(
            self.rmt, fields, **kwargs)

    def test_record_model_has_only_chunk_fields(self):
        wrapper, record = self._build([self.f_site, self.f_count],
                                      with_parent_index=True)
        self.assertEqual(
            set(record.model_fields),
            {'site_0', 'count', 'parent_index', 'field_assessments'})
        inst = wrapper(records=[{
            'site_0': 'Left', 'count': 0, 'parent_index': 0,
            'field_assessments': [{'field': 'count', 'basis': 'inferred',
                                   'quotes': ['absent'], 'rationale': 'absent'}],
        }])
        self.assertEqual(inst.records[0].site_0, 'Left')
        self.assertEqual(wrapper(records=[]).records, [])

    def test_lookup_membership_uses_context_rules(self):
        from pydantic import ValidationError
        _, record = self._build([self.f_site, self.f_count])
        ctx = {'lookup_rules': {'diagnosis.site_0': {
            'allowed': {'left'}, 'candidates': ['Left']}}}
        with self.assertRaises(ValidationError):
            record.model_validate(
                {'site_0': 'Wrong', 'count': 0,
                 'field_assessments': [{'field': 'count',
                                        'basis': 'unknown', 'quotes': [],
                                        'rationale': 'missing'}]},
                context=ctx)
        ok = record.model_validate(
            {'site_0': 'Left', 'count': 0,
             'field_assessments': [{'field': 'count',
                                    'basis': 'inferred', 'quotes': ['absent'],
                                    'rationale': 'absent'}]},
            context=ctx)
        self.assertEqual(ok.site_0, 'Left')

    def test_no_assessment_field_for_lookup_only_chunk(self):
        _, record = self._build([self.f_site])
        self.assertNotIn('field_assessments', record.model_fields)

    def test_date_pair_enforced_only_when_both_fields_in_chunk(self):
        from pydantic import ValidationError
        self.diagnosis.date_validation_pairs = [('d_start', 'd_end')]
        self.diagnosis.save()
        f_start = make_field(self.diagnosis, 'd_start',
                             field_type=EntityTypeChoices.DATE)
        f_end = make_field(self.diagnosis, 'd_end',
                           field_type=EntityTypeChoices.DATE)
        _, both = self._build([f_start, f_end])
        with self.assertRaises(ValidationError):
            both.model_validate({'d_start': '2024-02-01',
                                 'd_end': '2024-01-01'})
        _, single = self._build([f_start])
        ok = single.model_validate({'d_start': '2024-02-01'})
        self.assertEqual(ok.d_start, '2024-02-01')


class MergeTests(TestCase):
    def test_single_parent_rescue(self):
        from extractor.services.extraction_split import rescue_single_parent
        children = [{'a': 1, 'parent_index': None},
                    {'a': 2, 'parent_index': 9}]
        fixed = rescue_single_parent(children, 1)
        self.assertEqual(fixed, 2)
        self.assertEqual([c['parent_index'] for c in children], [0, 0])
        # with several parents, bad indices are left for nest_children to drop
        children2 = [{'a': 1, 'parent_index': None}]
        self.assertEqual(rescue_single_parent(children2, 2), 0)
        self.assertIsNone(children2[0]['parent_index'])

    def test_nest_children_by_parent_index(self):
        from extractor.services.extraction_split import nest_children
        parents = [{'x': 1}, {'x': 2}]
        children = [
            {'a': 'c1', 'parent_index': 0},
            {'a': 'c2', 'parent_index': 1},
            {'a': 'c3', 'parent_index': 7},
            {'a': 'c4', 'parent_index': None},
        ]
        out, dropped = nest_children(parents, children, 'pathology')
        self.assertEqual([c['a'] for c in out[0]['pathology']], ['c1'])
        self.assertEqual([c['a'] for c in out[1]['pathology']], ['c2'])
        self.assertNotIn('parent_index', out[0]['pathology'][0])
        self.assertEqual(dropped, 2)


class StagePlanningTests(TestCase):
    def setUp(self):
        import hashlib
        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.pathology = make_table('pathology', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt_d = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.diagnosis)
        self.rmt_p = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.pathology)
        f1 = make_field(self.diagnosis, 'site_0', lookup_field=True)
        f2 = make_field(self.diagnosis, 'plain_0', field_type='int')
        for i, f in enumerate((f1, f2)):
            ResponseModelTableField.objects.create(
                response_model_table=self.rmt_d, field=f, order=i)
        f3 = make_field(self.pathology, 'date_pathology')
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_p, field=f3, order=0)

        self.user = User.objects.create(username='planner')
        self.source = 'PATHOLOGY REPORT text'
        self.upload = FileUpload.objects.create(file='s.pdf')
        self.processed = ProcessedText.objects.create(
            file_upload=self.upload, content_length=len(self.source))
        self.digest = hashlib.sha256(self.source.encode('utf-8')).hexdigest()

    def _job(self, status):
        return ExtractionJob.objects.create(
            response_model=self.rm, processed_file=self.processed,
            extracted_by=self.user, extraction_status=status,
            input_content_hash=self.digest)

    def _patch_mining(self):
        self.enterContext(patch.object(
            InstructorExtractionService, 'mine_lookup_snippets',
            return_value=({}, 0)))
        self.enterContext(patch.object(
            InstructorExtractionService, 'recheck_empty_snippets',
            return_value=({}, 0, ['diagnosis.site_0'])))
        self.enterContext(patch.object(
            InstructorExtractionService, '_get_llm_client',
            return_value=Mock()))

    def test_stage_mine_traces_one_prompt_entry_per_call(self):
        from extractor.models import ExtractionStatusChoices
        from extractor.services.extraction_split import plan_extraction_calls
        self._patch_mining()
        job = self._job(ExtractionStatusChoices.AWAITING_MINING)
        result = InstructorExtractionService.stage_mine(job, self.source)
        self.assertIsNone(result)  # parked for approval
        job.refresh_from_db()
        entries = [e for e in job.stage_trace
                   if e.get('stage') == 'extraction' and e.get('kind') == 'prompt']
        expected = plan_extraction_calls(self.rm)
        self.assertEqual(len(entries), len(expected))
        self.assertEqual(
            [e['index'] for e in entries],
            list(range(len(expected))))
        self.assertTrue(all('messages' in e and e['fields'] for e in entries))
        self.assertEqual(job.config_snapshot['extraction_plan_version'], 2)
        self.assertEqual(job.extraction_status,
                         ExtractionStatusChoices.AWAITING_EXTRACTION)
        self.assertEqual(json.loads(job.prompt_snapshot)[0]['table'],
                         'diagnosis')

    def test_stage_mine_refuses_call_over_context_budget(self):
        from extractor.models import ExtractionStatusChoices
        self._patch_mining()
        # mutate the cached client instance — ORM .update() would not
        # reach the already-resolved response_model.client object
        self.rm.client.context_size = 100
        job = self._job(ExtractionStatusChoices.AWAITING_MINING)
        with self.assertRaises(ValueError):
            InstructorExtractionService.stage_mine(job, self.source)

    def test_stage_prepare_no_lookup_builds_plan_entries(self):
        from extractor.models import ExtractionStatusChoices
        f1 = DatabaseField.objects.get(
            clientapp_field_name='site_0',
            clientapp_database_table=self.diagnosis)
        f1.lookup_field = False
        f1.save()
        job = self._job(ExtractionStatusChoices.PENDING)
        result = InstructorExtractionService.stage_prepare(job, self.source)
        self.assertIsNone(result)
        job.refresh_from_db()
        entries = [e for e in job.stage_trace
                   if e.get('stage') == 'extraction' and e.get('kind') == 'prompt']
        self.assertEqual(len(entries), 2)  # diagnosis + pathology, one call each
        self.assertEqual([e['table'] for e in entries], ['diagnosis', 'pathology'])
        self.assertTrue(all(e['call_kind'] == 'table' for e in entries))
        self.assertEqual(job.config_snapshot['extraction_plan_version'], 2)
        self.assertEqual(job.extraction_status,
                         ExtractionStatusChoices.AWAITING_EXTRACTION)


class TableExtractTests(TestCase):
    def setUp(self):
        import hashlib
        self.diagnosis = make_table('diagnosis', [PATIENT_STEP])
        self.pathology = make_table('pathology', [
            {'field': 'diagnosis', 'model': 'client_app.diagnosis', 'pk_field': 'pk'},
            PATIENT_STEP])
        self.rm = make_response_model()
        self.rmt_d = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.diagnosis)
        self.rmt_p = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.pathology)
        make_field(self.diagnosis, 'site_0', lookup_field=True)
        make_field(self.diagnosis, 'plain_0', field_type='int')
        f_date = make_field(self.pathology, 'date_pathology')
        rmtf = ResponseModelTableField.objects
        rmtf.create(response_model_table=self.rmt_d,
                    field=DatabaseField.objects.get(
                        clientapp_field_name='site_0',
                        clientapp_database_table=self.diagnosis), order=0)
        rmtf.create(response_model_table=self.rmt_d,
                    field=DatabaseField.objects.get(
                        clientapp_field_name='plain_0',
                        clientapp_database_table=self.diagnosis), order=1)
        rmtf.create(response_model_table=self.rmt_p, field=f_date, order=0)

        self.user = User.objects.create(username='runner')
        self.upload = FileUpload.objects.create(file='s.pdf')
        self.source = 'PATHOLOGY REPORT. 1 node involved.'
        self.processed = ProcessedText.objects.create(
            file_upload=self.upload, content_length=len(self.source))
        digest = hashlib.sha256(self.source.encode('utf-8')).hexdigest()
        self.job = ExtractionJob.objects.create(
            response_model=self.rm, processed_file=self.processed,
            extracted_by=self.user,
            extraction_status=ExtractionStatusChoices.AWAITING_EXTRACTION,
            input_content_hash=digest,
            config_snapshot={'field_assessment_version': 1,
                             'extraction_plan_version': 2})
        # Trace the real plan exactly as stage_mine would (mining is
        # patched out) and freeze the job
        with patch.object(InstructorExtractionService, 'mine_lookup_snippets',
                          return_value=({}, 0)), \
             patch.object(InstructorExtractionService,
                          'recheck_empty_snippets',
                          return_value=({}, 0, ['diagnosis.site_0'])), \
             patch.object(InstructorExtractionService, '_get_llm_client',
                          return_value=Mock()):
            self.job.extraction_status = \
                ExtractionStatusChoices.AWAITING_MINING
            InstructorExtractionService.stage_mine(self.job, self.source)
        self.job.refresh_from_db()
        self.entries = [e for e in self.job.stage_trace
                        if e.get('stage') == 'extraction'
                        and e.get('kind') == 'prompt']

    def _record_for(self, wrapper, entry):
        table = entry['table']
        if table == 'diagnosis':
            # one call per table: the diagnosis call carries both the
            # lookup and the reasoning fields
            return wrapper(records=[{
                'site_0': 'Left',
                'plain_0': 1,
                'field_assessments': [{
                    'field': 'plain_0', 'basis': 'explicit',
                    'quotes': ['1 node involved.'],
                    'rationale': 'stated'}],
            }])
        if table == 'pathology':
            return wrapper(records=[{
                'date_pathology': '2024-01-02', 'parent_index': 0}])
        if table == 'lesion':
            return wrapper(records=[{'lesion_size': 'tumor mass'}])
        raise AssertionError(f'unexpected call for {table}')

    def _run(self, fail_table=None):
        from types import SimpleNamespace
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=11))
        state = {'i': 0}

        def create(**kwargs):
            i = state['i']
            state['i'] += 1
            if fail_table and self.entries[i]['table'] == fail_table:
                raise Exception('provider down')
            return self._record_for(kwargs['response_model'],
                                    self.entries[i]), completion

        self._client = Mock()
        self._client.chat.completions.create_with_completion.side_effect = create
        self.enterContext(patch.object(InstructorExtractionService,
                                      '_get_llm_client',
                                      return_value=self._client))
        self.enterContext(patch('django.db.transaction.atomic',
                                side_effect=nullcontext))
        coverage = Mock()
        coverage.values.return_value.annotate.return_value = \
            [{'result_state': 'extracted', 'n': 1}]
        self.enterContext(patch.object(ExtractionResult.objects, 'filter',
                                      return_value=coverage))
        self.saved = self.enterContext(patch.object(
            InstructorExtractionService, 'save_extraction_results'))

    def test_table_extraction_saves_nested_result(self):
        self._run()
        result = InstructorExtractionService.stage_extract(self.job, self.source)
        self.assertTrue(result['success'])
        self.assertEqual(
            self._client.chat.completions.create_with_completion.call_count,
            len(self.entries))
        self.saved.assert_called_once()
        data = self.saved.call_args.args[1]
        self.assertEqual(set(data), {'diagnosis'})
        rec = data['diagnosis'][0]
        self.assertEqual(rec['site_0'], 'Left')
        self.assertEqual(rec['plain_0'], 1)
        self.assertEqual(rec['pathology'][0]['date_pathology'], '2024-01-02')
        self.assertNotIn('parent_index', rec['pathology'][0])
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status,
                         ExtractionStatusChoices.COMPLETED)
        self.assertEqual(
            json.loads(self.job.raw_llm_response)['diagnosis'][0]['site_0'],
            'Left')
        final = self.job.stage_trace[-1]
        self.assertEqual(final['kind'], 'result')
        self.assertEqual(final.get('failed_calls'), [])
        # no null fields -> no gap-fill passes; trace entries carry the
        # pass key (1 = the main per-table call)
        call_results = [e for e in self.job.stage_trace
                        if e.get('kind') == 'call_result']
        self.assertEqual(len(call_results), len(self.entries))
        self.assertTrue(all(e.get('pass') == 1 for e in call_results))

    def test_partial_save_when_a_call_fails(self):
        # Second independent root table (lesion, parent Patient) so a
        # failing diagnosis root can still leave saved data -> PARTIAL
        self.lesion = make_table('lesion', [PATIENT_STEP])
        self.rmt_l = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.lesion)
        f_lesion = make_field(self.lesion, 'lesion_size')
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_l, field=f_lesion, order=0)
        # Replace the traced extraction prompts with a plan that includes
        # the new lesion table
        self.job.stage_trace = [
            e for e in self.job.stage_trace
            if not (e.get('stage') == 'extraction'
                    and e.get('kind') == 'prompt')]
        entries = InstructorExtractionService.build_extraction_plan_entries(
            self.rm, self.source, self.rm.client, {})
        for entry in entries:
            InstructorExtractionService._append_trace(
                self.job, 'extraction', 'prompt',
                index=entry['index'], table=entry['table'],
                fields=entry['fields'], call_kind=entry['call_kind'],
                ancestry=entry['ancestry'], messages=entry['messages'])
        self.job.save()
        self.entries = [e for e in self.job.stage_trace
                        if e.get('stage') == 'extraction'
                        and e.get('kind') == 'prompt']
        self._run(fail_table='diagnosis')
        result = InstructorExtractionService.stage_extract(self.job, self.source)
        self.assertFalse(result['success'])
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status,
                         ExtractionStatusChoices.PARTIAL)
        self.assertIn('diagnosis', self.job.extraction_error)
        calls = self._client.chat.completions.create_with_completion
        self.assertEqual(calls.call_count, 2)
        # diagnosis failed (one call per table), lesion ran, pathology
        # skipped (not charged)
        self.saved.assert_called_once()
        data = self.saved.call_args.args[1]
        self.assertEqual(data.get('diagnosis', []), [])
        self.assertEqual(data['lesion'][0]['lesion_size'], 'tumor mass')

    def _setup_client(self, create):
        self._client = Mock()
        self._client.chat.completions.create_with_completion.side_effect = \
            create
        self.enterContext(patch.object(InstructorExtractionService,
                                      '_get_llm_client',
                                      return_value=self._client))
        self.enterContext(patch('django.db.transaction.atomic',
                                side_effect=nullcontext))
        coverage = Mock()
        coverage.values.return_value.annotate.return_value = \
            [{'result_state': 'extracted', 'n': 1}]
        self.enterContext(patch.object(ExtractionResult.objects, 'filter',
                                      return_value=coverage))
        self.saved = self.enterContext(patch.object(
            InstructorExtractionService, 'save_extraction_results'))

    def test_gap_fill_passes_run_for_null_fields(self):
        # diagnosis leaves plain_0 null on the main pass -> one focused
        # gap-fill re-ask for just that field, merged without touching
        # site_0.
        from types import SimpleNamespace
        from typing import get_args
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=5))
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            wrapper = kwargs['response_model']
            record_cls = get_args(
                wrapper.model_fields['records'].annotation)[0]
            fields = set(record_cls.model_fields)
            if fields == {'plain_0', 'field_assessments'}:
                # gap-fill re-ask: the subset model only asks plain_0
                self.assertIn('previous extraction pass',
                              kwargs['messages'][0]['content'])
                self.assertNotIn('site_0:',
                                 kwargs['messages'][0]['content'])
                return wrapper(records=[{
                    'plain_0': 1,
                    'field_assessments': [{
                        'field': 'plain_0', 'basis': 'explicit',
                        'quotes': ['1 node involved.'],
                        'rationale': 'stated'}]}]), completion
            if fields == {'site_0', 'plain_0', 'field_assessments'}:
                # diagnosis main pass: site_0 answered, plain_0 left null
                return wrapper(records=[{
                    'site_0': 'Left', 'plain_0': None,
                    'field_assessments': [{
                        'field': 'plain_0', 'basis': 'unknown',
                        'quotes': [], 'rationale': 'missing'}]}]), completion
            # pathology
            return wrapper(records=[{
                'date_pathology': '2024-01-02', 'parent_index': 0}]), \
                completion

        self._setup_client(create)
        result = InstructorExtractionService.stage_extract(self.job, self.source)
        self.assertTrue(result['success'])
        # diagnosis main + diagnosis gap-fill + pathology main
        self.assertEqual(
            self._client.chat.completions.create_with_completion.call_count,
            3)
        data = self.saved.call_args.args[1]
        rec = data['diagnosis'][0]
        self.assertEqual(rec['site_0'], 'Left')
        self.assertEqual(rec['plain_0'], 1)
        self.job.refresh_from_db()
        call_results = [e for e in self.job.stage_trace
                        if e.get('kind') == 'call_result'
                        and e.get('table') == 'diagnosis']
        self.assertEqual([e.get('pass') for e in call_results], [1, 2])

    def test_gap_fill_stops_when_second_pass_fills_nothing(self):
        # diagnosis leaves plain_0 null; the gap-fill re-ask returns it
        # still null -> nothing filled -> a third pass must NOT run.
        from types import SimpleNamespace
        from typing import get_args
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=5))
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            wrapper = kwargs['response_model']
            record_cls = get_args(
                wrapper.model_fields['records'].annotation)[0]
            fields = set(record_cls.model_fields)
            if fields == {'plain_0', 'field_assessments'}:
                # the re-ask still cannot find the value
                return wrapper(records=[{
                    'plain_0': None,
                    'field_assessments': [{
                        'field': 'plain_0', 'basis': 'unknown',
                        'quotes': [], 'rationale': 'missing'}]}]), completion
            if fields == {'site_0', 'plain_0', 'field_assessments'}:
                return wrapper(records=[{
                    'site_0': 'Left', 'plain_0': None,
                    'field_assessments': [{
                        'field': 'plain_0', 'basis': 'unknown',
                        'quotes': [], 'rationale': 'missing'}]}]), completion
            return wrapper(records=[{
                'date_pathology': '2024-01-02', 'parent_index': 0}]), \
                completion

        self._setup_client(create)
        result = InstructorExtractionService.stage_extract(self.job, self.source)
        self.assertTrue(result['success'])
        # diagnosis main + ONE gap-fill + pathology main — no third pass
        self.assertEqual(
            self._client.chat.completions.create_with_completion.call_count,
            3)
        data = self.saved.call_args.args[1]
        self.assertIsNone(data['diagnosis'][0].get('plain_0'))
        self.job.refresh_from_db()
        call_results = [e for e in self.job.stage_trace
                        if e.get('kind') == 'call_result'
                        and e.get('table') == 'diagnosis']
        self.assertEqual([e.get('pass') for e in call_results], [1, 2])

    def test_gap_fill_skips_tables_with_no_records(self):
        # A table the document does not mention (0 records) must not
        # trigger a gap-fill re-ask — there is nothing to fill.
        # (The job fails overall: the only root table is empty.)
        from types import SimpleNamespace
        from typing import get_args
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=5))
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            wrapper = kwargs['response_model']
            record_cls = get_args(
                wrapper.model_fields['records'].annotation)[0]
            if set(record_cls.model_fields) == \
                    {'site_0', 'plain_0', 'field_assessments'}:
                return wrapper(records=[]), completion
            return wrapper(records=[{
                'date_pathology': '2024-01-02', 'parent_index': 0}]), \
                completion

        self._setup_client(create)
        result = InstructorExtractionService.stage_extract(self.job, self.source)
        self.assertFalse(result['success'])
        # diagnosis main (0 records) + pathology main — NO gap-fill call
        self.assertEqual(
            self._client.chat.completions.create_with_completion.call_count,
            2)
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status,
                         ExtractionStatusChoices.FAILED)
        self.assertIn('no data', (self.job.extraction_error or '').lower())
        call_results = [e for e in self.job.stage_trace
                        if e.get('kind') == 'call_result'
                        and e.get('table') == 'diagnosis']
        self.assertEqual([e.get('pass') for e in call_results], [1])

    def test_grandchild_nests_under_its_parent_record(self):
        # IHC (child of pathology, grandchild of diagnosis) with one
        # parent record: IHC nests inside the pathology record, which
        # sits inside the diagnosis record.
        self.ihc = make_table('immunohistochemistry', [
            {'field': 'pathology', 'model': 'client_app.pathology',
             'pk_field': 'pk'},
            PATIENT_STEP])
        self.rmt_i = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.ihc)
        f_ihc = make_field(self.ihc, 'protein_name')
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_i, field=f_ihc, order=0)
        self.job.stage_trace = [
            e for e in self.job.stage_trace
            if not (e.get('stage') == 'extraction'
                    and e.get('kind') == 'prompt')]
        entries = InstructorExtractionService.build_extraction_plan_entries(
            self.rm, self.source, self.rm.client, {})
        for entry in entries:
            InstructorExtractionService._append_trace(
                self.job, 'extraction', 'prompt',
                index=entry['index'], table=entry['table'],
                fields=entry['fields'], call_kind=entry['call_kind'],
                ancestry=entry['ancestry'], messages=entry['messages'])
        self.job.save()
        self.entries = [e for e in self.job.stage_trace
                        if e.get('stage') == 'extraction'
                        and e.get('kind') == 'prompt']

        from types import SimpleNamespace
        state = {'i': 0}
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=5))

        def create(**kwargs):
            i = state['i']
            state['i'] += 1
            wrapper = kwargs['response_model']
            table = self.entries[i]['table']
            if table == 'diagnosis':
                return wrapper(records=[{
                    'site_0': 'Left', 'plain_0': 1,
                    'field_assessments': [{
                        'field': 'plain_0', 'basis': 'explicit',
                        'quotes': ['1 node involved.'],
                        'rationale': 'stated'}]}]), completion
            if table == 'pathology':
                return wrapper(records=[{
                    'date_pathology': '2024-01-02',
                    'parent_index': 0}]), completion
            return wrapper(records=[{
                'protein_name': 'Ki-67', 'parent_index': 0}]), completion

        self._client = Mock()
        self._client.chat.completions.create_with_completion.side_effect = \
            create
        self.enterContext(patch.object(InstructorExtractionService,
                                      '_get_llm_client',
                                      return_value=self._client))
        self.enterContext(patch('django.db.transaction.atomic',
                                side_effect=nullcontext))
        coverage = Mock()
        coverage.values.return_value.annotate.return_value = \
            [{'result_state': 'extracted', 'n': 1}]
        self.enterContext(patch.object(ExtractionResult.objects, 'filter',
                                      return_value=coverage))
        self.saved = self.enterContext(patch.object(
            InstructorExtractionService, 'save_extraction_results'))

        result = InstructorExtractionService.stage_extract(self.job, self.source)
        self.assertTrue(result['success'])
        data = self.saved.call_args.args[1]
        p = data['diagnosis'][0]['pathology'][0]
        self.assertEqual(p['immunohistochemistry'][0]['protein_name'],
                         'Ki-67')
        self.assertNotIn('parent_index', p['immunohistochemistry'][0])
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status,
                         ExtractionStatusChoices.COMPLETED)
        final = self.job.stage_trace[-1]
        self.assertEqual(final['dropped_orphans'], 0)

    def test_grandchild_of_failed_table_is_skipped_not_crashing(self):
        # IHC (child of pathology, grandchild of diagnosis): the
        # pathology call fails, so the IHC call must be SKIPPED (not
        # executed, not charged) rather than raising KeyError.
        from types import SimpleNamespace
        self.ihc = make_table('immunohistochemistry', [
            {'field': 'pathology', 'model': 'client_app.pathology',
             'pk_field': 'pk'},
            PATIENT_STEP])
        self.rmt_i = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.ihc)
        f_ihc = make_field(self.ihc, 'protein_name')
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_i, field=f_ihc, order=0)
        self.job.stage_trace = [
            e for e in self.job.stage_trace
            if not (e.get('stage') == 'extraction'
                    and e.get('kind') == 'prompt')]
        entries = InstructorExtractionService.build_extraction_plan_entries(
            self.rm, self.source, self.rm.client, {})
        for entry in entries:
            InstructorExtractionService._append_trace(
                self.job, 'extraction', 'prompt',
                index=entry['index'], table=entry['table'],
                fields=entry['fields'], call_kind=entry['call_kind'],
                ancestry=entry['ancestry'], messages=entry['messages'])
        self.job.save()
        self.entries = [e for e in self.job.stage_trace
                        if e.get('stage') == 'extraction'
                        and e.get('kind') == 'prompt']
        self.assertEqual([e['table'] for e in self.entries],
                         ['diagnosis', 'pathology', 'immunohistochemistry'])

        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=5))
        calls = []

        def create(**kwargs):
            table = self.entries[len(calls)]['table']
            calls.append(kwargs)
            wrapper = kwargs['response_model']
            if table == 'diagnosis':
                return wrapper(records=[{
                    'site_0': 'Left', 'plain_0': 1,
                    'field_assessments': [{
                        'field': 'plain_0', 'basis': 'explicit',
                        'quotes': ['1 node involved.'],
                        'rationale': 'stated'}]}]), completion
            if table == 'pathology':
                raise Exception('provider down')
            raise AssertionError(f'unexpected call for {table}')

        self._client = Mock()
        self._client.chat.completions.create_with_completion.side_effect = \
            create
        self.enterContext(patch.object(InstructorExtractionService,
                                      '_get_llm_client',
                                      return_value=self._client))
        self.enterContext(patch('django.db.transaction.atomic',
                                side_effect=nullcontext))
        coverage = Mock()
        coverage.values.return_value.annotate.return_value = \
            [{'result_state': 'extracted', 'n': 1}]
        self.enterContext(patch.object(ExtractionResult.objects, 'filter',
                                      return_value=coverage))
        self.saved = self.enterContext(patch.object(
            InstructorExtractionService, 'save_extraction_results'))

        result = InstructorExtractionService.stage_extract(self.job, self.source)
        self.assertFalse(result['success'])
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status,
                         ExtractionStatusChoices.PARTIAL)
        self.assertIn('pathology', self.job.extraction_error)
        self.assertIn('skipped: immunohistochemistry',
                      self.job.extraction_error)
        # the IHC call was never executed
        self.assertEqual(
            self._client.chat.completions.create_with_completion.call_count,
            2)
        final = self.job.stage_trace[-1]
        self.assertEqual(final['dropped_orphans'], 0)
        data = self.saved.call_args.args[1]
        self.assertEqual(len(data['diagnosis']), 1)
        self.assertNotIn('pathology', data['diagnosis'][0])
        self.assertNotIn('immunohistochemistry', str(data))


class TableExtractParallelTests(TableExtractTests):
    """Parallel per-table execution (ClientConfiguration.extraction_concurrency):
    independent tables run concurrently, child tables wait for their
    parent, and the trace stays plan-ordered.
    """

    def _table_of(self, kwargs):
        # wrapper models are named '<table>Chunk'
        return kwargs['response_model'].__name__.removesuffix('Chunk')

    def _set_concurrency(self, n):
        self.rm.client.extraction_concurrency = n
        self.rm.client.save()

    def _entry_for_table(self, table):
        return next(e for e in self.entries if e['table'] == table)

    def _add_lesion_root(self):
        # Second independent root table (parent Patient), so two roots
        # can be in flight at the same time
        self.lesion = make_table('lesion', [PATIENT_STEP])
        self.rmt_l = ResponseModelTable.objects.create(
            response_model=self.rm, database_table=self.lesion)
        f_lesion = make_field(self.lesion, 'lesion_size')
        ResponseModelTableField.objects.create(
            response_model_table=self.rmt_l, field=f_lesion, order=0)
        self.job.stage_trace = [
            e for e in self.job.stage_trace
            if not (e.get('stage') == 'extraction'
                    and e.get('kind') == 'prompt')]
        entries = InstructorExtractionService.build_extraction_plan_entries(
            self.rm, self.source, self.rm.client, {})
        for entry in entries:
            InstructorExtractionService._append_trace(
                self.job, 'extraction', 'prompt',
                index=entry['index'], table=entry['table'],
                fields=entry['fields'], call_kind=entry['call_kind'],
                ancestry=entry['ancestry'], messages=entry['messages'])
        self.job.save()
        self.entries = [e for e in self.job.stage_trace
                        if e.get('stage') == 'extraction'
                        and e.get('kind') == 'prompt']

    def test_independent_tables_run_concurrently(self):
        self._add_lesion_root()
        self._set_concurrency(4)
        from types import SimpleNamespace
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=7))
        in_flight = {}
        lock = threading.Lock()
        release = threading.Event()
        overlap_proven = {'both': False}

        def create(**kwargs):
            table = self._table_of(kwargs)
            with lock:
                in_flight[table] = threading.get_ident()
                if set(in_flight) == {'diagnosis', 'lesion'}:
                    overlap_proven['both'] = True
                    release.set()
            release.wait(timeout=10)  # hold both calls open
            with lock:
                in_flight.pop(table, None)
            return self._record_for(kwargs['response_model'],
                                    self._entry_for_table(table)), completion

        self._setup_client(create)
        result = InstructorExtractionService.stage_extract(self.job, self.source)
        self.assertTrue(result['success'])
        self.assertTrue(overlap_proven['both'],
                        'diagnosis and lesion were never in flight together')
        self.assertEqual(
            self._client.chat.completions.create_with_completion.call_count,
            3)
        data = self.saved.call_args.args[1]
        self.assertEqual(data['lesion'][0]['lesion_size'], 'tumor mass')
        self.assertEqual(data['diagnosis'][0]['site_0'], 'Left')
        # traces merge in plan order regardless of completion order
        self.job.refresh_from_db()
        call_results = [e['table'] for e in self.job.stage_trace
                        if e.get('kind') == 'call_result']
        self.assertEqual(call_results,
                         [e['table'] for e in self.entries])

    def test_child_waits_for_parent_records(self):
        # diagnosis (root) + pathology (child): with concurrency > 1 the
        # pathology call must NOT start while diagnosis is in flight —
        # it needs the parent's merged records for its prompt.
        self._set_concurrency(4)
        from types import SimpleNamespace
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=7))
        started = set()
        lock = threading.Lock()

        def create(**kwargs):
            table = self._table_of(kwargs)
            with lock:
                started.add(table)
                if table == 'diagnosis':
                    self.assertNotIn('pathology', started,
                                     'child started before parent finished')
            if table == 'diagnosis':
                # hold the parent call open so a broken gate would let
                # the child start early
                time.sleep(0.3)
                with lock:
                    self.assertNotIn('pathology', started,
                                     'child started before parent finished')
            return self._record_for(kwargs['response_model'],
                                    self._entry_for_table(table)), completion

        self._setup_client(create)
        result = InstructorExtractionService.stage_extract(self.job, self.source)
        self.assertTrue(result['success'])
        self.assertEqual(started, {'diagnosis', 'pathology'})
        data = self.saved.call_args.args[1]
        self.assertEqual(data['diagnosis'][0]['pathology'][0]
                         ['date_pathology'], '2024-01-02')

    def test_failed_parent_skips_child_under_concurrency(self):
        # diagnosis fails with concurrency > 1: pathology is skipped
        # (never executed, never charged) and the job is PARTIAL.
        self._set_concurrency(4)
        from types import SimpleNamespace
        completion = SimpleNamespace(usage=SimpleNamespace(total_tokens=7))
        started = set()
        lock = threading.Lock()

        def create(**kwargs):
            table = self._table_of(kwargs)
            with lock:
                started.add(table)
            if table == 'diagnosis':
                raise Exception('provider down')
            raise AssertionError(f'unexpected call for {table}')

        self._setup_client(create)
        result = InstructorExtractionService.stage_extract(self.job, self.source)
        self.assertFalse(result['success'])
        self.job.refresh_from_db()
        self.assertEqual(self.job.extraction_status,
                         ExtractionStatusChoices.FAILED)
        self.assertIn('diagnosis', self.job.extraction_error)
        self.assertIn('skipped: pathology', self.job.extraction_error)
        self.assertEqual(started, {'diagnosis'})
        self.assertEqual(
            self._client.chat.completions.create_with_completion.call_count,
            1)



class ClientConfigurationDeidValidationTests(TestCase):
    """model_type + deid_local_certified validation on ClientConfiguration."""

    def _make(self, **kw):
        from extractor.models import ClientConfiguration
        defaults = dict(
            llm_model_name='test-model',
            model_provider=kw.pop('provider', 'Local (Ollama)'),
            model_api_key='ollama',
            model_base_url=kw.pop('base_url', 'http://localhost:11434'),
            model_type=kw.pop('model_type', 'system2'),
        )
        defaults.update(kw)
        return ClientConfiguration(**defaults)

    def test_system2_local_certified_clean(self):
        from django.core.exceptions import ValidationError
        c = self._make(model_type='system2', deid_local_certified=True)
        try:
            c.full_clean()
        except ValidationError as e:
            self.fail(f"full_clean raised: {e.message_dict}")

    def test_system2_cloud_provider_rejected(self):
        from django.core.exceptions import ValidationError
        c = self._make(model_type='system2', provider='OpenAI',
                       base_url='https://api.openai.com/v1',
                       deid_local_certified=True)
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_system2_public_url_rejected(self):
        from django.core.exceptions import ValidationError
        # provider not on the cloud list, but URL is public
        c = self._make(model_type='system2', provider='Other',
                       base_url='https://llm.example.com/v1',
                       deid_local_certified=True)
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_system2_not_certified_is_still_valid(self):
        # A System-2 model not certified for local deid is still a valid
        # configuration (it just can't be selected as a pipeline's LLM pass;
        # that restriction is enforced on the pipeline, not the config).
        c = self._make(model_type='system2', deid_local_certified=False)
        c.full_clean()  # no ValidationError

    def test_system2_lan_ip_allowed(self):
        c = self._make(model_type='system2', base_url='http://192.168.1.50:11434',
                       deid_local_certified=True)
        c.full_clean()  # no ValidationError

    def test_system1_remote_allowed(self):
        # A System-1 decision model may use a remote endpoint; no local
        # certification is required.
        c = self._make(model_type='system1', provider='OpenAI',
                       base_url='https://api.openai.com/v1',
                       deid_local_certified=False)
        c.full_clean()  # no ValidationError

    def test_system1_cloud_provider_clean(self):
        c = self._make(model_type='system1', provider='OpenAI',
                       base_url='https://api.openai.com/v1')
        c.full_clean()  # no ValidationError


class ClientConfigurationDeidViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('smoke')
        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=['add_clientconfiguration', 'change_clientconfiguration',
                          'view_clientconfiguration']))

    def test_create_with_model_type(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse('extractor:client_configuration_create'), {
            'llm_model_name': 'gemma4:4b', 'model_provider': 'Local (Ollama)',
            'model_api_key': 'ollama', 'model_base_url': 'http://localhost:11434',
            'request_timeout': '60', 'context_size': '8192',
            'extraction_concurrency': '1',
            'model_type': 'system2', 'deid_local_certified': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        from extractor.models import ClientConfiguration
        cfg = ClientConfiguration.objects.get(llm_model_name='gemma4:4b')
        self.assertEqual(cfg.model_type, 'system2')
        self.assertTrue(cfg.deid_local_certified)

    def test_create_cloud_with_deid_rejected(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse('extractor:client_configuration_create'), {
            'llm_model_name': 'gpt-4', 'model_provider': 'OpenAI',
            'model_api_key': 'sk-x', 'model_base_url': 'https://api.openai.com/v1',
            'request_timeout': '60', 'context_size': '8192',
            'extraction_concurrency': '1',
            'model_type': 'system2', 'deid_local_certified': 'on',
        })
        from extractor.models import ClientConfiguration
        self.assertFalse(ClientConfiguration.objects.filter(
            llm_model_name='gpt-4').exists())
        final = self.client.get(reverse('extractor:client_configuration_create'))
        self.assertTrue(any('cloud provider' in str(m)
                            for m in final.context['messages']))

    def test_edit_round_trip_and_templates_render(self):
        from extractor.models import ClientConfiguration
        cfg = ClientConfiguration.objects.create(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434',
            model_type='system2', deid_local_certified=True)
        self.client.force_login(self.user)
        resp = self.client.post(reverse('extractor:client_configuration_edit', args=[cfg.id]), {
            'llm_model_name': 'gemma4:4b', 'model_provider': 'Local (Ollama)',
            'model_base_url': 'http://localhost:11434',
            'request_timeout': '60', 'context_size': '8192',
            'extraction_concurrency': '1',
            'model_type': 'system1', 'deid_local_certified': 'on',
        })
        cfg.refresh_from_db()
        self.assertEqual(cfg.model_type, 'system1')
        # templates render
        self.client.get(reverse('extractor:client_configuration_list'))
        self.assertContains(
            self.client.get(reverse('extractor:client_configuration_detail', args=[cfg.id])),
            'Text Deidentification')
        self.assertContains(
            self.client.get(reverse('extractor:client_configuration_edit', args=[cfg.id])),
            'deid_local_certified')
        self.assertContains(
            self.client.get(reverse('extractor:client_configuration_create')),
            'model_type')


class ClientConfigurationSystem1CapabilityTests(TestCase):
    """Connection test + capabilities for a System-1 decision model must hit
    the /v1/systemone judge endpoint, not the OpenAI chat path."""

    def setUp(self):
        from extractor.models import ClientConfiguration
        self.user = User.objects.create_user('s1cap')
        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=['view_clientconfiguration',
                          'change_clientconfiguration']))
        self.cfg = ClientConfiguration.objects.create(
            llm_model_name='nimble', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434/v1',
            model_type='system1')

    def test_system1_connection_uses_systemone(self):
        import extractor.services.system1_judge as sj
        self.client.force_login(self.user)
        with mock.patch.object(sj, 'judge_span', return_value=0.42) as m:
            r = self.client.post(
                reverse('extractor:client_configuration_test_connection',
                        args=[self.cfg.id]), {},
                content_type='application/json')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['success'])
        self.assertIn('System-1', data['message'])
        self.assertEqual(data['details']['is_phi_probability'], 0.42)
        m.assert_called_once()

    def test_system1_discovery_returns_decision_profile(self):
        import extractor.services.system1_judge as sj
        self.client.force_login(self.user)
        with mock.patch.object(sj, 'judge_span', return_value=0.1):
            r = self.client.post(
                reverse('extractor:client_configuration_discover_capabilities',
                        args=[self.cfg.id]), {},
                content_type='application/json')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['capabilities']['model_details']['family'],
                         'decision-model')
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.model_capabilities['model_details']['family'],
                         'decision-model')


from extractor.services import llm_ner


class ChunkTextTests(SimpleTestCase):
    def test_short_text_single_chunk(self):
        chunks = list(llm_ner.chunk_text('hello world'))
        self.assertEqual(chunks, [(0, 'hello world')])

    def test_empty_text(self):
        self.assertEqual(list(llm_ner.chunk_text('')), [])

    def test_full_coverage_no_gaps(self):
        text = 'Para one.\n\n' * 50 + '\n\n'.join(
            f'Sentence {i} of paragraph two, with details.' for i in range(100))
        chunks = list(llm_ner.chunk_text(text, max_chars=500, overlap=50))
        covered = set()
        for offset, chunk in chunks:
            covered.update(range(offset, offset + len(chunk)))
        self.assertEqual(covered, set(range(len(text))))

    def test_chunks_respect_max_chars(self):
        text = 'word ' * 5000
        for offset, chunk in llm_ner.chunk_text(text, max_chars=1000, overlap=100):
            self.assertLessEqual(len(chunk), 1000)

    def test_progress_guaranteed_on_no_boundaries(self):
        text = 'x' * 5000
        chunks = list(llm_ner.chunk_text(text, max_chars=1000, overlap=100))
        self.assertGreater(len(chunks), 1)
        starts = [o for o, _ in chunks]
        self.assertTrue(all(b > a for a, b in zip(starts, starts[1:])))


class ResolveSpansTests(SimpleTestCase):
    def test_exact_single_span(self):
        src = 'Patient Sharma Rao visited on 01/02/2024.'
        out = llm_ner.resolve_spans(src, [('PERSON', 'Sharma Rao')])
        self.assertEqual(len(out), 1)
        self.assertEqual(src[out[0]['start']:out[0]['end']], 'Sharma Rao')
        self.assertEqual(out[0]['type'], 'PERSON')

    def test_duplicate_spans_consumed_in_order(self):
        src = 'Dr Rao examined Rao and Rao again.'
        out = llm_ner.resolve_spans(src, [('PERSON', 'Rao')] * 3)
        spans = [src[e['start']:e['end']] for e in out]
        self.assertEqual(spans, ['Rao', 'Rao', 'Rao'])
        starts = [e['start'] for e in out]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(all(b > a for a, b in zip(starts, starts[1:])))

    def test_whitespace_normalized_span(self):
        src = 'Admitted: Sharma\nRao, 56 y.'
        out = llm_ner.resolve_spans(src, [('PERSON', 'Sharma Rao')])
        self.assertEqual(len(out), 1)
        self.assertEqual(src[out[0]['start']:out[0]['end']], 'Sharma\nRao')

    def test_case_fallback(self):
        src = 'referred by Dr SHARMA.'
        out = llm_ner.resolve_spans(src, [('PERSON', 'Sharma')])
        self.assertEqual(len(out), 1)
        self.assertEqual(src[out[0]['start']:out[0]['end']], 'SHARMA')

    def test_unlocatable_span_dropped(self):
        out = llm_ner.resolve_spans('hello world', [('PERSON', 'Ghost Name')])
        self.assertEqual(out, [])

    def test_blank_span_ignored(self):
        self.assertEqual(llm_ner.resolve_spans('abc', [('PERSON', '   ')]), [])

    def test_same_span_two_types_kept_once_per_type(self):
        src = 'MR/24/012817 issued.'
        out = llm_ner.resolve_spans(
            src, [('MEDICAL_RECORD_NUMBER', 'MR/24/012817'),
                  ('PERSON', 'MR')])
        types = sorted(e['type'] for e in out)
        self.assertEqual(types, ['MEDICAL_RECORD_NUMBER', 'PERSON'])


class LlmNerClientTests(TestCase):
    def _config(self, **kw):
        from extractor.models import ClientConfiguration
        defaults = dict(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434')
        defaults.update(kw)
        return ClientConfiguration.objects.create(**defaults)

    def test_entity_types_mapped_and_offsets_found(self):
        from extractor.services import llm_ner
        cfg = self._config()
        client = llm_ner.LlmNerClient(cfg)
        text = 'Patient Sharma Rao admitted on 01/02/2024 to AIIMS.'
        with mock.patch.object(
                llm_ner.LlmNerClient, '_llm_call',
                return_value=[('person', 'Sharma Rao'), ('date', '01/02/2024'),
                              ('organization', 'AIIMS'), ('junk_type', 'AIIMS')]):
            results = client.find_entities_in_text(text)
        got = {(r['type'], text[r['start']:r['end']]) for r in results}
        self.assertIn(('PERSON', 'Sharma Rao'), got)
        self.assertIn(('DATE_TIME', '01/02/2024'), got)
        self.assertIn(('ORGANIZATION', 'AIIMS'), got)
        self.assertEqual(len(results), 3)  # unknown type dropped

    def test_chunked_text_global_offsets_and_overlap_dedupe(self):
        from extractor.services import llm_ner
        cfg = self._config()
        client = llm_ner.LlmNerClient(cfg)
        filler = 'Normal clinical sentence number. ' * 200  # ~5.8k chars
        text = filler + 'Sharma Rao' + filler
        with mock.patch.object(
                llm_ner.LlmNerClient, '_llm_call',
                side_effect=lambda chunk: (
                    [('person', 'Sharma Rao')]
                    if 'Sharma Rao' in chunk else [])):
            results = client.find_entities_in_text(text)
        self.assertEqual(len(results), 1)  # overlap double-hit deduped
        self.assertEqual(results[0]['type'], 'PERSON')
        self.assertEqual(text[results[0]['start']:results[0]['end']], 'Sharma Rao')

    def test_llm_failure_raises(self):
        from extractor.services import llm_ner
        cfg = self._config()
        client = llm_ner.LlmNerClient(cfg)
        with mock.patch.object(
                llm_ner.LlmNerClient, '_llm_call',
                side_effect=RuntimeError('connection refused')):
            with self.assertRaises(llm_ner.LlmNerError):
                client.find_entities_in_text('some text')


class LlmNerRecognizerTests(TestCase):
    def test_cache_serves_repeated_text_without_second_call(self):
        from extractor.models import ClientConfiguration
        from extractor.services import llm_ner
        cfg = ClientConfiguration.objects.create(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434')
        rec = llm_ner.LlmNerRecognizer(cfg)
        with mock.patch.object(
                llm_ner.LlmNerClient, 'find_entities_in_text',
                return_value=[{'type': 'PERSON', 'start': 0, 'end': 5,
                               'score': llm_ner.LLM_NER_SCORE}]) as m:
            first = rec.analyze('Rao K.', language='en')
            second = rec.analyze('Rao K.', language='en')
        self.assertEqual(m.call_count, 1)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].entity_type, 'PERSON')
        self.assertEqual((first[0].start, first[0].end), (0, 5))
        self.assertEqual(len(second), 1)


class DeidPipelineResolutionTests(TestCase):
    def _cfg(self, **kw):
        from extractor.models import ClientConfiguration
        defaults = dict(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434',
            model_type='system2', deid_local_certified=True)
        defaults.update(kw)
        return ClientConfiguration.objects.create(**defaults)

    def test_default_resolves_to_default_pipeline(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        from extractor.models import TextDeidentificationPipelineConfig as P
        pipeline, openmed = S._resolve_pipeline(None, 'default', None)
        self.assertIsNone(openmed)
        self.assertTrue(P.objects.filter(id=pipeline.id, is_default=True).exists())

    def test_presidio_backend_builds_hf_pipeline(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        from django.conf import settings
        pipeline, openmed = S._resolve_pipeline(None, 'presidio', None)
        self.assertIsNone(openmed)
        self.assertEqual(pipeline.ner_engine, 'hf')
        self.assertEqual(pipeline.hf_model_id, settings.DEID_HF_NER_MODEL)

    def test_llm_backend_uses_config(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        cfg = self._cfg()
        pipeline, openmed = S._resolve_pipeline(None, 'llm', cfg.id)
        self.assertIsNone(openmed)
        self.assertEqual(pipeline.system2_model_id, cfg.id)
        self.assertEqual(pipeline.ner_engine, 'spacy')

    def test_explicit_llm_without_config_raises(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S, LlmDeidConfigurationError)
        with self.assertRaises(LlmDeidConfigurationError):
            S._resolve_pipeline(None, 'llm', None)

    def test_openmed_backend(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        pipeline, openmed = S._resolve_pipeline(None, 'openmed', None)
        self.assertIsNone(pipeline)
        self.assertEqual(openmed, 'openmed')

    def test_pipeline_wins_over_backend(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        from extractor.models import TextDeidentificationPipelineConfig as P
        p = P.objects.filter(is_default=True).first()
        got, openmed = S._resolve_pipeline(p, 'presidio', None)
        self.assertIsNone(openmed)
        self.assertEqual(got.id, p.id)

    def test_unknown_backend_raises(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S, LlmDeidConfigurationError)
        with self.assertRaises(LlmDeidConfigurationError):
            S._resolve_pipeline(None, 'magic', None)


class DurationFilterTests(SimpleTestCase):
    def _kept(self, text, etype, surface=None):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)

        class R:
            def __init__(self):
                self.entity_type = etype
                s = surface if surface is not None else text
                self.start = text.find(s)
                self.end = self.start + len(s)
                self.score = 0.9
        r = R()
        return len(S._filter_results(text, [r])) == 1

    def test_bare_duration_months_dropped(self):
        self.assertFalse(self._kept('follow up after 1 month', 'DATE_TIME', '1 month'))

    def test_bare_duration_weeks_days_dropped(self):
        self.assertFalse(self._kept('take for 2 weeks', 'DATE_TIME', '2 weeks'))
        self.assertFalse(self._kept('waited 3 days', 'DATE_TIME', '3 days'))

    def test_real_date_kept(self):
        self.assertTrue(self._kept('admitted on 01/02/2024', 'DATE_TIME', '01/02/2024'))

    def test_age_surfaces_still_dropped(self):
        self.assertFalse(self._kept('age 56 years', 'DATE_TIME', '56 years'))
        self.assertFalse(self._kept('a 56-year-old man', 'DATE_TIME', '56-year-old'))

    def test_age_with_leading_word_dropped(self):
        # spaCy tags the whole 'Age 56 years' as one DATE span
        self.assertFalse(
            self._kept('Age 56 years, Sex: Male', 'DATE_TIME', 'Age 56 years'))

    def test_bare_age_expressions_dropped(self):
        self.assertFalse(self._kept('DOB 12/04/1968, age: 56', 'DATE_TIME', 'age: 56'))
        self.assertFalse(self._kept('admitted at age 56', 'DATE_TIME', 'age 56'))
        self.assertFalse(self._kept('he is 56 years old', 'DATE_TIME', '56 years old'))

    def test_range_duration_dropped(self):
        self.assertFalse(self._kept('orthopnoea since 3-4 days', 'DATE_TIME', '3-4 days'))

    def test_mnth_abbrev_duration_dropped(self):
        self.assertFalse(self._kept('swelling since 1 mnth', 'DATE_TIME', '1 mnth'))
        self.assertFalse(self._kept('wt loss in 2 mnths', 'DATE_TIME', '2 mnths'))

    def test_age_sex_formats_dropped(self):
        # age/sex (61/F, F/46, 91 y/M) are not PII
        self.assertFalse(self._kept('Smt X 61/F W/o Y', 'DATE_TIME', '61/F'))
        self.assertFalse(self._kept('Smt X F/46', 'DATE_TIME', 'F/46'))
        self.assertFalse(self._kept('Mr X 91 y/M', 'DATE_TIME', '91 y/M'))

    def test_clinical_person_prefix_dropped(self):
        # lab/drug/vital lines mis-tagged as person by NER
        self.assertFalse(self._kept('Pre-op: Hb 9.8, creat 1.4', 'PERSON', 'Hb 9.8'))
        self.assertFalse(self._kept('Tab Tramadol 50 mg BD', 'PERSON', 'Tab Tramadol'))
        self.assertFalse(self._kept('SpO2 94% RA', 'PERSON', 'SpO2'))
        self.assertFalse(self._kept('Inj Lasix 40mg IV', 'PERSON', 'Inj Lasix'))

    def test_real_person_prefix_still_kept(self):
        # a genuine name is not dropped by the clinical-prefix guard
        self.assertTrue(self._kept('Dr. Taboo Singh', 'PERSON', 'Taboo Singh'))

    def test_pulses_and_times_dropped(self):
        self.assertFalse(self._kept('pulse 82/min', 'DATE_TIME', '82/min'))
        self.assertFalse(self._kept('receipt at 07:45 on 02/02/2024',
                                    'DATE_TIME', '07:45'))

    def test_drug_dose_span_dropped(self):
        self.assertFalse(self._kept('IV ceftriaxone 1 g 12 hourly',
                                    'DATE_TIME', 'ceftriaxone 1'))
        self.assertFalse(self._kept('Tab paracetamol 650 mg OD',
                                    'DATE_TIME', 'paracetamol 650 mg'))

    def test_fraction_counter_dropped_real_date_kept(self):
        self.assertFalse(self._kept('Fraction 10/25 completed',
                                    'DATE_TIME', '10/25'))
        self.assertTrue(self._kept('admitted on 10/25', 'DATE_TIME', '10/25'))


class AgeDurationRegressionTests(SimpleTestCase):
    """End-to-end: age and duration survive deid, real dates shift.

    Regression guard for the A/B finding that 'Age 56 years' (a single
    spaCy DATE span) was redacted as <DATE> on both engines while
    clinical intervals ('1 month', '2 weeks') must remain.
    """

    def test_age_and_durations_survive_dates_shift(self):
        from unittest import mock
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)

        class FakeResult:
            def __init__(self, etype, start, end, score=0.9):
                self.entity_type = etype
                self.start = start
                self.end = end
                self.score = score

        text = ('Age 56 years, symptomatic for 1 month with fever 3 days. '
                'Admitted 01/02/2024, follow up in 2 weeks.')
        spans = [
            ('DATE_TIME', 'Age 56 years'),
            ('DATE_TIME', '1 month'),
            ('DATE_TIME', '3 days'),
            ('DATE_TIME', '01/02/2024'),
            ('DATE_TIME', '2 weeks'),
        ]
        results = [
            FakeResult(et, text.find(s), text.find(s) + len(s))
            for et, s in spans
        ]
        kept = S._filter_results(text, results)
        kept_surfaces = {text[r.start:r.end] for r in kept}
        self.assertEqual(kept_surfaces, {'01/02/2024'})


class ClinicalAllowlistTests(SimpleTestCase):
    """Clinical terms mis-tagged by general-domain NER survive on
    every engine (whole-span, case-insensitive match)."""

    def _kept(self, text, etype, surface):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)

        class R:
            def __init__(self):
                self.entity_type = etype
                self.start = text.find(surface)
                self.end = self.start + len(surface)
                self.score = 0.95
        return len(S._filter_results(text, [R()])) == 1

    def test_nottingham_survives_as_location(self):
        self.assertFalse(self._kept(
            'Grade III (Nottingham 8/9)', 'LOCATION', 'Nottingham'))

    def test_grade_survives_as_person(self):
        self.assertFalse(self._kept(
            'ductal carcinoma, Grade III', 'PERSON', 'Grade III'))

    def test_mammogram_survives_as_date(self):
        self.assertFalse(self._kept(
            'follow up with mammogram', 'DATE_TIME', 'mammogram'))

    def test_real_place_still_redacted(self):
        self.assertTrue(self._kept(
            'from Kolkata to Patia', 'LOCATION', 'Kolkata'))


class FilterDecompositionTests(SimpleTestCase):
    """_filter_results is decomposed into mechanical + dates + clinical.

    Equivalence with the original monolith is proven by the pre-existing
    DurationFilterTests / AgeDurationRegressionTests / ClinicalAllowlistTests
    continuing to pass unchanged. These tests pin each sub-filter's job.
    """

    def _mk(self, etype, start, end):
        class R:
            def __init__(self):
                self.entity_type = etype
                self.start = start
                self.end = end
                self.score = 0.9
        return R()

    def test_mechanical_drops_drop_type_and_midword(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        text = "oropharynx"
        idr = self._mk('ID', 0, 2)        # in drop_types
        mid = self._mk('PERSON', 3, 6)    # 'oph' mid-word
        ok = self._mk('PERSON', 0, 10)    # whole token, kept
        kept = S._filter_mechanical(text, [idr, mid, ok])
        self.assertEqual([r.entity_type for r in kept], ['PERSON'])

    def test_dates_drops_duration_keeps_real_date(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        text = "for 1 month admitted 01/02/2024"
        dur = self._mk('DATE_TIME', text.find('1 month'), text.find('1 month') + 7)
        real = self._mk('DATE_TIME', text.find('01/02/2024'), text.find('01/02/2024') + 10)
        kept = S._filter_dates(text, [dur, real])
        self.assertEqual([text[r.start:r.end] for r in kept], ['01/02/2024'])

    def test_clinical_drops_lab_keeps_name(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        text = "Hb 9.8 seen Taboo Singh"
        lab = self._mk('PERSON', 0, 6)    # 'Hb 9.8' clinical prefix
        name = self._mk('PERSON', text.find('Taboo Singh'), text.find('Taboo Singh') + 11)
        kept = S._filter_clinical(text, [lab, name])
        self.assertEqual([text[r.start:r.end] for r in kept], ['Taboo Singh'])


class OpenMedNerRecognizerTests(SimpleTestCase):
    def test_labels_mapped_offsets_preserved(self):
        from extractor.services.openmed_ner import OpenMedNerRecognizer

        rec = OpenMedNerRecognizer(threshold=0.5)
        text = 'Rajesh Kumar from Patia on 01/02/2024'
        rec._extract = mock.Mock(return_value=[
            ('first_name', 0.99, 0, 6),
            ('last_name', 0.99, 7, 12),
            ('city', 0.8, 17, 22),
            ('date', 0.95, 27, 37),
            # unmapped clinical label must be dropped
            ('medical_condition', 0.9, 17, 22),
            # below-threshold mapped label must be dropped
            ('postcode', 0.4, 0, 6),
        ])
        found = rec._find(text)
        self.assertEqual(
            found,
            [('PERSON', 0.99, 0, 6), ('PERSON', 0.99, 7, 12),
             ('LOCATION', 0.8, 17, 22), ('DATE_TIME', 0.95, 27, 37)])

    def test_age_label_maps_to_age(self):
        from extractor.services.openmed_ner import OpenMedNerRecognizer
        rec = OpenMedNerRecognizer(threshold=0.5)
        rec._extract = mock.Mock(return_value=[('age', 0.99, 0, 2)])
        self.assertEqual(rec._find('56'), [('AGE', 0.99, 0, 2)])

    def test_analyze_caches_per_text(self):
        from extractor.services.openmed_ner import OpenMedNerRecognizer
        rec = OpenMedNerRecognizer(threshold=0.5)
        rec._extract = mock.Mock(return_value=[('name', 0.9, 0, 3)])
        rec.analyze('abc', entities=None, nlp_artifacts=None)
        rec.analyze('abc', entities=None, nlp_artifacts=None)
        self.assertEqual(rec._extract.call_count, 1)

    def test_openmed_error_wrapped(self):
        from extractor.services.openmed_ner import (
            OpenMedNerError, OpenMedNerRecognizer)
        rec = OpenMedNerRecognizer(threshold=0.5)
        rec._extract = mock.Mock(side_effect=RuntimeError('boom'))
        with self.assertRaises(OpenMedNerError):
            rec._find('abc')


class DeidDispatchViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        from extractor.models import FileUpload, ProcessedText
        self.user = User.objects.create_user('deid_tester')
        self.user.user_permissions.set(
            Permission.objects.filter(
                codename__in=['view_processedtext', 'change_processedtext',
                              'view_fileupload']))
        self.upload = FileUpload.objects.create(original_filename='a.pdf')
        self.pt = ProcessedText.objects.create(
            file_upload=self.upload, processed_file_path='x.txt',
            content_length=3)
        self.path = reverse('extractor:processed_text_deidentify',
                            args=[self.pt.id])

    def _post(self, **extra):
        return self.client.post(self.path, {'next': '/', **extra})

    @mock.patch('extractor.tasks.deidentify_processed_text_task.delay')
    def test_default_dispatch(self, delay):
        self.client.force_login(self.user)
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(delay.call_count, 1)
        args, kwargs = delay.call_args
        self.assertEqual(kwargs['backend'], 'default')
        self.assertIsNone(kwargs['client_config_id'])

    @mock.patch('extractor.tasks.deidentify_processed_text_task.delay')
    def test_llm_dispatch_with_encoded_option(self, delay):
        from extractor.models import ClientConfiguration
        cfg = ClientConfiguration.objects.create(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434',
            model_type='system2', deid_local_certified=True)
        self.client.force_login(self.user)
        resp = self._post(**{'backend': f'llm:{cfg.id}'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(delay.call_count, 1)
        args, kwargs = delay.call_args
        self.assertEqual(kwargs['backend'], 'llm')
        self.assertEqual(kwargs['client_config_id'], cfg.id)

    @mock.patch('extractor.tasks.deidentify_processed_text_task.delay')
    def test_llm_dispatch_bad_config_no_task(self, delay):
        self.client.force_login(self.user)
        resp = self._post(**{'backend': 'llm'})
        self.assertEqual(delay.call_count, 0)
        final = self.client.get('/')
        self.assertTrue(any('llm' in str(m).lower()
                            or 'configuration' in str(m).lower()
                            for m in final.context['messages']))

    def test_permission_required(self):
        anon = User.objects.create_user('noperm')
        self.client.force_login(anon)
        resp = self._post()
        self.assertEqual(resp.status_code, 403)


class FileUploadDetailDeidRenderTests(TestCase):
    def test_file_detail_engine_selector(self):
        u = User.objects.create_user('r1')
        u.user_permissions.set(Permission.objects.filter(
            codename__in=['view_fileupload', 'view_processedtext',
                          'change_processedtext']))
        cfg = ClientConfiguration.objects.create(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434',
            model_type='system2', deid_local_certified=True)
        up = FileUpload.objects.create(original_filename='a.pdf',
                                      file=ContentFile(b'%PDF-1.4 fake', 'a.pdf'))
        ProcessedText.objects.create(file_upload=up, processed_file_path='x.txt')
        self.client.force_login(u)
        resp = self.client.get(reverse('extractor:file_upload_detail', args=[up.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Legacy: LLM NER — gemma4:4b')
        self.assertContains(resp, 'Default pipeline')
        self.assertContains(resp, 'Legacy: Presidio + Stanford NER')

    def test_file_detail_no_llm_config_hidden_select(self):
        u = User.objects.create_user('r2')
        u.user_permissions.set(Permission.objects.filter(
            codename__in=['view_fileupload', 'view_processedtext',
                          'change_processedtext']))
        up = FileUpload.objects.create(original_filename='b.pdf',
                                      file=ContentFile(b'%PDF-1.4 fake', 'b.pdf'))
        ProcessedText.objects.create(file_upload=up, processed_file_path='y.txt')
        self.client.force_login(u)
        resp = self.client.get(reverse('extractor:file_upload_detail', args=[up.id]))
        self.assertEqual(resp.status_code, 200)
        # the pipeline selector always renders (at least the default)
        self.assertContains(resp, 'name="backend"')
        self.assertContains(resp, 'Default pipeline')


class LlmDeidEndToEndTests(TestCase):
    """Full deidentify() run on the LLM engine with the model mocked.

    Verifies: engine/model/config recorded, Indian names redacted by the
    LLM, dates shifted (not replaced with <DATE> when parseable), rule
    recognizers still active (Aadhaar caught without the LLM naming it),
    durations NOT redacted, and the review map populated.
    """

    def setUp(self):
        from pathlib import Path
        from django.conf import settings
        from extractor.models import (
            ClientConfiguration, FileUpload, ProcessedText)
        self.media = Path(settings.MEDIA_ROOT)
        self.cfg = ClientConfiguration.objects.create(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434',
            model_type='system2', deid_local_certified=True)
        self.upload = FileUpload.objects.create(original_filename='note.pdf')
        self.content = (
            'Mr Rajesh Kumar from Village Patia, Kolkata, was admitted on '
            '01/02/2024. Aadhaar 123412341234. He had symptoms for 1 month '
            'before presentation. Follow up advised in 2 weeks.')
        self.pt = self._write_processed('uploads/test_note.txt', self.content)

    def _write_processed(self, rel_path, content):
        from pathlib import Path
        from django.conf import settings
        from extractor.models import ProcessedText
        pt = ProcessedText.objects.create(
            file_upload=self.upload, processed_file_path=rel_path,
            content_length=len(content))
        path = Path(settings.MEDIA_ROOT) / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return pt

    def _llm_side_effect(self, chunk):
        # The model "finds" the Indian names (which the gazetteer/NER may
        # miss) but nothing else — rules cover Aadhaar + dates.
        found = []
        for name in ('Rajesh Kumar', 'Patia'):
            if name in chunk:
                found.append(('person', name))
        if 'Kolkata' in chunk:
            found.append(('location', 'Kolkata'))
        return found

    def test_llm_deidentify_text(self):
        from pathlib import Path
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        with mock.patch('extractor.services.llm_ner.LlmNerClient._llm_call',
                        side_effect=lambda chunk:
                        self._llm_side_effect(chunk)):
            new = S.deidentify(self.pt, backend='llm',
                               client_config_id=self.cfg.id)
        self.assertIsNotNone(new)
        self.assertEqual(new.deid_engine, 'spacy')
        self.assertEqual(new.deid_model, 'gemma4:4b')
        self.assertEqual(new.deid_client_config_id, self.cfg.id)
        out = (self.media / new.processed_file_path).read_text(encoding='utf-8')
        # LLM-found entities redacted
        self.assertNotIn('Rajesh Kumar', out)
        self.assertNotIn('Patia', out)
        self.assertNotIn('Kolkata', out)
        self.assertRegex(out, r'<PERSON_\d+>')
        # Rule recognizer still covers the Aadhaar digits without LLM
        # help. (The digits may be subsumed into a wider spaCy PERSON
        # span by the intentional containment rule in _resolve_overlaps —
        # either way the digits must not survive.)
        self.assertNotIn('123412341234', out)
        # Duration NOT redacted — the persistent false positive
        self.assertIn('1 month', out)
        self.assertIn('2 weeks', out)
        # Real date shifted by the recorded offset (or unchanged when the
        # random offset happened to be 0)
        from datetime import timedelta
        from dateutil.parser import parse as parse_date
        shift = new.deid_date_shift_days
        self.assertIsNotNone(shift)
        if shift != 0:
            self.assertNotIn('01/02/2024', out)
            shifted = (parse_date('01/02/2024', dayfirst=True)
                       + timedelta(days=shift)).strftime('%d/%m/%Y')
            self.assertIn(shifted, out)
        # Review map populated
        self.assertTrue(new.deid_map)

    def test_default_resolution_picks_default_pipeline(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        with mock.patch('extractor.services.llm_ner.LlmNerClient._llm_call',
                        side_effect=lambda chunk:
                        self._llm_side_effect(chunk)):
            new = S.deidentify(self.pt)  # default backend -> default pipeline
        self.assertEqual(new.deid_engine, 'spacy')
        self.assertIsNone(new.deid_client_config_id)

    def test_presidio_engine_unaffected(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        new = S.deidentify(self.pt, backend='presidio')
        self.assertEqual(new.deid_engine, 'hf')
        self.assertIsNone(new.deid_client_config_id)
        out = (self.media / new.processed_file_path).read_text(encoding='utf-8')
        self.assertNotIn('123412341234', out)  # rules still work

    def test_llm_csv_cell_caching(self):
        """Identical unmapped cell values cost ONE LLM call per run.

        Layout trick: 'dob' IS in EXTRACTOR_DEID_CSV_COLUMN_MAP so the CSV
        goes through the header-aware path (fully unmapped CSVs fall back
        to whole-text deid), while 'subject' cells go through per-cell NER
        where the recognizer's run-cache must absorb the repeats.
        """
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        csv_content = (
            'dob,subject\n'
            '01/02/2024,Rajesh Kumar\n'
            '02/02/2024,Rajesh Kumar\n'
            '03/02/2024,Rajesh Kumar\n')
        pt2 = self._write_processed('uploads/test_note.csv', csv_content)
        with mock.patch(
                'extractor.services.llm_ner.LlmNerClient._llm_call',
                wraps=lambda chunk: self._llm_side_effect(chunk)) as m:
            new = S.deidentify(pt2, backend='llm', client_config_id=self.cfg.id)
        calls_for_name = sum(
            1 for c in m.call_args_list if 'Rajesh Kumar' in c.args[0])
        out = (self.media / new.processed_file_path).read_text(encoding='utf-8')
        self.assertNotIn('Rajesh Kumar', out)
        self.assertEqual(calls_for_name, 1)


class LlmNerParseTests(SimpleTestCase):
    def test_plain_array(self):
        from extractor.services.llm_ner import _parse_entity_output
        out = _parse_entity_output(
            '[{"type": "person", "text": "Rao K"}, '
            '{"type": "date", "text": "01/02/2024"}]')
        self.assertEqual(out, [('person', 'Rao K'), ('date', '01/02/2024')])

    def test_single_object(self):
        from extractor.services.llm_ner import _parse_entity_output
        out = _parse_entity_output('{"type": "person", "text": "Rao K"}')
        self.assertEqual(out, [('person', 'Rao K')])

    def test_entities_wrapper_object(self):
        from extractor.services.llm_ner import _parse_entity_output
        out = _parse_entity_output(
            '{"entities": [{"type": "person", "text": "Rao K"}]}')
        self.assertEqual(out, [('person', 'Rao K')])

    def test_code_fences_and_prose(self):
        from extractor.services.llm_ner import _parse_entity_output
        out = _parse_entity_output(
            'Here are the findings:\n```json\n'
            '[{"type": "person", "text": "Rao K"}]\n```\nDone.')
        self.assertEqual(out, [('person', 'Rao K')])

    def test_empty_array(self):
        from extractor.services.llm_ner import _parse_entity_output
        self.assertEqual(_parse_entity_output('[]'), [])

    def test_garbage_raises(self):
        from extractor.services.llm_ner import (
            LlmNerParseError, _parse_entity_output)
        with self.assertRaises(LlmNerParseError):
            _parse_entity_output('no identifiable information found')
        with self.assertRaises(LlmNerParseError):
            _parse_entity_output('')

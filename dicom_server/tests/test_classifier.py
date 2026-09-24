from django.test import TestCase

from client_app.models import Patient, DICOMStudy, SiteConfiguration, StudyTypeRule, StudyTypeChoices, StudyTypeSource
from dicom_server.services.classifier import classify_study


class ClassifierTests(TestCase):
    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='TEST', center_name='Test')
        self.patient = Patient.objects.create(patient_id='P001', chavi_consent=True)
        self.study = DICOMStudy.objects.create(
            patient=self.patient,
            study_instance_uid='1.2.3',
            study_description='CT SIM',
            study_modalities='CT',
        )
        StudyTypeRule.objects.create(
            study_type=StudyTypeChoices.PLANNING_IMAGE,
            priority=10,
            match_study_description='SIM',
        )

    def test_keyword_rule_classifies(self):
        classify_study(self.study)
        self.study.refresh_from_db()
        self.assertEqual(self.study.study_type, StudyTypeChoices.PLANNING_IMAGE)
        self.assertEqual(self.study.study_type_source, StudyTypeSource.AUTO)

    def test_manual_override_preserved(self):
        self.study.study_type = StudyTypeChoices.OTHER
        self.study.study_type_source = StudyTypeSource.MANUAL
        self.study.save()
        classify_study(self.study)
        self.study.refresh_from_db()
        self.assertEqual(self.study.study_type, StudyTypeChoices.OTHER)
        self.assertEqual(self.study.study_type_source, StudyTypeSource.MANUAL)

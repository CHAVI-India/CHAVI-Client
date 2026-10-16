from django.test import TestCase
from client_app.models import Patient, SiteConfiguration
from dicom_server.models import (
    RetrievalJob, RetrievalJobStudy, RetrievalJobSeries, RemoteDICOMNode,
)


class RetrievalJobStudyTests(TestCase):
    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='T', center_name='T')
        self.patient = Patient.objects.create(patient_id='P1', gender='Male')
        self.node = RemoteDICOMNode.objects.create(
            name='n', ae_title='TEST', host='127.0.0.1',
        )

    def test_create_study_and_series(self):
        job = RetrievalJob.objects.create(
            node=self.node, patient=self.patient,
        )
        study = RetrievalJobStudy.objects.create(
            job=job, study_instance_uid='1.2.3',
            remote_patient_id='REMOTE1',
            study_date=None, study_description='CT Head',
            modalities='CT',
        )
        series = RetrievalJobSeries.objects.create(
            study=study, series_instance_uid='4.5.6',
            series_description='Series 1', modality='CT',
        )
        self.assertEqual(job.studies.count(), 1)
        self.assertEqual(study.series.count(), 1)
        self.assertEqual(study.job.patient, self.patient)

    def test_unique_constraint(self):
        from django.db import IntegrityError
        from django.db.transaction import atomic
        job = RetrievalJob.objects.create(node=self.node, patient=self.patient)
        RetrievalJobStudy.objects.create(job=job, study_instance_uid='1.2.3')
        with self.assertRaises(IntegrityError):
            with atomic():
                RetrievalJobStudy.objects.create(job=job, study_instance_uid='1.2.3')

    def test_query_by_study_uid_and_running_status(self):
        """This is the query ingest_dataset will use."""
        job = RetrievalJob.objects.create(
            node=self.node, patient=self.patient, status=RetrievalJob.Status.RUNNING,
        )
        RetrievalJobStudy.objects.create(
            job=job, study_instance_uid='9.9.9',
        )
        result = RetrievalJobStudy.objects.filter(
            study_instance_uid='9.9.9',
            job__status=RetrievalJob.Status.RUNNING,
        ).select_related('job__patient').first()
        self.assertIsNotNone(result)
        self.assertEqual(result.job.patient, self.patient)

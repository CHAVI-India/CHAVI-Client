from django.core.management.base import BaseCommand
from client_app.models import Patient
from dicom_server.services.classifier import classify_all_studies, classify_patient_studies


class Command(BaseCommand):
    help = 'Re-apply StudyTypeRule classification to DICOMStudy rows'

    def add_arguments(self, parser):
        parser.add_argument('--patient-id', type=str, help='Only classify studies for this patient')

    def handle(self, *args, **options):
        patient_id = options.get('patient_id')
        if patient_id:
            patient = Patient.objects.get(patient_id=patient_id)
            classify_patient_studies(patient)
            self.stdout.write(self.style.SUCCESS(f'Classified studies for {patient_id}'))
        else:
            classify_all_studies()
            self.stdout.write(self.style.SUCCESS('Classified all studies'))

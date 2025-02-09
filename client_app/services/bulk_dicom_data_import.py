from django.contrib import messages
from django.conf import settings
from pathlib import Path
import tempfile
import zipfile
from pydicom import dcmread
from datetime import datetime
from django.utils import timezone
import shutil
from ..models import Patient, DICOMStudy

def process_bulk_dicom(modeladmin, request, queryset):
    '''
    Process uploaded zip files containing DICOM studies from multiple patients:
    1. Unzip to temp directory
    2. Process each DICOM file:
        - If patient exists: Move to patient's study directory in processed_dicom folder
        - If patient doesn't exist: Move to unprocessed directory
    3. Update database with study information for matched patients
    '''
    def sanitize(path):
        return path.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')

    # Create processed_dicom and unprocessed directories
    processed_dir = Path(settings.MEDIA_ROOT) / 'processed_dicom'
    unprocessed_dir = Path(settings.MEDIA_ROOT) / 'Unprocessed_DICOM'
    processed_dir.mkdir(parents=True, exist_ok=True)
    unprocessed_dir.mkdir(parents=True, exist_ok=True)

    for upload in queryset:
        if upload.status == 'Processed':
            messages.warning(request, f"Upload {upload.id} already processed")
            continue

        try:
            temp_dir = Path(tempfile.TemporaryDirectory().name)
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Process all files in directory tree
            dicom_files = [f for f in temp_dir.glob('**/*') if f.is_file()]
            processed_count = 0
            unprocessed_count = 0

            for file_path in dicom_files:
                try:
                    # Try to read as DICOM
                    ds = dcmread(file_path)
                    
                    # Extract patient ID and sanitize it
                    patient_id = ds.PatientID
                    sanitized_patient_id = sanitize(patient_id)
                    
                    # Get study information
                    study_instance_uid = ds.StudyInstanceUID
                    sop_instance_uid = ds.SOPInstanceUID
                    
                    try:
                        # Look for matching patient
                        patient = Patient.objects.get(patient_id=patient_id)
                        
                        # Update patient directory path to use processed_dicom subfolder
                        patient_dir = processed_dir / sanitized_patient_id
                        study_dir = patient_dir / sanitize(study_instance_uid)
                        study_dir.mkdir(parents=True, exist_ok=True)
                        
                        # Save DICOM file
                        ds.save_as(study_dir / f"{sanitize(sop_instance_uid)}.dcm")
                        
                        # Update or create DICOM study record
                        study_date = None
                        if hasattr(ds, 'StudyDate') and ds.StudyDate:
                            try:
                                study_date = datetime.strptime(ds.StudyDate, '%Y%m%d').date()
                            except ValueError as e:
                                messages.warning(request, f"Invalid date format in DICOM file {file_path.name}")

                        study_description = getattr(ds, 'StudyDescription', None)
                        series_description = getattr(ds, 'SeriesDescription', None)
                        
                        DICOMStudy.objects.update_or_create(
                            patient=patient,
                            study_instance_uid=study_instance_uid,
                            defaults={
                                'study_description': study_description,
                                'study_date': study_date,
                                'series_descriptions': series_description
                            }
                        )
                        processed_count += 1
                        
                    except Patient.DoesNotExist:
                        # Unprocessed directory path remains the same
                        unprocessed_patient_dir = unprocessed_dir / sanitized_patient_id / sanitize(study_instance_uid)
                        unprocessed_patient_dir.mkdir(parents=True, exist_ok=True)
                        ds.save_as(unprocessed_patient_dir / f"{sanitize(sop_instance_uid)}.dcm")
                        unprocessed_count += 1
                        
                except Exception as e:
                    messages.error(request, f"Error processing file {file_path.name}: {str(e)}")
                    continue

            # Update upload status
            upload.status = 'Processed'
            upload.processed_at = timezone.now()
            upload.save()

            messages.success(
                request,
                f"Processed {processed_count} DICOM files for existing patients and moved {unprocessed_count} files to unprocessed directory"
            )

        except Exception as e:
            messages.error(request, f"Error processing upload {upload.id}: {str(e)}")
            continue

        finally:
            # Cleanup temporary directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

# Short description for the admin interface
process_bulk_dicom.short_description = "Process Bulk DICOM Files"

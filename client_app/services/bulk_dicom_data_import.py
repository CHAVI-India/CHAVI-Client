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
from django.http import HttpResponseRedirect
from django.contrib import messages

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

    # Track unmatched patients to avoid duplicate messages
    unmatched_patients = set()
    error_files = []

    for upload in queryset:
        if upload.status == 'Processed':
            messages.warning(request, f"Upload {upload.id} already processed")
            continue

        try:
            temp_dir = Path(tempfile.TemporaryDirectory().name)
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Extract the zip file first
            with zipfile.ZipFile(upload.file.path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            # Process all files in directory tree
            dicom_files = [f for f in temp_dir.glob('**/*') if f.is_file()]
            processed_count = 0
            unprocessed_count = 0

            for file_path in dicom_files:
                try:
                    ds = dcmread(file_path)
                    patient_id = ds.PatientID
                    sanitized_patient_id = sanitize(patient_id)
                    study_instance_uid = ds.StudyInstanceUID
                    sop_instance_uid = ds.SOPInstanceUID
                    
                    try:
                        patient = Patient.objects.get(patient_id=patient_id)
                        
                        patient_dir = processed_dir / sanitized_patient_id
                        study_dir = patient_dir / sanitize(study_instance_uid)
                        study_dir.mkdir(parents=True, exist_ok=True)
                        
                        ds.save_as(study_dir / f"{sanitize(sop_instance_uid)}.dcm")
                        
                        study_date = None
                        if hasattr(ds, 'StudyDate') and ds.StudyDate:
                            try:
                                study_date = datetime.strptime(ds.StudyDate, '%Y%m%d').date()
                            except ValueError:
                                pass  # Skip invalid dates without message

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
                        unprocessed_patient_dir = unprocessed_dir / sanitized_patient_id / sanitize(study_instance_uid)
                        unprocessed_patient_dir.mkdir(parents=True, exist_ok=True)
                        ds.save_as(unprocessed_patient_dir / f"{sanitize(sop_instance_uid)}.dcm")
                        unprocessed_count += 1
                        unmatched_patients.add(patient_id)  # Track unique unmatched patients
                        
                except Exception as e:
                    error_files.append(f"{file_path.name}: {str(e)}")
                    continue

            # Update upload status
            upload.status = 'Processed'
            upload.processed_at = timezone.now()
            upload.save()

            # Summary messages
            if processed_count > 0:
                messages.success(
                    request,
                    f"Successfully processed {processed_count} DICOM files"
                )
            
            if unmatched_patients:
                messages.warning(
                    request,
                    f"No matching patients found for IDs: {', '.join(sorted(unmatched_patients))} ({unprocessed_count} files moved to unprocessed directory)"
                )

            if error_files:
                messages.error(
                    request,
                    f"Failed to process {len(error_files)} files. First few errors: {', '.join(error_files[:3])}"
                )

            return HttpResponseRedirect(request.path)

        except Exception as e:
            messages.error(request, f"Error processing upload {upload.id}: {str(e)}")
            continue

        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

# Short description for the admin interface
process_bulk_dicom.short_description = "Process Bulk DICOM Files"

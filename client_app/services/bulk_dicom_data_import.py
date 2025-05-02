from django.contrib import messages
from django.conf import settings
from pathlib import Path
import tempfile
import zipfile
from pydicom import dcmread
from datetime import datetime
from django.utils import timezone
import shutil
from ..models import Patient, DICOMStudy, UnprocessedDICOMStudies
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
    4. Record unmatched studies in the UnprocessedDICOMStudies model
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
            
            # Track study information
            study_data = {}  # Dictionary to track study data with study_instance_uid as key
            # Track unprocessed study folders
            unprocessed_study_folders = {}  # study_instance_uid -> folder path

            for file_path in dicom_files:
                try:
                    ds = dcmread(file_path)
                    patient_id = ds.PatientID
                    sanitized_patient_id = sanitize(patient_id)
                    study_instance_uid = ds.StudyInstanceUID
                    sop_instance_uid = ds.SOPInstanceUID
                    
                    # Initialize study data if not already present
                    if study_instance_uid not in study_data:
                        study_data[study_instance_uid] = {
                            'patient_id': patient_id,
                            'series_descriptions': set(),
                            'modalities': set(),
                            'study_description': None,
                            'study_date': None
                        }
                    
                    # Collect modality
                    if hasattr(ds, 'Modality') and ds.Modality:
                        study_data[study_instance_uid]['modalities'].add(ds.Modality)
                    
                    # Collect study description
                    if hasattr(ds, 'StudyDescription') and ds.StudyDescription:
                        study_data[study_instance_uid]['study_description'] = ds.StudyDescription
                    
                    # Collect series descriptions
                    if hasattr(ds, 'SeriesDescription') and ds.SeriesDescription:
                        study_data[study_instance_uid]['series_descriptions'].add(ds.SeriesDescription)
                    
                    # Collect study date
                    if hasattr(ds, 'StudyDate') and ds.StudyDate:
                        try:
                            study_date = datetime.strptime(ds.StudyDate, '%Y%m%d').date()
                            study_data[study_instance_uid]['study_date'] = study_date
                        except ValueError:
                            pass  # Skip invalid dates without message
                    
                    try:
                        patient = Patient.objects.get(patient_id=patient_id)
                        
                        patient_dir = processed_dir / sanitized_patient_id
                        study_dir = patient_dir / sanitize(study_instance_uid)
                        study_dir.mkdir(parents=True, exist_ok=True)
                        
                        ds.save_as(study_dir / f"{sanitize(sop_instance_uid)}.dcm")
                        processed_count += 1
                        
                    except Patient.DoesNotExist:
                        unprocessed_patient_dir = unprocessed_dir / sanitized_patient_id / sanitize(study_instance_uid)
                        unprocessed_patient_dir.mkdir(parents=True, exist_ok=True)
                        ds.save_as(unprocessed_patient_dir / f"{sanitize(sop_instance_uid)}.dcm")
                        unprocessed_count += 1
                        unmatched_patients.add(patient_id)  # Track unique unmatched patients
                        
                        # Store folder path for unprocessed studies
                        unprocessed_study_folders[study_instance_uid] = str(unprocessed_patient_dir)
                        
                except Exception as e:
                    error_files.append(f"{file_path.name}: {str(e)}")
                    continue
            
            # Update database with study information for matched patients
            for study_uid, data in study_data.items():
                try:
                    patient_id = data['patient_id']
                    
                    try:
                        patient = Patient.objects.get(patient_id=patient_id)
                        
                        # Convert series descriptions from set to comma-separated string
                        series_desc_string = ', '.join(sorted(data['series_descriptions'])) if data['series_descriptions'] else ''
                        
                        # Convert modalities from set to comma-separated string
                        modalities_string = ', '.join(sorted(data['modalities'])) if data['modalities'] else ''
                        
                        DICOMStudy.objects.update_or_create(
                            patient=patient,
                            study_instance_uid=study_uid,
                            defaults={
                                'study_description': data['study_description'],
                                'study_date': data['study_date'],
                                'series_descriptions': series_desc_string,
                                'study_modalities': modalities_string,
                                'folder_path': str(study_dir.absolute())
                            }
                        )
                    except Patient.DoesNotExist:
                        # Record unprocessed study in database
                        if study_uid in unprocessed_study_folders:
                            UnprocessedDICOMStudies.objects.update_or_create(
                                study_instance_uid=study_uid,
                                defaults={
                                    'dicom_patient_id': patient_id,
                                    'patient_id': None,  # Leave patient_id blank as requested
                                    'folder_path': unprocessed_study_folders[study_uid],
                                    'status': 'Unprocessed'
                                }
                            )
                        continue
                        
                except Exception as e:
                    error_files.append(f"Error updating study {study_uid}: {str(e)}")
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
                    f"No matching patients found for IDs: {', '.join(sorted(unmatched_patients))} ({unprocessed_count} files moved to unprocessed directory and recorded in database)"
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

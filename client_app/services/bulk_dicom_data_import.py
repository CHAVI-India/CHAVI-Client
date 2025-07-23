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
import logging

# Get logger for this module
logger = logging.getLogger(__name__)

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

    logger.info("Starting bulk DICOM import process")
    
    # Create processed_dicom and unprocessed directories
    processed_dir = Path(settings.MEDIA_ROOT) / 'processed_dicom'
    unprocessed_dir = Path(settings.MEDIA_ROOT) / 'Unprocessed_DICOM'
    processed_dir.mkdir(parents=True, exist_ok=True)
    unprocessed_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created/verified directories: {processed_dir} and {unprocessed_dir}")

    # Track unmatched patients to avoid duplicate messages
    unmatched_patients = set()
    error_files = []

    for upload in queryset:
        logger.info(f"Processing upload ID: {upload.id}")
        
        if upload.status == 'Processed':
            logger.warning(f"Upload {upload.id} already processed, skipping")
            messages.warning(request, f"Upload {upload.id} already processed")
            continue

        try:
            temp_dir = Path(tempfile.TemporaryDirectory().name)
            temp_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created temporary directory: {temp_dir}")

            # Extract the zip file first
            logger.info(f"Extracting zip file: {upload.file.path}")
            with zipfile.ZipFile(upload.file.path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            # Process all files in directory tree
            dicom_files = [f for f in temp_dir.glob('**/*') if f.is_file()]
            logger.info(f"Found {len(dicom_files)} files to process")
            processed_count = 0
            unprocessed_count = 0
            
            # Track study information
            study_data = {}  # Dictionary to track study data with study_instance_uid as key
            # Track unprocessed study folders
            unprocessed_study_folders = {}  # study_instance_uid -> folder path

            for file_path in dicom_files:
                try:
                    logger.debug(f"Processing file: {file_path}")
                    ds = dcmread(file_path)
                    patient_id = ds.PatientID
                    sanitized_patient_id = sanitize(patient_id)
                    study_instance_uid = ds.StudyInstanceUID
                    sop_instance_uid = ds.SOPInstanceUID
                    
                    logger.debug(f"File metadata - Patient ID: {patient_id}, Study UID: {study_instance_uid}, SOP UID: {sop_instance_uid}")
                    
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
                            logger.warning(f"Invalid study date format in file: {file_path}")
                    
                    try:
                        patient = Patient.objects.get(patient_id=patient_id)
                        logger.debug(f"Found matching patient: {patient_id}")
                        
                        patient_dir = processed_dir / sanitized_patient_id
                        study_dir = patient_dir / sanitize(study_instance_uid)
                        study_dir.mkdir(parents=True, exist_ok=True)
                        
                        ds.save_as(study_dir / f"{sanitize(sop_instance_uid)}.dcm", enforce_file_format=True)
                        processed_count += 1
                        logger.debug(f"Saved processed DICOM file to: {study_dir}")
                        
                    except Patient.DoesNotExist:
                        logger.warning(f"No matching patient found for ID: {patient_id}")
                        unprocessed_patient_dir = unprocessed_dir / sanitized_patient_id / sanitize(study_instance_uid)
                        unprocessed_patient_dir.mkdir(parents=True, exist_ok=True)
                        ds.save_as(unprocessed_patient_dir / f"{sanitize(sop_instance_uid)}.dcm")
                        unprocessed_count += 1
                        unmatched_patients.add(patient_id)
                        
                        # Store folder path for unprocessed studies
                        unprocessed_study_folders[study_instance_uid] = str(unprocessed_patient_dir)
                        logger.debug(f"Saved unprocessed DICOM file to: {unprocessed_patient_dir}")
                        
                except Exception as e:
                    error_msg = f"Error processing file {file_path.name}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    error_files.append(error_msg)
                    continue
            
            # Update database with study information for matched patients
            logger.info("Updating database with study information")
            for study_uid, data in study_data.items():
                try:
                    patient_id = data['patient_id']
                    
                    try:
                        patient = Patient.objects.get(patient_id=patient_id)
                        logger.debug(f"Updating study information for patient {patient_id}, study {study_uid}")
                        
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
                        logger.debug(f"Successfully updated study information for study {study_uid}")
                    except Patient.DoesNotExist:
                        logger.warning(f"Patient {patient_id} not found while updating study {study_uid}")
                        # Record unprocessed study in database
                        if study_uid in unprocessed_study_folders:
                            UnprocessedDICOMStudies.objects.update_or_create(
                                study_instance_uid=study_uid,
                                defaults={
                                    'dicom_patient_id': patient_id,
                                    'patient_id': None,
                                    'folder_path': unprocessed_study_folders[study_uid],
                                    'status': 'Unprocessed'
                                }
                            )
                            logger.debug(f"Recorded unprocessed study {study_uid} in database")
                        continue
                        
                except Exception as e:
                    error_msg = f"Error updating study {study_uid}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    error_files.append(error_msg)
                    continue

            # Update upload status
            upload.status = 'Processed'
            upload.processed_at = timezone.now()
            upload.save()
            logger.info(f"Updated upload status to Processed for upload {upload.id}")

            # Summary messages
            if processed_count > 0:
                success_msg = f"Successfully processed {processed_count} DICOM files"
                logger.info(success_msg)
                messages.success(request, success_msg)
            
            if unmatched_patients:
                warning_msg = f"No matching patients found for IDs: {', '.join(sorted(unmatched_patients))} ({unprocessed_count} files moved to unprocessed directory and recorded in database)"
                logger.warning(warning_msg)
                messages.warning(request, warning_msg)

            if error_files:
                error_msg = f"Failed to process {len(error_files)} files. First few errors: {', '.join(error_files[:3])}"
                logger.error(error_msg)
                messages.error(request, error_msg)

            return HttpResponseRedirect(request.path)

        except Exception as e:
            error_msg = f"Error processing upload {upload.id}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            messages.error(request, error_msg)
            continue

        finally:
            if temp_dir.exists():
                logger.debug(f"Cleaning up temporary directory: {temp_dir}")
                shutil.rmtree(temp_dir)

    logger.info("Completed bulk DICOM import process")

# Short description for the admin interface
process_bulk_dicom.short_description = "Process Bulk DICOM Files"

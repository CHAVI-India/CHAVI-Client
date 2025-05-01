from django.contrib import messages
from django.conf import settings
from pathlib import Path
import tempfile
import shutil
from pydicom import dcmread
from datetime import datetime
from client_app.models import DICOMStudy, UnprocessedDICOMStudies, Patient
from django.http import HttpResponseRedirect
import os

def process_unprocessed_dicom(modeladmin, request, queryset):
    '''
    Process the UnprocessedDICOMStudies stored in the database. The database has information about the DICOM files folder path where the files are being stored. Additionally there is a field called patient_id which is a FK reference to the Patient model.
    After the user selects the studies to process, first check if a patient_id has been associated the study. If it has been the first step is to modify the PatientID in the DICOM files to match the patient_id in the Patient model. After this the DICOM files are to be moved to the processed_dicom folder. Ensure that the DICOMStudy model is updated with information about the processed file. This will be done as per the dicom_data_import_per_patient file functionality.
    
    '''
    # Function to sanitize paths
    def sanitize(path):
        return path.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
    
    # Create processed_dicom directory if it doesn't exist
    processed_dir = Path(settings.MEDIA_ROOT) / 'processed_dicom'
    processed_dir.mkdir(parents=True, exist_ok=True)
    
    for obj in queryset:
        # Check if a patient_id has been associated with the study
        if not obj.patient_id:
            messages.error(request, f"Study {obj.study_instance_uid} does not have an associated patient. Please associate a patient first.")
            continue
        
        # Get the folder path where DICOM files are stored
        if not obj.folder_path:
            messages.error(request, f"Study {obj.study_instance_uid} does not have a valid folder path.")
            continue
        
        # Initialize processing statistics
        processing_stats = {
            'total_files': 0,
            'successful_files': 0,
            'failed_files': [],
            'successful_studies': 0,
            'failed_studies': []
        }
        
        try:
            # Extract Patient ID from the object
            patient_id = obj.patient_id.patient_id
            # Keep the sanitized patient_id for future paths
            patient_path = sanitize(patient_id)
            # Update save path to use processed_dicom subfolder
            save_path = processed_dir / patient_path
            save_path.mkdir(exist_ok=True, parents=True)
            
            study_uids = set()
            study_descriptions = {}  # Dict for descriptions
            study_dates = {}  # Dict for dates
            series_descriptions = {}  # Dict for series descriptions
            modalities = {}  # Dict for modalities
            
            # Get all DICOM files from the folder
            folder_path = Path(obj.folder_path)
            dicom_files = [file for file in folder_path.glob('**/*') if file.is_file()]
            processing_stats['total_files'] = len(dicom_files)
            
            for file in dicom_files:
                try:
                    # Read the DICOM Dataset
                    ds = dcmread(file)
                    
                    # Modify the PatientID to match the patient_id in the Patient model
                    ds.PatientID = patient_id
                    
                    # Get the Study Instance UID
                    study_instance_uid = ds.StudyInstanceUID
                    
                    # Collect study description with corresponding UID
                    if hasattr(ds, 'StudyDescription'):
                        study_descriptions[study_instance_uid] = ds.StudyDescription
                    
                    # Collect study date with corresponding UID
                    if hasattr(ds, 'StudyDate') and ds.StudyDate:
                        try:
                            study_date = datetime.strptime(ds.StudyDate, '%Y%m%d').date()
                            study_dates[study_instance_uid] = study_date
                        except ValueError as e:
                            messages.warning(request, f"Invalid date format in DICOM file {file.name}: {str(e)}")
                    
                    # Collect series descriptions
                    if hasattr(ds, 'SeriesDescription'):
                        # Initialize a set for this study if it doesn't exist
                        if study_instance_uid not in series_descriptions:
                            series_descriptions[study_instance_uid] = set()
                        # Add the series description to the set
                        series_descriptions[study_instance_uid].add(ds.SeriesDescription)
                    
                    # Collect modalities with corresponding UID
                    if hasattr(ds, 'Modality'):
                        # Initialize a set for this study if it doesn't exist
                        if study_instance_uid not in modalities:
                            modalities[study_instance_uid] = set()
                        # Add the modality to the set
                        modalities[study_instance_uid].add(ds.Modality)
                    
                    # Get the SOP Instance UID. This will become the filename.
                    sop_instance_uid = ds.SOPInstanceUID
                    
                    # Ensure paths are sanitized for future use.
                    folder_path = sanitize(study_instance_uid)
                    file_path = sanitize(sop_instance_uid)
                    
                    # Create the directory structure
                    study_dir = Path(save_path) / folder_path
                    study_dir.mkdir(exist_ok=True, parents=True)
                    
                    # Save the modified DICOM file
                    ds.save_as(study_dir / f"{file_path}.dcm")
                    
                    # Add Study Instance UID to set
                    study_uids.add(study_instance_uid)
                    processing_stats['successful_files'] += 1
                    
                except Exception as e:
                    processing_stats['failed_files'].append(f"{file.name}: {str(e)}")
                    messages.error(request, f"Error processing DICOM file {file.name} for {patient_id}: {str(e)}")
                    continue
            
            # Processing Study UID into the DICOMStudy Table
            for uid in study_uids:
                try:
                    series_desc_string = ', '.join(sorted(series_descriptions.get(uid, []))) if uid in series_descriptions else ''
                    modalities_string = ', '.join(sorted(modalities.get(uid, []))) if uid in modalities else ''
                    
                    DICOMStudy.objects.update_or_create(
                        patient=obj.patient_id,
                        study_instance_uid=uid,
                        defaults={
                            'study_description': study_descriptions.get(uid),
                            'study_date': study_dates.get(uid),
                            'series_descriptions': series_desc_string,
                            'study_modalities': modalities_string,
                        }
                    )
                    processing_stats['successful_studies'] += 1
                    messages.success(request, f"Added DICOM study UID {uid} data for {patient_id}")
                    
                except Exception as e:
                    processing_stats['failed_studies'].append(f"{uid}: {str(e)}")
                    messages.error(request, f"Error adding DICOM data for Study {uid}")
                    continue
            
            # Create processing log
            log_parts = [
                f"Processing completed for {patient_id} \n",
                f"Total files processed: {processing_stats['total_files']} \n",
                f"Successfully processed files: {processing_stats['successful_files']} \n",
                f"Failed files: {len(processing_stats['failed_files'])} \n",
                f"Successfully processed studies: {processing_stats['successful_studies']} \n",
                f"Failed studies: {len(processing_stats['failed_studies'])}"
            ]
            
            if processing_stats['failed_files']:
                log_parts.append("\nFailed files details:")
                log_parts.extend(processing_stats['failed_files'])
            
            if processing_stats['failed_studies']:
                log_parts.append("\nFailed studies details:")
                log_parts.extend(processing_stats['failed_studies'])
            
            # Update the UnprocessedDICOMStudies status
            obj.status = "Processed"
            obj.save()
            
            messages.success(request, f"Successfully processed DICOM study {obj.study_instance_uid}")
            
        except Exception as e:
            messages.error(request, f"Error processing study {obj.study_instance_uid}: {str(e)}")
            continue
            
    return HttpResponseRedirect(request.path)

# Short description for the admin interface
process_unprocessed_dicom.short_description = "Process selected unprocessed DICOM studies"
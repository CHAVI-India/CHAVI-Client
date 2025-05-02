from django.contrib import messages
from django.conf import settings
from pathlib import Path
import tempfile
import zipfile
from pydicom import dcmread
from datetime import datetime
import shutil
from ..models import DICOMStudy, Patient
from django.http import HttpResponseRedirect
from django.contrib import messages

def process_dicom(modeladmin, request, queryset):
    '''
    This custom admin action is there to do the following :
    1. Unzip the uploaded zipped file into the temporary directory.
    2. From the directory take all DICOM files and change the Patient ID tag to match that of the patient ID in the query set. This ensures that the de-identification process will produce the same ID even if the patient has undergone imaging at different centers. 
    3. Extract the SOP Instance UID and Study Instance UID and then create save the files inside a folder inside the Media directory. The folder is specific for each patient. Thus all studies for a given patient will be stored in the same folder. 
    4. The created folder structure will thus look like this processed_dicom/Patient_id/StudyInstanceUID/SOPInstanceUID.dcm
    5. Delete the temporary directory where the files were processed.
    '''
    # Function to sanitize paths
    def sanitize(path):
        return path.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
    
    # Create processed_dicom directory if it doesn't exist
    processed_dir = Path(settings.MEDIA_ROOT) / 'processed_dicom'
    processed_dir.mkdir(parents=True, exist_ok=True)
    
    for obj in queryset:
        # Initialize processing statistics
        processing_stats = {
            'total_files': 0,
            'successful_files': 0,
            'failed_files': [],
            'successful_studies': 0,
            'failed_studies': []
        }
        
        # If the file is not there there raise an error.
        if not obj.file:
            messages.error(request, f"No file found for {obj.patient.patient_id}")
            obj.processing_log = "Error: No file found"
            obj.processed = True
            obj.save()
            continue

        # Create the temporary directory where the files will be processed.    
        temp_dir = Path(tempfile.TemporaryDirectory().name)
        # Extract Patient ID from the queryset for the object
        patient_id = obj.patient.patient_id
        # Keep the sanitized patient_id for future paths. 
        patient_path = sanitize(patient_id)
        # Update save path to use processed_dicom subfolder
        save_path = processed_dir / patient_path
        save_path.mkdir(exist_ok=True, parents=True)

        study_uids = set()
        study_descriptions = {}  # Dict of sets for descriptions
        study_dates = {}  # Dict of sets for dates
        series_descriptions = {}  # Dict of sets for series descriptions
        modalities = {}  # Dict of sets for modalities

        try:
            # First we will extract all the files from the zip file
            with zipfile.ZipFile(obj.file.path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            # Next we will process each DICOM file and extract the metadata
            dicom_files = [files for files in temp_dir.glob('**/*') if files.is_file()]
            processing_stats['total_files'] = len(dicom_files)

            for file in dicom_files:
                try:
                    # Read the DICOM Dataset
                    ds = dcmread(file)
                    # Get the Study Instance UID. We will use this to create folder paths.
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

                    # Overwrite the patient ID with the patient ID. 
                    # This will ensure all DICOM files of a patient from different sources will have the same ID and help de-identification and linkage.
                    ds.PatientID = patient_id

                    # Create the directory structure
                    study_dir = Path(save_path) / folder_path
                    study_dir.mkdir(exist_ok=True, parents=True)
                    # Save the DICOM file
                    ds.save_as(study_dir / f"{file_path}.dcm")

                    # Add Study Instance UID, Modality and Study Description to sets prepared previously.
                    study_uids.add(study_instance_uid)
                    processing_stats['successful_files'] += 1

                except Exception as e:
                    processing_stats['failed_files'].append(f"{file.name}: {str(e)}")
                    messages.error(request, f"Error processing DICOM file {file.name} for {obj.patient.patient_id}: {str(e)}")
                    continue        
            
            #  Processing Study UID into the DICOMStudy Table
            for uid in study_uids:
                try: 
                    series_desc_string = ', '.join(sorted(series_descriptions.get(uid, []))) if uid in series_descriptions else ''
                    modalities_string = ', '.join(sorted(modalities.get(uid, []))) if uid in modalities else ''
                    DICOMStudy.objects.update_or_create(
                        patient=obj.patient,
                        study_instance_uid=uid,
                        defaults={
                            'study_description': study_descriptions.get(uid),
                            'study_date': study_dates.get(uid),
                            'series_descriptions': series_desc_string,
                            'study_modalities': modalities_string,
                            'folder_path': str(study_dir.absolute()),
                        }
                    )
                    processing_stats['successful_studies'] += 1
                    messages.success(request,f"Added DICOM study UID {uid} Data for {obj.patient.patient_id}")

                except Exception as e:
                    processing_stats['failed_studies'].append(f"{uid}: {str(e)}")
                    messages.error(request,f"Error adding DICOM data for Study")
                    continue

            # Create processing log
            log_parts = [
                f"Processing completed for {obj.patient.patient_id} \n",
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

            # Update the PatientDicomFile object
            obj.processing_log = "\n".join(log_parts)
            obj.processed = True
            obj.save()

            return HttpResponseRedirect(request.path)

        except zipfile.BadZipFile:
            error_msg = f"Invalid zip file for {obj.patient.patient_id}"
            messages.error(request, error_msg)
            obj.processing_log = f"Error: {error_msg}"
            obj.processed = True
            obj.save()
            continue

# Short description for the admin interface
process_dicom.short_description = "Extract and Process DICOM File and extract metadata"

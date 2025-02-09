from django.contrib import messages
from django.conf import settings
from pathlib import Path
import tempfile
import zipfile
from pydicom import dcmread
from datetime import datetime
import shutil
from ..models import DICOMStudy, Patient

def process_dicom(modeladmin, request, queryset):
    '''
    This custom admin action is there to do the following :
    1. Unzip the uploaded zipped file into the temporary directory.
    2. From the directory take all DICOM files and change the Patient ID tag to match that of the patient ID in the query set. This ensures that the de-identification process will produce the same ID even if the patient has undergone imaging at different centers. 
    3. Extract the SOP Instance UID and Study Instance UID and then create save the files inside a folder inside the Media directory. The folder is specific for each patient. Thus all studies for a given patient will be stored in the same folder. 
    4. The created folder structure will thus look like this Patient_id > StudyInstanceUID > SOPInstanceUID.dcm
    5. Delete the temporary directory where the files were processed.
    '''
    # Function to sanitize paths
    def sanitize(path):
        return path.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
    
    # Create processed_dicom directory if it doesn't exist
    processed_dir = Path(settings.MEDIA_ROOT) / 'processed_dicom'
    processed_dir.mkdir(parents=True, exist_ok=True)
    
    for obj in queryset:
        # If the file is not there there raise an error.
        if not obj.file:
            messages.error(request, f"No file found for {obj.patient.patient_id}")
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

        try:
            # First we will extract all the files from the zip file
            with zipfile.ZipFile(obj.file.path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            # Next we will process each DICOM file and extract the metadata
            dicom_files = [files for files in temp_dir.glob('**/*') if files.is_file()]

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

                except Exception as e:
                    messages.error(request, f"Error processing DICOM file {file.name} for {obj.patient.patient_id}: {str(e)}")
                    continue        
            
            #  Processing Study UID into the DICOMStudy Table
            for uid in study_uids:
                try: 
                    # Convert set of series descriptions to comma-separated string
                    series_desc_string = ', '.join(sorted(series_descriptions.get(uid, []))) if uid in series_descriptions else ''
                    
                    DICOMStudy.objects.update_or_create(
                        patient=obj.patient,
                        study_instance_uid=uid,
                        defaults={
                            'study_description': study_descriptions.get(uid),
                            'study_date': study_dates.get(uid),
                            'series_descriptions': series_desc_string,  # Add the new field
                        }
                    )
                    messages.success(request,f"Added DICOM study UID {uid} Data for {obj.patient.patient_id}")
                except Exception as e:
                    messages.error(request,f"Error adding DICOM data for Study")   

            # Convert the folder to zip format.
            try:
                shutil.make_archive(base_name=f"{save_path}", format='zip', root_dir=save_path)
                messages.success(request, f"Successfully converted folder to zip for {obj.patient.patient_id}")
                shutil.rmtree(save_path)
            except Exception as e:
                messages.error(request, f"Error converting folder to zip for {obj.patient.patient_id}: {str(e)}")

        except zipfile.BadZipFile:
            messages.error(request, f"Invalid zip file for {obj.patient.patient_id}")
            continue

# Short description for the admin interface
process_dicom.short_description = "Extract and Process DICOM File and extract metadata"

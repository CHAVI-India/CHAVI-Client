"""
Service module for frontend bulk DICOM import with manual patient matching.
This module handles the extraction, analysis, and processing of bulk DICOM uploads
with support for manual patient matching.
"""

from django.conf import settings
from pathlib import Path
import tempfile
import zipfile
from pydicom import dcmread
from datetime import datetime
from django.utils import timezone
import shutil
from ..models import Patient, DICOMStudy, UnprocessedDICOMStudies, BulkDICOMUploadSession, BulkDICOMStudyMatch
import logging
import uuid

logger = logging.getLogger(__name__)


def sanitize(path):
    """Sanitize path by replacing invalid characters"""
    return path.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')


def extract_and_analyze_upload(session):
    """
    Extract uploaded zip file and analyze DICOM studies.
    Returns a dictionary with study information and matching status.
    """
    logger.info(f"Starting extraction and analysis for session {session.session_id}")
    
    try:
        # Create temporary directory for extraction
        temp_dir = Path(tempfile.mkdtemp(prefix=f'bulk_dicom_{session.session_id}_'))
        session.temp_directory = str(temp_dir)
        session.status = BulkDICOMUploadSession.StatusChoices.EXTRACTED
        session.save()
        
        logger.info(f"Extracting to temporary directory: {temp_dir}")
        
        # Extract the zip file
        with zipfile.ZipFile(session.uploaded_file.path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Find all DICOM files
        dicom_files = [f for f in temp_dir.glob('**/*') if f.is_file()]
        logger.info(f"Found {len(dicom_files)} files to analyze")
        
        # Dictionary to track study information
        study_data = {}  # study_instance_uid -> study info
        
        for file_path in dicom_files:
            try:
                ds = dcmread(file_path)
                patient_id = ds.PatientID
                study_instance_uid = ds.StudyInstanceUID
                
                # Initialize study data if not present
                if study_instance_uid not in study_data:
                    study_data[study_instance_uid] = {
                        'patient_id': patient_id,
                        'study_instance_uid': study_instance_uid,
                        'series_descriptions': set(),
                        'modalities': set(),
                        'study_description': None,
                        'study_date': None,
                        'file_count': 0,
                        'files': []
                    }
                
                # Collect metadata
                if hasattr(ds, 'Modality') and ds.Modality:
                    study_data[study_instance_uid]['modalities'].add(ds.Modality)
                
                if hasattr(ds, 'StudyDescription') and ds.StudyDescription:
                    study_data[study_instance_uid]['study_description'] = ds.StudyDescription
                
                if hasattr(ds, 'SeriesDescription') and ds.SeriesDescription:
                    study_data[study_instance_uid]['series_descriptions'].add(ds.SeriesDescription)
                
                if hasattr(ds, 'StudyDate') and ds.StudyDate:
                    try:
                        study_date = datetime.strptime(ds.StudyDate, '%Y%m%d').date()
                        study_data[study_instance_uid]['study_date'] = study_date
                    except ValueError:
                        logger.warning(f"Invalid study date format in file: {file_path}")
                
                study_data[study_instance_uid]['file_count'] += 1
                study_data[study_instance_uid]['files'].append(file_path)
                
            except Exception as e:
                logger.error(f"Error reading DICOM file {file_path}: {str(e)}")
                continue
        
        # Create study match records and determine matching status
        auto_matched = 0
        manual_required = 0
        
        for study_uid, data in study_data.items():
            patient_id = data['patient_id']
            
            # Try to find matching patient
            try:
                patient = Patient.objects.get(patient_id=patient_id)
                match_status = BulkDICOMStudyMatch.MatchStatus.AUTO_MATCHED
                matched_patient = patient
                auto_matched += 1
                logger.info(f"Auto-matched study {study_uid} to patient {patient_id}")
            except Patient.DoesNotExist:
                match_status = BulkDICOMStudyMatch.MatchStatus.MANUAL_MATCH_REQUIRED
                matched_patient = None
                manual_required += 1
                logger.info(f"Manual match required for study {study_uid} with patient ID {patient_id}")
            
            # Create temporary folder for this study
            sanitized_patient_id = sanitize(patient_id)
            study_temp_folder = temp_dir / sanitized_patient_id / sanitize(study_uid)
            study_temp_folder.mkdir(parents=True, exist_ok=True)
            
            # Move DICOM files to organized structure
            for file_path in data['files']:
                try:
                    ds = dcmread(file_path)
                    sop_instance_uid = ds.SOPInstanceUID
                    dest_path = study_temp_folder / f"{sanitize(sop_instance_uid)}.dcm"
                    shutil.move(str(file_path), str(dest_path))
                except Exception as e:
                    logger.error(f"Error moving file {file_path}: {str(e)}")
            
            # Create study match record
            BulkDICOMStudyMatch.objects.create(
                session=session,
                study_instance_uid=study_uid,
                dicom_patient_id=patient_id,
                study_description=data['study_description'],
                study_date=data['study_date'],
                modalities=', '.join(sorted(data['modalities'])) if data['modalities'] else '',
                series_descriptions=', '.join(sorted(data['series_descriptions'])) if data['series_descriptions'] else '',
                file_count=data['file_count'],
                match_status=match_status,
                matched_patient=matched_patient,
                temp_folder_path=str(study_temp_folder)
            )
        
        # Update session statistics
        session.total_studies = len(study_data)
        session.auto_matched_studies = auto_matched
        session.manual_match_required = manual_required
        session.status = BulkDICOMUploadSession.StatusChoices.ANALYZED
        session.save()
        
        logger.info(f"Analysis complete: {auto_matched} auto-matched, {manual_required} require manual matching")
        
        return {
            'success': True,
            'total_studies': len(study_data),
            'auto_matched': auto_matched,
            'manual_required': manual_required
        }
        
    except Exception as e:
        logger.error(f"Error during extraction and analysis: {str(e)}", exc_info=True)
        session.status = BulkDICOMUploadSession.StatusChoices.FAILED
        session.error_log = str(e)
        session.save()
        return {
            'success': False,
            'error': str(e)
        }


def process_confirmed_matches(session):
    """
    Process all confirmed study matches and move files to final locations.
    Creates DICOMStudy records for matched studies and UnprocessedDICOMStudies for unmatched.
    """
    logger.info(f"Starting processing for session {session.session_id}")
    
    try:
        session.status = BulkDICOMUploadSession.StatusChoices.PROCESSING
        session.save()
        
        # Create directories
        processed_dir = Path(settings.MEDIA_ROOT) / 'processed_dicom'
        unprocessed_dir = Path(settings.MEDIA_ROOT) / 'Unprocessed_DICOM'
        processed_dir.mkdir(parents=True, exist_ok=True)
        unprocessed_dir.mkdir(parents=True, exist_ok=True)
        
        # Get all study matches for this session
        study_matches = BulkDICOMStudyMatch.objects.filter(session=session)
        
        processed_count = 0
        unprocessed_count = 0
        error_count = 0
        
        for study_match in study_matches:
            try:
                if study_match.match_status == BulkDICOMStudyMatch.MatchStatus.CONFIRMED and study_match.matched_patient:
                    # Process matched study
                    patient = study_match.matched_patient
                    sanitized_patient_id = sanitize(patient.patient_id)
                    
                    # Create final directory
                    patient_dir = processed_dir / sanitized_patient_id
                    study_dir = patient_dir / sanitize(study_match.study_instance_uid)
                    study_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Check if this was manually matched (DICOM patient ID differs from matched patient ID)
                    is_manually_matched = (study_match.dicom_patient_id != patient.patient_id)
                    
                    # Move files from temp to final location
                    temp_folder = Path(study_match.temp_folder_path)
                    if temp_folder.exists():
                        for dicom_file in temp_folder.glob('*.dcm'):
                            dest_file = study_dir / dicom_file.name
                            
                            # If manually matched, modify DICOM metadata to match the correct patient
                            if is_manually_matched:
                                try:
                                    ds = dcmread(str(dicom_file))
                                    
                                    # Overwrite the patient ID with the correct patient ID
                                    # This ensures all DICOM files have consistent patient identification
                                    ds.PatientID = patient.patient_id
                                    
                                    # Optionally update Patient Name if it exists
                                    if hasattr(ds, 'PatientName'):
                                        ds.PatientName = patient.patient_id
                                    
                                    # Save the modified DICOM file
                                    ds.save_as(str(dest_file), enforce_file_format=True)
                                    logger.info(f"Modified DICOM metadata for manually matched file: {dicom_file.name}")
                                except Exception as e:
                                    logger.error(f"Error modifying DICOM metadata for {dicom_file.name}: {str(e)}")
                                    # Fall back to simple copy if modification fails
                                    shutil.copy2(str(dicom_file), str(dest_file))
                            else:
                                # Auto-matched studies - just copy without modification
                                shutil.copy2(str(dicom_file), str(dest_file))
                    
                    # Create or update DICOMStudy record
                    DICOMStudy.objects.update_or_create(
                        patient=patient,
                        study_instance_uid=study_match.study_instance_uid,
                        defaults={
                            'study_description': study_match.study_description,
                            'study_date': study_match.study_date,
                            'series_descriptions': study_match.series_descriptions,
                            'study_modalities': study_match.modalities,
                            'folder_path': str(study_dir.absolute())
                        }
                    )
                    
                    study_match.match_status = BulkDICOMStudyMatch.MatchStatus.PROCESSED
                    study_match.final_folder_path = str(study_dir)
                    study_match.save()
                    
                    processed_count += 1
                    logger.info(f"Processed study {study_match.study_instance_uid} for patient {patient.patient_id}")
                    
                elif study_match.match_status == BulkDICOMStudyMatch.MatchStatus.UNMATCHED:
                    # Move to unprocessed directory
                    sanitized_patient_id = sanitize(study_match.dicom_patient_id)
                    unprocessed_patient_dir = unprocessed_dir / sanitized_patient_id / sanitize(study_match.study_instance_uid)
                    unprocessed_patient_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Move files
                    temp_folder = Path(study_match.temp_folder_path)
                    if temp_folder.exists():
                        for dicom_file in temp_folder.glob('*.dcm'):
                            dest_file = unprocessed_patient_dir / dicom_file.name
                            shutil.copy2(str(dicom_file), str(dest_file))
                    
                    # Create UnprocessedDICOMStudies record
                    UnprocessedDICOMStudies.objects.update_or_create(
                        study_instance_uid=study_match.study_instance_uid,
                        defaults={
                            'dicom_patient_id': study_match.dicom_patient_id,
                            'patient_id': None,
                            'folder_path': str(unprocessed_patient_dir),
                            'status': 'Unprocessed'
                        }
                    )
                    
                    study_match.final_folder_path = str(unprocessed_patient_dir)
                    study_match.save()
                    
                    unprocessed_count += 1
                    logger.info(f"Moved study {study_match.study_instance_uid} to unprocessed")
                    
            except Exception as e:
                logger.error(f"Error processing study {study_match.study_instance_uid}: {str(e)}", exc_info=True)
                error_count += 1
                continue
        
        # Clean up temporary directory
        if session.temp_directory:
            temp_dir = Path(session.temp_directory)
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temporary directory: {temp_dir}")
        
        # Update session
        session.status = BulkDICOMUploadSession.StatusChoices.COMPLETED
        session.completed_at = timezone.now()
        session.save()
        
        logger.info(f"Processing complete: {processed_count} processed, {unprocessed_count} unprocessed, {error_count} errors")
        
        return {
            'success': True,
            'processed': processed_count,
            'unprocessed': unprocessed_count,
            'errors': error_count
        }
        
    except Exception as e:
        logger.error(f"Error during processing: {str(e)}", exc_info=True)
        session.status = BulkDICOMUploadSession.StatusChoices.FAILED
        session.error_log = str(e)
        session.save()
        return {
            'success': False,
            'error': str(e)
        }

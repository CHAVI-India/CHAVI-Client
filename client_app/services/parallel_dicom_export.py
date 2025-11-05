"""
Parallel DICOM Export Service with Progress Tracking
This module provides multiprocessing-based DICOM export functionality with real-time progress tracking.
"""
import os
import zipfile
import logging
import re
from pathlib import Path
from multiprocessing import Pool, cpu_count
from django.http import HttpResponse
from django.contrib import messages
from django.conf import settings
from django.core.cache import cache
import shutil


logger = logging.getLogger(__name__)


def sanitize_filename(filename):
    """
    Sanitize filename by replacing problematic characters that could create subdirectories
    or cause file system issues.
    """
    # Replace forward slashes and other problematic characters with underscores
    sanitized = re.sub(r'[/\\:*?"<>|]', '_', filename)
    # Remove any leading/trailing whitespace and dots
    sanitized = sanitized.strip('. ')
    # Ensure the filename is not empty
    if not sanitized:
        sanitized = 'unknown'
    return sanitized


def process_study_files(study_data):
    """
    Process a single study and return list of files to add to zip.
    This function is designed to be used with multiprocessing.
    
    Args:
        study_data (dict): Dictionary containing study_uid, folder_path, and patient_id
        
    Returns:
        dict: Result dictionary with success status, files list, or error information
    """
    study_uid = study_data['study_uid']
    folder_path = study_data['folder_path']
    patient_id = study_data['patient_id']
    
    files_to_add = []
    
    if not folder_path or not os.path.exists(folder_path):
        return {'success': False, 'study_uid': study_uid, 'error': 'Invalid folder path'}
    
    study_path = Path(folder_path)
    if not study_path.exists():
        return {'success': False, 'study_uid': study_uid, 'error': 'Folder does not exist'}
    
    try:
        # Collect all files in the study folder
        for file_path in study_path.rglob('*'):
            if file_path.is_file():
                try:
                    rel_path = file_path.relative_to(study_path)
                    sanitized_patient_id = sanitize_filename(patient_id)
                    arcname = f"{sanitized_patient_id}/{study_uid}/{rel_path}"
                    files_to_add.append({
                        'file_path': str(file_path),
                        'arcname': arcname
                    })
                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {str(e)}")
                    continue
        
        return {
            'success': True,
            'study_uid': study_uid,
            'files': files_to_add,
            'file_count': len(files_to_add)
        }
    except Exception as e:
        logger.error(f"Error processing study {study_uid}: {str(e)}")
        return {'success': False, 'study_uid': study_uid, 'error': str(e)}


def export_dicom_data_parallel(queryset, task_id):
    """
    Export DICOM data using multiprocessing for faster processing with progress tracking.
    
    This function processes DICOM studies in parallel and creates a ZIP file containing
    all DICOM files organized by patient ID and study UID.
    
    Args:
        queryset: Django queryset of DICOMStudy objects to export
        task_id (str): Unique task identifier for progress tracking
        
    Returns:
        dict: Result dictionary with status, message, and file path information
    """
    # Create a temporary directory inside media folder
    temp_dir = Path(settings.MEDIA_ROOT) / 'temp_export'
    temp_dir.mkdir(exist_ok=True)
    
    # Use task_id for unique zip filename
    zip_filename = f'dicom_export_{task_id}.zip'
    zip_path = temp_dir / zip_filename
    
    try:
        # Prepare study data for multiprocessing
        total_studies = queryset.count()
        study_data_list = []
        
        for study in queryset:
            study_data_list.append({
                'study_uid': study.study_instance_uid,
                'folder_path': study.folder_path,
                'patient_id': study.patient.patient_id
            })
        
        # Update progress: Starting
        cache.set(f'export_progress_{task_id}', {
            'status': 'processing',
            'progress': 0,
            'total': total_studies,
            'current': 0,
            'message': 'Starting export...'
        }, timeout=3600)
        
        # Use multiprocessing to process studies in parallel
        num_processes = min(cpu_count(), 4)  # Use up to 4 processes
        processed_results = []
        
        logger.info(f"Starting parallel processing with {num_processes} processes for {total_studies} studies")
        
        with Pool(processes=num_processes) as pool:
            # Process studies in parallel
            for i, result in enumerate(pool.imap_unordered(process_study_files, study_data_list)):
                processed_results.append(result)
                
                # Update progress (0-50% for processing)
                progress = int((i + 1) / total_studies * 50)
                cache.set(f'export_progress_{task_id}', {
                    'status': 'processing',
                    'progress': progress,
                    'total': total_studies,
                    'current': i + 1,
                    'message': f'Processing study {i + 1} of {total_studies}...'
                }, timeout=3600)
        
        logger.info(f"Completed parallel processing. Creating ZIP file...")
        
        # Update progress: Creating ZIP
        cache.set(f'export_progress_{task_id}', {
            'status': 'zipping',
            'progress': 50,
            'total': total_studies,
            'current': total_studies,
            'message': 'Creating ZIP file...'
        }, timeout=3600)
        
        # Create the zip file with collected files
        processed_studies = 0
        skipped_studies = 0
        total_files = 0
        error_messages = []
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
            for idx, result in enumerate(processed_results):
                if result['success']:
                    for file_info in result['files']:
                        try:
                            zipf.write(file_info['file_path'], file_info['arcname'])
                            total_files += 1
                        except Exception as e:
                            logger.error(f"Error adding file to zip: {str(e)}")
                            continue
                    processed_studies += 1
                else:
                    skipped_studies += 1
                    error_msg = f"Study {result['study_uid']}: {result.get('error', 'Unknown error')}"
                    error_messages.append(error_msg)
                    logger.warning(error_msg)
                
                # Update progress during zipping (50-100%)
                progress = 50 + int((idx + 1) / len(processed_results) * 50)
                cache.set(f'export_progress_{task_id}', {
                    'status': 'zipping',
                    'progress': progress,
                    'total': len(processed_results),
                    'current': idx + 1,
                    'message': f'Adding files to ZIP: {idx + 1} of {len(processed_results)} studies...'
                }, timeout=3600)
        
        # If no studies were processed, return error
        if processed_studies == 0:
            cache.set(f'export_progress_{task_id}', {
                'status': 'error',
                'progress': 100,
                'message': 'No valid DICOM studies were found to export.'
            }, timeout=3600)
            logger.error("No valid DICOM studies were found to export")
            return {
                'success': False,
                'message': 'No valid DICOM studies were found to export.'
            }
        
        # Verify the zip file exists and is not empty
        if not zip_path.exists() or zip_path.stat().st_size == 0:
            cache.set(f'export_progress_{task_id}', {
                'status': 'error',
                'progress': 100,
                'message': 'Failed to create zip file.'
            }, timeout=3600)
            logger.error("Failed to create zip file")
            return {
                'success': False,
                'message': 'Failed to create zip file.'
            }
        
        # Update progress: Complete
        logger.info(f"Export complete: {processed_studies} studies, {total_files} files, {skipped_studies} skipped")
        cache.set(f'export_progress_{task_id}', {
            'status': 'complete',
            'progress': 100,
            'total': total_studies,
            'processed': processed_studies,
            'skipped': skipped_studies,
            'total_files': total_files,
            'message': f'Export complete! {processed_studies} studies, {total_files} files.',
            'zip_path': str(zip_path),
            'zip_filename': zip_filename,
            'errors': error_messages[:10]  # Store first 10 errors
        }, timeout=3600)
        
        return {
            'success': True,
            'message': f'Successfully exported {processed_studies} studies ({total_files} files). {skipped_studies} studies were skipped.',
            'zip_path': str(zip_path),
            'processed': processed_studies,
            'skipped': skipped_studies,
            'total_files': total_files
        }
            
    except Exception as e:
        logger.error(f"Error creating zip file: {str(e)}", exc_info=True)
        cache.set(f'export_progress_{task_id}', {
            'status': 'error',
            'progress': 100,
            'message': f'Error: {str(e)}'
        }, timeout=3600)
        return {
            'success': False,
            'message': f'Error creating zip file: {str(e)}'
        }

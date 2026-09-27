def sanitize_filename(filename):
    """
    Sanitize filename by replacing problematic characters that could create subdirectories
    or cause file system issues.
    """
    import re
    # Replace forward slashes and other problematic characters with underscores
    sanitized = re.sub(r'[/\\:*?"<>|]', '_', filename)
    # Remove any leading/trailing whitespace and dots
    sanitized = sanitized.strip('. ')
    # Ensure the filename is not empty
    if not sanitized:
        sanitized = 'unknown'
    return sanitized


def export_dicom_data(modeladmin, request, queryset):
    '''
    This function will export the dicom data into a single zip file for all the objects selected in the DICOMStudy model where there is a valid folder_path
    '''
    import os
    import zipfile
    from django.http import HttpResponse
    from django.contrib import messages
    from pathlib import Path
    import shutil
    from django.conf import settings
    import logging

    logger = logging.getLogger(__name__)

    # Messages queued while the zip is being built cannot be rendered when this
    # action returns a file download; buffer them and flush to messages only on
    # paths that re-render the admin changelist, otherwise write them to the log.
    pending = []

    def flush_to_messages():
        for level, text in pending:
            messages.add_message(request, level, text)
        pending.clear()

    def flush_to_log():
        for level, text in pending:
            logger.log(logging.INFO if level == messages.SUCCESS else level, text)
        pending.clear()

    # Create a temporary directory inside media folder
    temp_dir = Path(settings.MEDIA_ROOT) / 'temp_export'
    temp_dir.mkdir(exist_ok=True)
    zip_path = temp_dir / 'dicom_export.zip'
    
    try:
        # Create a zip file
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED, allowZip64=True) as zipf:
            # Track statistics
            total_studies = queryset.count()
            processed_studies = 0
            skipped_studies = 0
            total_files = 0
            
            # Process each selected study
            for study in queryset:
                if not study.folder_path or not os.path.exists(study.folder_path):
                    pending.append((messages.WARNING, f"Study {study.study_instance_uid} has no valid folder path. Skipping."))
                    skipped_studies += 1
                    continue
                
                # Get all files in the study folder
                study_path = Path(study.folder_path)
                if not study_path.exists():
                    pending.append((messages.WARNING, f"Study folder {study.folder_path} does not exist. Skipping."))
                    skipped_studies += 1
                    continue
                try:
                    # Add all files and subfolders to the zip
                    for file_path in study_path.rglob('*'):
                        if file_path.is_file():  # Only add files, not directories
                            try:
                                # Get the relative path from the study folder to maintain folder structure
                                rel_path = file_path.relative_to(study_path)
                                # Create the full path in the zip including sanitized patient ID and study UID
                                sanitized_patient_id = sanitize_filename(study.patient.patient_id)
                                arcname = f"{sanitized_patient_id}/{study.study_instance_uid}/{rel_path}"
                                # Add the file to the zip, preserving its relative path
                                zipf.write(file_path, arcname)
                                total_files += 1
                            except Exception as e:
                                logger.error(f"Error adding file {file_path} to zip: {str(e)}")
                                pending.append((messages.WARNING, f"Error adding file {file_path.name} to zip. Skipping."))
                                continue
                    
                    processed_studies += 1
                except Exception as e:
                    logger.error(f"Error processing study {study.study_instance_uid}: {str(e)}")
                    pending.append((messages.ERROR, f"Error processing study {study.study_instance_uid}: {str(e)}"))
                    continue

            # If no studies were processed, return with an error message
            if processed_studies == 0:
                flush_to_messages()
                messages.error(request, "No valid DICOM studies were found to export.")
                return

            # Ensure the zip file is properly closed before reading
            zipf.close()

            # Verify the zip file exists and is not empty
            if not zip_path.exists() or zip_path.stat().st_size == 0:
                flush_to_messages()
                messages.error(request, "Failed to create zip file.")
                return

            # Create the response
            try:
                with open(zip_path, 'rb') as f:
                    response = HttpResponse(f.read(), content_type='application/zip')
                    response['Content-Disposition'] = 'attachment; filename=dicom_export.zip'

                    # The response is a file download, so nothing rendered can
                    # display queued messages — record the outcome in the log.
                    pending.append((messages.SUCCESS, f"Successfully exported {processed_studies} studies ({total_files} files). {skipped_studies} studies were skipped."))
                    flush_to_log()

                    return response
            except Exception as e:
                logger.error(f"Error creating response: {str(e)}")
                flush_to_messages()
                messages.error(request, f"Error creating download response: {str(e)}")
                return

    except Exception as e:
        logger.error(f"Error creating zip file: {str(e)}")
        flush_to_messages()
        messages.error(request, f"Error creating zip file: {str(e)}")
        return
    finally:
        # Clean up the temporary directory
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Error cleaning up temporary directory: {str(e)}")





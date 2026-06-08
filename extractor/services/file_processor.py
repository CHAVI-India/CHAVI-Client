import os
import csv
from pathlib import Path
from typing import List, Dict, Any
from logging import getLogger
from django.conf import settings
from extractor.models import FileUpload, ProcessedText, FileTypeChoices, ProcessingStatusChoices

log = getLogger(__name__)


class FileProcessorService:
    """
    Service to process uploaded files and convert them to usable formats.
    - PDF -> Markdown (using markitdown)
    - CSV -> No processing (direct use)
    - Excel -> Multiple CSV files (one per sheet)
    """
    
    @classmethod
    def process_file(cls, file_upload: FileUpload, user=None) -> Dict[str, Any]:
        """
        Process an uploaded file based on its type.
        
        Returns:
            dict with keys: success, message, processed_files, errors
        """
        result = {
            'success': False,
            'message': '',
            'processed_files': [],
            'errors': []
        }
        
        try:
            file_upload.processing_status = ProcessingStatusChoices.PROCESSING
            file_upload.save()
            
            if file_upload.file_type == FileTypeChoices.PDF:
                result = cls._process_pdf(file_upload, user)
            elif file_upload.file_type == FileTypeChoices.CSV:
                result = cls._process_csv(file_upload, user)
            elif file_upload.file_type == FileTypeChoices.EXCEL:
                result = cls._process_excel(file_upload, user)
            else:
                result['errors'].append(f"Unsupported file type: {file_upload.file_type}")
                file_upload.processing_status = ProcessingStatusChoices.FAILED
                file_upload.save()
                return result
            
            if result['success']:
                file_upload.processing_status = ProcessingStatusChoices.COMPLETED
                log.info(f"Successfully processed file: {file_upload.file.name}")
            else:
                file_upload.processing_status = ProcessingStatusChoices.FAILED
                log.error(f"Failed to process file: {file_upload.file.name}")
            
            file_upload.save()
            
        except Exception as e:
            log.error(f"Error processing file {file_upload.id}: {e}")
            result['errors'].append(str(e))
            file_upload.processing_status = ProcessingStatusChoices.FAILED
            file_upload.save()
        
        return result
    
    @classmethod
    def _process_pdf(cls, file_upload: FileUpload, user=None) -> Dict[str, Any]:
        """
        Convert PDF to Markdown using markitdown.
        """
        result = {
            'success': False,
            'message': '',
            'processed_files': [],
            'errors': []
        }
        
        try:
            from markitdown import MarkItDown
            
            # Get the uploaded file path
            pdf_path = file_upload.file.path
            
            # Create output directory
            output_dir = Path(settings.MEDIA_ROOT) / 'processed' / 'pdf'
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate output filename
            base_name = Path(file_upload.file.name).stem
            output_filename = f"{base_name}_{file_upload.id}.md"
            output_path = output_dir / output_filename
            
            # Convert PDF to Markdown
            md = MarkItDown()
            markdown_result = md.convert(pdf_path)
            
            # Save markdown content
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(markdown_result.text_content)
            
            # Create ProcessedText record
            relative_path = os.path.relpath(output_path, settings.MEDIA_ROOT)
            processed_text = ProcessedText.objects.create(
                file_upload=file_upload,
                processed_file_path=relative_path,
                processed_by_user=user
            )
            
            result['success'] = True
            result['message'] = f"PDF converted to Markdown: {output_filename}"
            result['processed_files'].append({
                'id': processed_text.id,
                'path': relative_path,
                'type': 'markdown'
            })
            
            log.info(f"Converted PDF to Markdown: {pdf_path} -> {output_path}")
            
        except ImportError:
            result['errors'].append("markitdown library not installed. Install with: pip install markitdown")
            log.error("markitdown library not found")
        except Exception as e:
            result['errors'].append(f"PDF processing error: {str(e)}")
            log.error(f"PDF processing failed: {e}")
        
        return result
    
    @classmethod
    def _process_csv(cls, file_upload: FileUpload, user=None) -> Dict[str, Any]:
        """
        CSV files don't need processing - just create a ProcessedText record.
        """
        result = {
            'success': False,
            'message': '',
            'processed_files': [],
            'errors': []
        }
        
        try:
            # CSV files are used directly, just record the path
            relative_path = file_upload.file.name
            
            processed_text = ProcessedText.objects.create(
                file_upload=file_upload,
                processed_file_path=relative_path,
                processed_by_user=user
            )
            
            result['success'] = True
            result['message'] = "CSV file ready for processing (no conversion needed)"
            result['processed_files'].append({
                'id': processed_text.id,
                'path': relative_path,
                'type': 'csv'
            })
            
            log.info(f"CSV file registered: {file_upload.file.name}")
            
        except Exception as e:
            result['errors'].append(f"CSV processing error: {str(e)}")
            log.error(f"CSV processing failed: {e}")
        
        return result
    
    @classmethod
    def _process_excel(cls, file_upload: FileUpload, user=None) -> Dict[str, Any]:
        """
        Convert Excel file to multiple CSV files (one per sheet).
        """
        result = {
            'success': False,
            'message': '',
            'processed_files': [],
            'errors': []
        }
        
        try:
            import pandas as pd
            
            # Get the uploaded file path
            excel_path = file_upload.file.path
            
            # Create output directory
            output_dir = Path(settings.MEDIA_ROOT) / 'processed' / 'excel'
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Read all sheets
            excel_file = pd.ExcelFile(excel_path)
            base_name = Path(file_upload.file.name).stem
            
            sheets_processed = 0
            for sheet_name in excel_file.sheet_names:
                try:
                    # Read sheet
                    df = pd.read_excel(excel_file, sheet_name=sheet_name)
                    
                    # Generate output filename
                    safe_sheet_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in sheet_name)
                    output_filename = f"{base_name}_{file_upload.id}_{safe_sheet_name}.csv"
                    output_path = output_dir / output_filename
                    
                    # Save as CSV
                    df.to_csv(output_path, index=False, encoding='utf-8')
                    
                    # Create ProcessedText record
                    relative_path = os.path.relpath(output_path, settings.MEDIA_ROOT)
                    processed_text = ProcessedText.objects.create(
                        file_upload=file_upload,
                        processed_file_path=relative_path,
                        processed_by_user=user
                    )
                    
                    result['processed_files'].append({
                        'id': processed_text.id,
                        'path': relative_path,
                        'sheet_name': sheet_name,
                        'type': 'csv'
                    })
                    
                    sheets_processed += 1
                    log.info(f"Converted Excel sheet '{sheet_name}' to CSV: {output_path}")
                    
                except Exception as e:
                    result['errors'].append(f"Error processing sheet '{sheet_name}': {str(e)}")
                    log.error(f"Failed to process sheet '{sheet_name}': {e}")
            
            if sheets_processed > 0:
                result['success'] = True
                result['message'] = f"Excel file converted to {sheets_processed} CSV file(s)"
            else:
                result['errors'].append("No sheets were successfully processed")
            
        except ImportError:
            result['errors'].append("pandas library not installed. Install with: pip install pandas openpyxl")
            log.error("pandas library not found")
        except Exception as e:
            result['errors'].append(f"Excel processing error: {str(e)}")
            log.error(f"Excel processing failed: {e}")
        
        return result
    
    @classmethod
    def get_processed_content(cls, processed_text: ProcessedText) -> str:
        """
        Read and return the content of a processed file.
        """
        try:
            file_path = Path(settings.MEDIA_ROOT) / processed_text.processed_file_path
            
            if not file_path.exists():
                log.error(f"Processed file not found: {file_path}")
                return ""
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return content
            
        except Exception as e:
            log.error(f"Error reading processed file: {e}")
            return ""
    
    @classmethod
    def delete_processed_files(cls, file_upload: FileUpload) -> bool:
        """
        Delete all processed files associated with a FileUpload.
        """
        try:
            processed_texts = ProcessedText.objects.filter(file_upload=file_upload)
            
            for processed_text in processed_texts:
                file_path = Path(settings.MEDIA_ROOT) / processed_text.processed_file_path
                
                if file_path.exists():
                    file_path.unlink()
                    log.info(f"Deleted processed file: {file_path}")
                
                processed_text.delete()
            
            return True
            
        except Exception as e:
            log.error(f"Error deleting processed files: {e}")
            return False

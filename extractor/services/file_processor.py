import os
import chardet
import pandas as pd
import pdfplumber
from pathlib import Path
from typing import Dict, Any
from logging import getLogger
from django.conf import settings
from markitdown import MarkItDown
from extractor.models import FileUpload, ProcessedText, FileTypeChoices, ProcessingStatusChoices

log = getLogger(__name__)

MAX_UPLOAD_BYTES = getattr(settings, 'EXTRACTOR_MAX_UPLOAD_MB', 50) * 1024 * 1024


class FileProcessorService:
    """
    Service to process uploaded files and convert them to usable formats.
    - PDF -> Markdown (using markitdown)
    - CSV -> No processing (direct use)
    - Excel -> Multiple CSV files (one per sheet)
    """

    @classmethod
    def _next_version(cls, file_upload: FileUpload) -> int:
        """
        Next processing version for an upload; reprocessing writes to a new
        versioned directory instead of overwriting prior output.
        """
        latest = ProcessedText.objects.filter(
            file_upload=file_upload
        ).order_by('-version').values_list('version', flat=True).first()
        return (latest or 0) + 1

    @classmethod
    def _versioned_output_dir(cls, file_type_dir: str, file_upload: FileUpload, version: int) -> Path:
        output_dir = Path(settings.MEDIA_ROOT) / 'processed' / file_type_dir / str(file_upload.id) / f'v{version}'
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    @classmethod
    def process_file(cls, file_upload: FileUpload, user=None) -> Dict[str, Any]:
        """
        Process an uploaded file based on its type.

        Returns:
            dict with keys: success, message, processed_files, errors, warnings
        """
        result = {
            'success': False,
            'message': '',
            'processed_files': [],
            'errors': [],
            'warnings': []
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
                log.info(f"Successfully processed upload {file_upload.id}")
            else:
                file_upload.processing_status = ProcessingStatusChoices.FAILED
                log.error(f"Failed to process upload {file_upload.id}: {result['errors']}")

            file_upload.save()

        except Exception as e:
            log.error(f"Error processing upload {file_upload.id}: {e}")
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
            'errors': [],
            'warnings': []
        }

        try:
            pdf_path = file_upload.file.path
            version = cls._next_version(file_upload)

            output_dir = cls._versioned_output_dir('pdf', file_upload, version)
            output_filename = f"{file_upload.id}.md"
            output_path = output_dir / output_filename

            # Convert PDF to Markdown
            md = MarkItDown()
            markdown_result = md.convert(pdf_path)
            text_content = markdown_result.text_content or ''

            # Page coverage: image-only pages produce no text
            page_count = 0
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    page_count = len(pdf.pages)
            except Exception as e:
                log.warning(f"Could not count PDF pages for upload {file_upload.id}: {e}")

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text_content)

            # Usable-text gate: empty or near-empty conversion is flagged, not silently accepted
            warning = ''
            if len(text_content.strip()) == 0:
                warning = 'no_text'
            elif page_count > 0 and len(text_content.strip()) < page_count * 10:
                warning = 'low_text'

            relative_path = os.path.relpath(output_path, settings.MEDIA_ROOT)
            processed_text = ProcessedText.objects.create(
                file_upload=file_upload,
                processed_file_path=relative_path,
                processed_by_user=user,
                content_length=len(text_content.strip()),
                processing_warning=warning,
                version=version,
            )

            result['success'] = True
            result['message'] = f"PDF converted to Markdown ({page_count} page(s), {len(text_content.strip())} chars)"
            if warning:
                result['warnings'].append(
                    "PDF produced little or no text; it may be scanned/image-only and require OCR."
                )
            result['processed_files'].append({
                'id': processed_text.id,
                'path': relative_path,
                'type': 'markdown'
            })

            log.info(f"Converted PDF upload {file_upload.id} to markdown ({len(text_content)} chars, {page_count} pages)")

        except Exception as e:
            result['errors'].append(f"PDF processing error: {str(e)}")
            log.error(f"PDF processing failed for upload {file_upload.id}: {e}")

        return result

    @classmethod
    def ocr_pdf(cls, processed_text: ProcessedText, user=None, dpi: int = 300, lang: str = 'eng', max_pages: int = 50) -> ProcessedText:
        """
        OCR a scanned/image-only PDF into a new versioned ProcessedText row.

        Requires the system packages tesseract-ocr and poppler-utils, plus the
        pytesseract and pdf2image Python packages. Raises RuntimeError with a
        clear message when they are missing.
        """
        import shutil

        if processed_text.file_upload.file_type != FileTypeChoices.PDF:
            raise ValueError("OCR is only supported for PDF uploads")

        for binary, package in (('tesseract', 'tesseract-ocr'), ('pdftoppm', 'poppler-utils')):
            if not shutil.which(binary):
                raise RuntimeError(f"OCR requires {binary} (install: apt install {package})")

        try:
            from pdf2image import convert_from_path
            import pytesseract
        except ImportError as e:
            raise RuntimeError(f"OCR requires pdf2image and pytesseract: {e}") from e

        file_upload = processed_text.file_upload
        pdf_path = processed_text.resolve_path()
        if not pdf_path or not pdf_path.exists():
            # The flagged version usually points at the derived markdown, not the
            # PDF — fall back to the original upload file.
            pdf_path = Path(file_upload.file.path)

        version = cls._next_version(file_upload)
        output_dir = cls._versioned_output_dir('pdf', file_upload, version)
        output_path = output_dir / f"{file_upload.id}.ocr.md"

        page_texts = []
        pages = convert_from_path(str(pdf_path), dpi=dpi, last_page=max_pages)
        for page_image in pages:
            page_texts.append(pytesseract.image_to_string(page_image, lang=lang))

        text_content = "\n\n".join(t.strip() for t in page_texts if t.strip())

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(text_content)

        warning = '' if text_content.strip() else 'ocr_empty'
        relative_path = os.path.relpath(output_path, settings.MEDIA_ROOT)

        new_version = ProcessedText.objects.create(
            file_upload=file_upload,
            processed_file_path=relative_path,
            processed_by_user=user,
            source_sheet=processed_text.source_sheet,
            content_length=len(text_content.strip()),
            processing_warning=warning,
            version=version,
            ocr_applied=True,
        )

        log.info(
            f"OCR completed for upload {file_upload.id}: {len(pages)} page(s), "
            f"{len(text_content.strip())} chars -> v{version}"
        )
        return new_version

    @classmethod
    def _process_csv(cls, file_upload: FileUpload, user=None) -> Dict[str, Any]:
        """
        CSV files are used directly; verify readability/encoding and record the
        upload as a source alias (the processed row points at the original file).
        """
        result = {
            'success': False,
            'message': '',
            'processed_files': [],
            'errors': [],
            'warnings': []
        }

        try:
            raw = Path(file_upload.file.path).read_bytes()

            if len(raw) > MAX_UPLOAD_BYTES:
                result['errors'].append(
                    f"File exceeds maximum size of {MAX_UPLOAD_BYTES // (1024*1024)} MB"
                )
                return result

            # Encoding check: try UTF-8, fall back to detected encoding
            encoding = 'utf-8'
            warning = ''
            try:
                content = raw.decode('utf-8')
            except UnicodeDecodeError:
                detected = chardet.detect(raw)
                encoding = detected.get('encoding') or 'latin-1'
                content = raw.decode(encoding, errors='replace')
                warning = 'encoding_fallback'
                result['warnings'].append(
                    f"File is not UTF-8; read as {encoding}. Some characters may be altered."
                )

            version = cls._next_version(file_upload)
            relative_path = file_upload.file.name

            processed_text = ProcessedText.objects.create(
                file_upload=file_upload,
                processed_file_path=relative_path,
                processed_by_user=user,
                content_length=len(content.strip()),
                processing_warning=warning,
                version=version,
                is_source_alias=True,
            )

            result['success'] = True
            result['message'] = "CSV file ready for processing (no conversion needed)"
            result['processed_files'].append({
                'id': processed_text.id,
                'path': relative_path,
                'type': 'csv'
            })

            log.info(f"CSV upload {file_upload.id} registered ({len(content)} chars, {encoding})")

        except Exception as e:
            result['errors'].append(f"CSV processing error: {str(e)}")
            log.error(f"CSV processing failed for upload {file_upload.id}: {e}")

        return result

    @classmethod
    def _process_excel(cls, file_upload: FileUpload, user=None) -> Dict[str, Any]:
        """
        Convert Excel file to multiple CSV files (one per sheet).

        dtype=str + keep_default_na=False preserves literal cell text:
        identifiers like '000123' keep leading zeros and 'NA'/'NULL'/'None'
        remain literal strings instead of becoming empty cells.
        """
        result = {
            'success': False,
            'message': '',
            'processed_files': [],
            'errors': [],
            'warnings': []
        }

        try:
            excel_path = file_upload.file.path
            version = cls._next_version(file_upload)

            output_dir = cls._versioned_output_dir('excel', file_upload, version)

            excel_file = pd.ExcelFile(excel_path)
            total_sheets = len(excel_file.sheet_names)
            sheets_processed = 0
            failed_sheets = []

            for index, sheet_name in enumerate(excel_file.sheet_names):
                try:
                    df = pd.read_excel(
                        excel_file, sheet_name=sheet_name,
                        dtype=str, keep_default_na=False
                    )

                    # Unique output name: index guarantees uniqueness even when
                    # sanitized sheet names collide (e.g. 'Lab A' vs 'Lab_A')
                    safe_sheet_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in sheet_name)
                    output_filename = f"{file_upload.id}_{index}_{safe_sheet_name}.csv"
                    output_path = output_dir / output_filename

                    df.to_csv(output_path, index=False, encoding='utf-8')

                    relative_path = os.path.relpath(output_path, settings.MEDIA_ROOT)
                    content_length = len(df.to_csv(index=False).strip())
                    processed_text = ProcessedText.objects.create(
                        file_upload=file_upload,
                        processed_file_path=relative_path,
                        processed_by_user=user,
                        source_sheet=sheet_name,
                        content_length=content_length,
                        version=version,
                    )

                    result['processed_files'].append({
                        'id': processed_text.id,
                        'path': relative_path,
                        'sheet_name': sheet_name,
                        'type': 'csv'
                    })

                    sheets_processed += 1
                    log.info(f"Converted sheet '{sheet_name}' of upload {file_upload.id}")

                except Exception as e:
                    failed_sheets.append(sheet_name)
                    result['errors'].append(f"Error processing sheet '{sheet_name}': {str(e)}")
                    log.error(f"Failed to process sheet '{sheet_name}' of upload {file_upload.id}: {e}")

            # Honest outcome: success only when every sheet converted
            if sheets_processed == total_sheets:
                result['success'] = True
                result['message'] = f"Excel file converted to {sheets_processed} CSV file(s)"
            elif sheets_processed > 0:
                result['message'] = (
                    f"Partial conversion: {sheets_processed}/{total_sheets} sheet(s) processed; "
                    f"failed: {', '.join(failed_sheets)}"
                )
                result['warnings'].append("Workbook conversion incomplete; missing sheets were not extracted.")
            else:
                result['errors'].append("No sheets were successfully processed")

        except Exception as e:
            result['errors'].append(f"Excel processing error: {str(e)}")
            log.error(f"Excel processing failed for upload {file_upload.id}: {e}")

        return result

    @classmethod
    def get_processed_content(cls, processed_text: ProcessedText) -> str:
        """
        Read and return the content of a processed file.
        """
        try:
            file_path = processed_text.resolve_path()

            if not file_path or not file_path.exists():
                log.error(f"Processed file not found for ProcessedText {processed_text.id}")
                return ""

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            return content

        except Exception as e:
            log.error(f"Error reading processed file {processed_text.id}: {e}")
            return ""

    @classmethod
    def delete_processed_files(cls, file_upload: FileUpload) -> bool:
        """
        Delete all processed files associated with a FileUpload.
        The post_delete signal removes each derived file; source aliases are
        skipped by the signal since they point at the upload itself.
        """
        try:
            processed_texts = ProcessedText.objects.filter(file_upload=file_upload)

            for processed_text in processed_texts:
                processed_text.delete()

            return True

        except Exception as e:
            log.error(f"Error deleting processed files for upload {file_upload.id}: {e}")
            return False

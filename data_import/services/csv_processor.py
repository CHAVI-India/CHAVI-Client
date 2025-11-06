"""
Service for processing CSV files.
"""

import csv
import io
from django.core.files.uploadedfile import UploadedFile
from django.db.models.fields.files import FieldFile


class CSVProcessorService:
    """
    Handles CSV file processing and validation.
    """
    
    @staticmethod
    def read_csv_file(csv_file, encoding='utf-8'):
        """
        Read CSV file and return list of dictionaries.
        
        Args:
            csv_file: File object, FieldFile, or path
            encoding (str): File encoding
            
        Returns:
            tuple: (headers, rows, error)
        """
        try:
            # Handle different file types
            if isinstance(csv_file, (UploadedFile, FieldFile)):
                # For UploadedFile and FieldFile (from database)
                csv_file.seek(0)
                content = csv_file.read()
                if isinstance(content, bytes):
                    content = content.decode(encoding)
                csv_reader = csv.DictReader(io.StringIO(content))
                rows = list(csv_reader)
                headers = csv_reader.fieldnames
                return headers, rows, None
            elif hasattr(csv_file, 'read'):
                # Generic file-like object
                csv_file.seek(0)
                content = csv_file.read()
                if isinstance(content, bytes):
                    content = content.decode(encoding)
                csv_reader = csv.DictReader(io.StringIO(content))
                rows = list(csv_reader)
                headers = csv_reader.fieldnames
                return headers, rows, None
            else:
                # File path string
                with open(csv_file, 'r', encoding=encoding) as f:
                    csv_reader = csv.DictReader(f)
                    rows = list(csv_reader)
                    headers = csv_reader.fieldnames
                    return headers, rows, None
            
        except UnicodeDecodeError as e:
            return None, None, f"Encoding error: {str(e)}. Try a different encoding."
        except csv.Error as e:
            return None, None, f"CSV parsing error: {str(e)}"
        except Exception as e:
            return None, None, f"Error reading file: {str(e)}"
    
    @staticmethod
    def get_unique_values(rows, column_name, headers=None):
        """
        Get unique values from a specific column.
        
        Args:
            rows (list): List of row dictionaries or lists
            column_name (str): Column name
            headers (list): Optional list of headers if rows are lists
            
        Returns:
            list: Unique values (sorted)
        """
        if not rows:
            return []
        
        unique_values = set()
        
        # Check if rows are dictionaries or lists
        if isinstance(rows[0], dict):
            # Dictionary format
            if column_name not in rows[0]:
                return []
            
            for row in rows:
                value = str(row.get(column_name, '')).strip()
                if value:
                    unique_values.add(value)
        else:
            # List format - need headers
            if not headers or column_name not in headers:
                return []
            
            col_index = headers.index(column_name)
            for row in rows:
                if col_index < len(row):
                    value = str(row[col_index]).strip()
                    if value:
                        unique_values.add(value)
        
        return sorted(list(unique_values))
    
    @staticmethod
    def validate_csv_structure(headers, required_columns=None):
        """
        Validate CSV structure.
        
        Args:
            headers (list): CSV headers
            required_columns (list): Required column names
            
        Returns:
            tuple: (is_valid, error_message)
        """
        if not headers:
            return False, "CSV file has no headers"
        
        if required_columns:
            missing = set(required_columns) - set(headers)
            if missing:
                return False, f"Missing required columns: {', '.join(missing)}"
        
        # Check for duplicate headers
        if len(headers) != len(set(headers)):
            duplicates = [h for h in headers if headers.count(h) > 1]
            return False, f"Duplicate column names found: {', '.join(set(duplicates))}"
        
        return True, None
    
    @staticmethod
    def get_column_data_types(rows, column_name):
        """
        Analyze data types in a column.
        
        Args:
            rows (list): List of row dictionaries
            column_name (str): Column name
            
        Returns:
            dict: Data type analysis
        """
        if not rows or column_name not in rows[0]:
            return {'type': 'unknown', 'sample': None}
        
        values = [row.get(column_name, '').strip() for row in rows if row.get(column_name, '').strip()]
        
        if not values:
            return {'type': 'empty', 'sample': None}
        
        # Check if numeric
        numeric_count = 0
        for val in values:
            try:
                float(val)
                numeric_count += 1
            except ValueError:
                pass
        
        if numeric_count == len(values):
            return {'type': 'numeric', 'sample': values[0]}
        elif numeric_count > len(values) * 0.8:
            return {'type': 'mostly_numeric', 'sample': values[0]}
        
        # Check if date-like
        date_patterns = [r'\d{1,4}[-/\.]\d{1,2}[-/\.]\d{1,4}', r'\d{8}']
        import re
        date_count = sum(1 for val in values if any(re.match(p, val) for p in date_patterns))
        
        if date_count > len(values) * 0.8:
            return {'type': 'date', 'sample': values[0]}
        
        return {'type': 'text', 'sample': values[0]}
    
    @staticmethod
    def get_row_count(rows):
        """Get total row count."""
        return len(rows) if rows else 0
    
    @staticmethod
    def filter_rows_by_patient_ids(rows, patient_id_column, patient_ids):
        """
        Filter rows by patient IDs.
        
        Args:
            rows (list): List of row dictionaries
            patient_id_column (str): Column name for patient ID
            patient_ids (list): List of patient IDs to include
            
        Returns:
            list: Filtered rows
        """
        if not rows or not patient_id_column or not patient_ids:
            return rows
        
        return [row for row in rows if row.get(patient_id_column, '').strip() in patient_ids]
    
    @staticmethod
    def get_csv_preview(rows, max_rows=10):
        """
        Get preview of CSV data.
        
        Args:
            rows (list): List of row dictionaries
            max_rows (int): Maximum rows to return
            
        Returns:
            list: Preview rows
        """
        return rows[:max_rows] if rows else []

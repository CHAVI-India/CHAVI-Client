"""
Service for processing uploaded CSV and JSON files.
"""
import csv
import json
import chardet
from typing import Dict, List, Any, Optional, Tuple
from io import StringIO, TextIOWrapper
import logging

logger = logging.getLogger(__name__)


class FileProcessorService:
    """
    Service to parse and process uploaded CSV and JSON files.
    """
    
    def __init__(self, file_path: str, file_type: str):
        """
        Initialize the file processor.
        
        Args:
            file_path: Path to the uploaded file
            file_type: Type of file ('CSV' or 'JSON')
        """
        self.file_path = file_path
        self.file_type = file_type
        self.encoding = None
        self.delimiter = None
        
    def detect_encoding(self) -> str:
        """
        Detect the encoding of the file.
        
        Returns:
            Detected encoding (e.g., 'utf-8', 'latin-1')
        """
        if self.encoding:
            return self.encoding
            
        try:
            with open(self.file_path, 'rb') as f:
                raw_data = f.read(10000)  # Read first 10KB
                result = chardet.detect(raw_data)
                self.encoding = result['encoding'] or 'utf-8'
                logger.info(f"Detected encoding: {self.encoding} (confidence: {result['confidence']})")
                return self.encoding
        except Exception as e:
            logger.error(f"Error detecting encoding: {e}")
            self.encoding = 'utf-8'
            return self.encoding
    
    def detect_csv_delimiter(self) -> str:
        """
        Detect the delimiter used in CSV file.
        
        Returns:
            Detected delimiter (e.g., ',', ';', '\t')
        """
        if self.delimiter:
            return self.delimiter
            
        encoding = self.detect_encoding()
        
        try:
            with open(self.file_path, 'r', encoding=encoding) as f:
                # Read first few lines
                sample = f.read(4096)
                
                # Use csv.Sniffer to detect delimiter
                sniffer = csv.Sniffer()
                self.delimiter = sniffer.sniff(sample).delimiter
                logger.info(f"Detected delimiter: '{self.delimiter}'")
                return self.delimiter
                
        except Exception as e:
            logger.error(f"Error detecting delimiter: {e}")
            self.delimiter = ','
            return self.delimiter
    
    def parse_csv(self) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Parse CSV file and return headers and data rows.
        
        Returns:
            Tuple of (headers, data_rows)
            - headers: List of column names
            - data_rows: List of dictionaries (one per row)
        """
        encoding = self.detect_encoding()
        delimiter = self.detect_csv_delimiter()
        
        headers = []
        data_rows = []
        
        try:
            with open(self.file_path, 'r', encoding=encoding, newline='') as f:
                # Create CSV reader
                reader = csv.DictReader(f, delimiter=delimiter)
                
                # Get headers
                headers = reader.fieldnames
                
                if not headers:
                    raise ValueError("No headers found in CSV file")
                
                # Read all rows
                for row in reader:
                    # Clean up the row data
                    cleaned_row = {}
                    for key, value in row.items():
                        # Strip whitespace from keys and values
                        clean_key = key.strip() if key else key
                        clean_value = value.strip() if isinstance(value, str) else value
                        
                        # Convert empty strings to None
                        if clean_value == '':
                            clean_value = None
                            
                        cleaned_row[clean_key] = clean_value
                    
                    data_rows.append(cleaned_row)
                
                logger.info(f"Parsed CSV: {len(headers)} columns, {len(data_rows)} rows")
                
        except Exception as e:
            logger.error(f"Error parsing CSV file: {e}")
            raise ValueError(f"Failed to parse CSV file: {str(e)}")
        
        return headers, data_rows
    
    def parse_json(self) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Parse JSON file and return headers and data rows.
        Expected format: Array of objects or object with data array.
        
        Returns:
            Tuple of (headers, data_rows)
        """
        encoding = self.detect_encoding()
        
        headers = []
        data_rows = []
        
        try:
            with open(self.file_path, 'r', encoding=encoding) as f:
                data = json.load(f)
            
            # Handle different JSON structures
            if isinstance(data, list):
                # Array of objects: [{"field1": "value1", ...}, ...]
                data_rows = data
            elif isinstance(data, dict):
                # Object with data array: {"data": [...]}
                if 'data' in data:
                    data_rows = data['data']
                elif 'records' in data:
                    data_rows = data['records']
                elif 'rows' in data:
                    data_rows = data['rows']
                else:
                    # Treat the dict itself as a single row
                    data_rows = [data]
            else:
                raise ValueError("Unsupported JSON structure")
            
            if not data_rows:
                raise ValueError("No data found in JSON file")
            
            # Extract headers from first row
            if data_rows:
                headers = list(data_rows[0].keys())
            
            logger.info(f"Parsed JSON: {len(headers)} columns, {len(data_rows)} rows")
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON format: {e}")
            raise ValueError(f"Invalid JSON format: {str(e)}")
        except Exception as e:
            logger.error(f"Error parsing JSON file: {e}")
            raise ValueError(f"Failed to parse JSON file: {str(e)}")
        
        return headers, data_rows
    
    def parse(self) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Parse the file based on its type.
        
        Returns:
            Tuple of (headers, data_rows)
        """
        if self.file_type == 'CSV':
            return self.parse_csv()
        elif self.file_type == 'JSON':
            return self.parse_json()
        else:
            raise ValueError(f"Unsupported file type: {self.file_type}")
    
    def get_preview(self, num_rows: int = 10) -> Dict:
        """
        Get a preview of the file data.
        
        Args:
            num_rows: Number of rows to preview
            
        Returns:
            Dictionary with preview information
        """
        try:
            headers, data_rows = self.parse()
            
            preview_rows = data_rows[:num_rows]
            
            return {
                'headers': headers,
                'num_columns': len(headers),
                'total_rows': len(data_rows),
                'preview_rows': preview_rows,
                'encoding': self.encoding,
                'delimiter': self.delimiter if self.file_type == 'CSV' else None,
            }
            
        except Exception as e:
            logger.error(f"Error generating preview: {e}")
            raise
    
    def get_column_stats(self, headers: List[str], data_rows: List[Dict]) -> Dict[str, Dict]:
        """
        Get statistics for each column.
        
        Args:
            headers: List of column names
            data_rows: List of data rows
            
        Returns:
            Dictionary mapping column names to statistics
        """
        stats = {}
        
        for header in headers:
            column_values = [row.get(header) for row in data_rows]
            
            # Count non-empty values
            non_empty = [v for v in column_values if v is not None and v != '']
            
            # Try to detect data type
            data_type = self._infer_data_type(non_empty)
            
            # Get unique values (for small sets)
            unique_values = set(non_empty)
            
            stats[header] = {
                'total_values': len(column_values),
                'non_empty_values': len(non_empty),
                'empty_values': len(column_values) - len(non_empty),
                'unique_values': len(unique_values),
                'inferred_type': data_type,
                'sample_values': list(unique_values)[:5] if len(unique_values) <= 20 else non_empty[:5],
            }
        
        return stats
    
    def _infer_data_type(self, values: List[Any]) -> str:
        """
        Infer the data type of a column based on its values.
        
        Args:
            values: List of non-empty values
            
        Returns:
            Inferred data type
        """
        if not values:
            return 'Unknown'
        
        # Sample some values
        sample = values[:100]
        
        # Check for boolean
        bool_values = {'true', 'false', 't', 'f', 'yes', 'no', 'y', 'n', '0', '1', 'on', 'off'}
        if all(str(v).lower() in bool_values for v in sample):
            return 'Boolean'
        
        # Check for integer
        try:
            all_int = all(float(v).is_integer() for v in sample if v)
            if all_int:
                return 'Integer'
        except (ValueError, TypeError, AttributeError):
            pass
        
        # Check for float
        try:
            all(float(v) for v in sample if v)
            return 'Float'
        except (ValueError, TypeError):
            pass
        
        # Check for date
        date_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{2}/\d{2}/\d{4}',  # DD/MM/YYYY or MM/DD/YYYY
            r'\d{2}-\d{2}-\d{4}',  # DD-MM-YYYY
        ]
        
        import re
        for pattern in date_patterns:
            if all(re.match(pattern, str(v)) for v in sample if v):
                return 'Date'
        
        # Default to string
        return 'String'
    
    def validate_file_structure(self) -> Dict:
        """
        Validate the basic structure of the file.
        
        Returns:
            Dictionary with validation results
        """
        errors = []
        warnings = []
        
        try:
            headers, data_rows = self.parse()
            
            # Check for empty file
            if not data_rows:
                errors.append("File contains no data rows")
            
            # Check for duplicate headers
            if len(headers) != len(set(headers)):
                duplicates = [h for h in headers if headers.count(h) > 1]
                errors.append(f"Duplicate column names found: {', '.join(set(duplicates))}")
            
            # Check for empty headers
            if any(not h or h.strip() == '' for h in headers):
                errors.append("Some columns have empty names")
            
            # Check for very long headers
            long_headers = [h for h in headers if len(h) > 100]
            if long_headers:
                warnings.append(f"Some column names are very long (>100 chars): {len(long_headers)} columns")
            
            # Check for inconsistent row lengths (CSV only)
            if self.file_type == 'CSV':
                row_lengths = [len(row) for row in data_rows]
                if len(set(row_lengths)) > 1:
                    warnings.append(f"Rows have inconsistent number of columns: {set(row_lengths)}")
            
            return {
                'is_valid': len(errors) == 0,
                'errors': errors,
                'warnings': warnings,
                'num_headers': len(headers),
                'num_rows': len(data_rows),
            }
            
        except Exception as e:
            return {
                'is_valid': False,
                'errors': [str(e)],
                'warnings': [],
                'num_headers': 0,
                'num_rows': 0,
            }

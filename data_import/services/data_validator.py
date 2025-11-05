"""
Service for validating imported data against Django model constraints.
"""
from django.core.exceptions import ValidationError
from django.core import validators as django_validators
from decimal import Decimal, InvalidOperation
from datetime import datetime, date, time
from typing import Dict, List, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)


class DataValidatorService:
    """
    Service to validate imported data against CHAVI database field constraints.
    Works with both CSV and JSON imports.
    """
    
    def __init__(self):
        self.validation_errors = []
        
    def validate_data(
        self, 
        data_rows: List[Dict[str, Any]], 
        field_mappings: Dict[str, Dict]
    ) -> Dict:
        """
        Validate all data rows against field mappings.
        
        Args:
            data_rows: List of dictionaries (imported data rows)
            field_mappings: Dictionary mapping source field names to CHAVI field metadata
            
        Returns:
            Dictionary with validation results:
            {
                'is_valid': bool,
                'total_rows': int,
                'valid_rows': int,
                'invalid_rows': int,
                'errors_by_row': {row_num: [errors]},
                'errors_by_field': {source_field: count},
                'field_errors': {source_field: [row_nums]}
            }
        """
        self.validation_errors = []
        errors_by_row = {}
        errors_by_field = {}
        field_errors = {}
        
        for row_num, row_data in enumerate(data_rows, start=2):  # Start at 2 (row 1 is header)
            row_errors = []
            
            for source_field, chavi_field in field_mappings.items():
                # Get the value from the row
                value = row_data.get(source_field)
                
                # Validate the value
                field_errors_list = self.validate_field_value(
                    value, 
                    chavi_field, 
                    source_field,
                    row_num
                )
                
                if field_errors_list:
                    row_errors.extend(field_errors_list)
                    
                    # Track errors by field
                    if source_field not in errors_by_field:
                        errors_by_field[source_field] = 0
                        field_errors[source_field] = []
                    
                    errors_by_field[source_field] += len(field_errors_list)
                    field_errors[source_field].append(row_num)
            
            if row_errors:
                errors_by_row[row_num] = row_errors
        
        valid_rows = len(data_rows) - len(errors_by_row)
        
        return {
            'is_valid': len(errors_by_row) == 0,
            'total_rows': len(data_rows),
            'valid_rows': valid_rows,
            'invalid_rows': len(errors_by_row),
            'errors_by_row': errors_by_row,
            'errors_by_field': errors_by_field,
            'field_errors': field_errors,
        }
    
    def validate_field_value(
        self, 
        value: Any, 
        field_metadata: Dict, 
        source_field_name: str,
        row_num: int
    ) -> List[str]:
        """
        Validate a single field value against its metadata.
        
        Args:
            value: The value to validate
            field_metadata: CHAVI field metadata
            source_field_name: Name of the source field (for error messages)
            row_num: Row number (for error messages)
            
        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        
        # Check if value is empty
        is_empty = value is None or value == '' or (isinstance(value, str) and value.strip() == '')
        
        # Check required fields
        if field_metadata['is_required'] and is_empty:
            errors.append(
                f"Row {row_num}, Field '{source_field_name}': Required field is empty"
            )
            return errors  # No point in further validation
        
        # If field is empty and not required, skip further validation
        if is_empty:
            return errors
        
        # Validate data type
        data_type = field_metadata['data_type']
        
        try:
            if data_type == 'String':
                errors.extend(self._validate_string(value, field_metadata, source_field_name, row_num))
            elif data_type == 'Integer':
                errors.extend(self._validate_integer(value, field_metadata, source_field_name, row_num))
            elif data_type == 'Float':
                errors.extend(self._validate_float(value, field_metadata, source_field_name, row_num))
            elif data_type == 'Boolean':
                errors.extend(self._validate_boolean(value, field_metadata, source_field_name, row_num))
            elif data_type == 'Date':
                errors.extend(self._validate_date(value, field_metadata, source_field_name, row_num))
            elif data_type == 'DateTime':
                errors.extend(self._validate_datetime(value, field_metadata, source_field_name, row_num))
            elif data_type == 'Time':
                errors.extend(self._validate_time(value, field_metadata, source_field_name, row_num))
            elif data_type in ['ForeignKey', 'ManyToMany']:
                # These will be validated in the lookup matching step
                pass
            
        except Exception as e:
            errors.append(
                f"Row {row_num}, Field '{source_field_name}': Validation error - {str(e)}"
            )
        
        return errors
    
    def _validate_string(self, value: Any, field_metadata: Dict, source_field: str, row_num: int) -> List[str]:
        """Validate string field."""
        errors = []
        
        # Convert to string
        str_value = str(value).strip()
        
        # Check max length
        max_length = field_metadata.get('max_length')
        if max_length and len(str_value) > max_length:
            errors.append(
                f"Row {row_num}, Field '{source_field}': Value too long "
                f"({len(str_value)} chars, max {max_length})"
            )
        
        # Check choices
        if field_metadata.get('has_choices'):
            valid_values = [choice['value'] for choice in field_metadata['choices']]
            if str_value not in valid_values:
                errors.append(
                    f"Row {row_num}, Field '{source_field}': Invalid choice '{str_value}'. "
                    f"Valid options: {', '.join(valid_values)}"
                )
        
        # Check validators
        errors.extend(self._apply_validators(str_value, field_metadata, source_field, row_num))
        
        return errors
    
    def _validate_integer(self, value: Any, field_metadata: Dict, source_field: str, row_num: int) -> List[str]:
        """Validate integer field."""
        errors = []
        
        try:
            # Try to convert to integer
            if isinstance(value, str):
                value = value.strip()
            int_value = int(float(value))  # Handle "123.0" strings
            
            # Check validators (min/max)
            errors.extend(self._apply_validators(int_value, field_metadata, source_field, row_num))
            
        except (ValueError, TypeError):
            errors.append(
                f"Row {row_num}, Field '{source_field}': Invalid integer value '{value}'"
            )
        
        return errors
    
    def _validate_float(self, value: Any, field_metadata: Dict, source_field: str, row_num: int) -> List[str]:
        """Validate float/decimal field."""
        errors = []
        
        try:
            # Try to convert to Decimal for precision
            if isinstance(value, str):
                value = value.strip()
            decimal_value = Decimal(str(value))
            
            # Check max_digits and decimal_places
            max_digits = field_metadata.get('max_digits')
            decimal_places = field_metadata.get('decimal_places')
            
            if max_digits or decimal_places:
                # Convert to string to count digits
                str_value = str(decimal_value)
                if 'E' in str_value or 'e' in str_value:
                    # Scientific notation
                    decimal_value = Decimal(str_value)
                
                # Split into integer and decimal parts
                parts = str(abs(decimal_value)).split('.')
                integer_part = parts[0]
                decimal_part = parts[1] if len(parts) > 1 else ''
                
                total_digits = len(integer_part) + len(decimal_part)
                
                if max_digits and total_digits > max_digits:
                    errors.append(
                        f"Row {row_num}, Field '{source_field}': Too many digits "
                        f"({total_digits}, max {max_digits})"
                    )
                
                if decimal_places and len(decimal_part) > decimal_places:
                    errors.append(
                        f"Row {row_num}, Field '{source_field}': Too many decimal places "
                        f"({len(decimal_part)}, max {decimal_places})"
                    )
            
            # Check validators (min/max)
            errors.extend(self._apply_validators(float(decimal_value), field_metadata, source_field, row_num))
            
        except (InvalidOperation, ValueError, TypeError):
            errors.append(
                f"Row {row_num}, Field '{source_field}': Invalid decimal value '{value}'"
            )
        
        return errors
    
    def _validate_boolean(self, value: Any, field_metadata: Dict, source_field: str, row_num: int) -> List[str]:
        """Validate boolean field."""
        errors = []
        
        # Accept various boolean representations
        if isinstance(value, bool):
            return errors
        
        if isinstance(value, str):
            value = value.strip().lower()
            valid_true = ['true', 't', 'yes', 'y', '1', 'on']
            valid_false = ['false', 'f', 'no', 'n', '0', 'off', '']
            
            if value not in valid_true and value not in valid_false:
                errors.append(
                    f"Row {row_num}, Field '{source_field}': Invalid boolean value '{value}'. "
                    f"Use: true/false, yes/no, 1/0"
                )
        elif isinstance(value, (int, float)):
            if value not in [0, 1]:
                errors.append(
                    f"Row {row_num}, Field '{source_field}': Invalid boolean value '{value}'. "
                    f"Use: 0 or 1"
                )
        else:
            errors.append(
                f"Row {row_num}, Field '{source_field}': Invalid boolean value '{value}'"
            )
        
        return errors
    
    def _validate_date(self, value: Any, field_metadata: Dict, source_field: str, row_num: int) -> List[str]:
        """Validate date field."""
        errors = []
        
        if isinstance(value, date):
            return errors
        
        # Try common date formats
        date_formats = [
            '%Y-%m-%d',  # 2023-12-25
            '%d/%m/%Y',  # 25/12/2023
            '%m/%d/%Y',  # 12/25/2023
            '%d-%m-%Y',  # 25-12-2023
            '%Y/%m/%d',  # 2023/12/25
            '%d.%m.%Y',  # 25.12.2023
        ]
        
        str_value = str(value).strip()
        parsed = False
        
        for fmt in date_formats:
            try:
                datetime.strptime(str_value, fmt)
                parsed = True
                break
            except ValueError:
                continue
        
        if not parsed:
            errors.append(
                f"Row {row_num}, Field '{source_field}': Invalid date format '{value}'. "
                f"Use: YYYY-MM-DD or DD/MM/YYYY"
            )
        
        return errors
    
    def _validate_datetime(self, value: Any, field_metadata: Dict, source_field: str, row_num: int) -> List[str]:
        """Validate datetime field."""
        errors = []
        
        if isinstance(value, datetime):
            return errors
        
        # Try common datetime formats
        datetime_formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%d/%m/%Y %H:%M:%S',
            '%d/%m/%Y %H:%M',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
        ]
        
        str_value = str(value).strip()
        parsed = False
        
        for fmt in datetime_formats:
            try:
                datetime.strptime(str_value, fmt)
                parsed = True
                break
            except ValueError:
                continue
        
        if not parsed:
            errors.append(
                f"Row {row_num}, Field '{source_field}': Invalid datetime format '{value}'. "
                f"Use: YYYY-MM-DD HH:MM:SS"
            )
        
        return errors
    
    def _validate_time(self, value: Any, field_metadata: Dict, source_field: str, row_num: int) -> List[str]:
        """Validate time field."""
        errors = []
        
        if isinstance(value, time):
            return errors
        
        # Try common time formats
        time_formats = [
            '%H:%M:%S',
            '%H:%M',
            '%I:%M:%S %p',
            '%I:%M %p',
        ]
        
        str_value = str(value).strip()
        parsed = False
        
        for fmt in time_formats:
            try:
                datetime.strptime(str_value, fmt)
                parsed = True
                break
            except ValueError:
                continue
        
        if not parsed:
            errors.append(
                f"Row {row_num}, Field '{source_field}': Invalid time format '{value}'. "
                f"Use: HH:MM:SS or HH:MM"
            )
        
        return errors
    
    def _apply_validators(self, value: Any, field_metadata: Dict, source_field: str, row_num: int) -> List[str]:
        """Apply Django validators to a value."""
        errors = []
        
        validators = field_metadata.get('validators', [])
        
        for validator_info in validators:
            validator_type = validator_info['type']
            
            try:
                if validator_type == 'MinValueValidator':
                    min_val = Decimal(validator_info['min_value'])
                    if Decimal(str(value)) < min_val:
                        errors.append(
                            f"Row {row_num}, Field '{source_field}': Value {value} is less than minimum {min_val}"
                        )
                
                elif validator_type == 'MaxValueValidator':
                    max_val = Decimal(validator_info['max_value'])
                    if Decimal(str(value)) > max_val:
                        errors.append(
                            f"Row {row_num}, Field '{source_field}': Value {value} exceeds maximum {max_val}"
                        )
                
                elif validator_type == 'MinLengthValidator':
                    min_len = validator_info['min_length']
                    if len(str(value)) < min_len:
                        errors.append(
                            f"Row {row_num}, Field '{source_field}': Value too short (min length {min_len})"
                        )
                
                elif validator_type == 'MaxLengthValidator':
                    max_len = validator_info['max_length']
                    if len(str(value)) > max_len:
                        errors.append(
                            f"Row {row_num}, Field '{source_field}': Value too long (max length {max_len})"
                        )
                
                elif validator_type == 'RegexValidator':
                    pattern = validator_info['regex']
                    if not re.match(pattern, str(value)):
                        message = validator_info.get('message', f'Value does not match required pattern')
                        errors.append(
                            f"Row {row_num}, Field '{source_field}': {message}"
                        )
                
                elif validator_type == 'EmailValidator':
                    email_validator = django_validators.EmailValidator()
                    try:
                        email_validator(str(value))
                    except ValidationError:
                        errors.append(
                            f"Row {row_num}, Field '{source_field}': Invalid email address '{value}'"
                        )
                
                elif validator_type == 'URLValidator':
                    url_validator = django_validators.URLValidator()
                    try:
                        url_validator(str(value))
                    except ValidationError:
                        errors.append(
                            f"Row {row_num}, Field '{source_field}': Invalid URL '{value}'"
                        )
                
                # Custom validators from client_app.models
                elif validator_type == 'percentage_validator':
                    # Validates 0-100 range
                    try:
                        decimal_val = Decimal(str(value))
                        if decimal_val < Decimal('0.0') or decimal_val > Decimal('100.0'):
                            errors.append(
                                f"Row {row_num}, Field '{source_field}': Percentage must be between 0 and 100 (got {value})"
                            )
                    except (ValueError, InvalidOperation):
                        errors.append(
                            f"Row {row_num}, Field '{source_field}': Invalid percentage value '{value}'"
                        )
                
                elif validator_type == 'positive_decimal_validator':
                    # Validates >= 0
                    try:
                        decimal_val = Decimal(str(value))
                        if decimal_val < Decimal('0.0'):
                            errors.append(
                                f"Row {row_num}, Field '{source_field}': Value must be positive or zero (got {value})"
                            )
                    except (ValueError, InvalidOperation):
                        errors.append(
                            f"Row {row_num}, Field '{source_field}': Invalid decimal value '{value}'"
                        )
                
                elif validator_type == 'allred_score_validator':
                    # Validates 0-8 range
                    try:
                        int_val = int(value)
                        if int_val < 0 or int_val > 8:
                            errors.append(
                                f"Row {row_num}, Field '{source_field}': Allred score must be between 0 and 8 (got {value})"
                            )
                    except (ValueError, TypeError):
                        errors.append(
                            f"Row {row_num}, Field '{source_field}': Invalid Allred score value '{value}'"
                        )
            
            except Exception as e:
                logger.error(f"Error applying validator {validator_type}: {e}")
                continue
        
        return errors
    
    def generate_error_report(self, validation_result: Dict) -> str:
        """
        Generate a human-readable error report.
        
        Args:
            validation_result: Result from validate_data()
            
        Returns:
            Formatted error report string
        """
        report = []
        report.append("=" * 80)
        report.append("DATA VALIDATION REPORT")
        report.append("=" * 80)
        report.append(f"Total Rows: {validation_result['total_rows']}")
        report.append(f"Valid Rows: {validation_result['valid_rows']}")
        report.append(f"Invalid Rows: {validation_result['invalid_rows']}")
        report.append("")
        
        if validation_result['errors_by_field']:
            report.append("ERRORS BY FIELD:")
            report.append("-" * 80)
            for field, count in sorted(
                validation_result['errors_by_field'].items(), 
                key=lambda x: x[1], 
                reverse=True
            ):
                report.append(f"  {field}: {count} errors")
            report.append("")
        
        if validation_result['errors_by_row']:
            report.append("ERRORS BY ROW:")
            report.append("-" * 80)
            for row_num in sorted(validation_result['errors_by_row'].keys()):
                errors = validation_result['errors_by_row'][row_num]
                report.append(f"\nRow {row_num}:")
                for error in errors:
                    report.append(f"  - {error}")
        
        report.append("")
        report.append("=" * 80)
        
        return "\n".join(report)

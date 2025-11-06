"""
Service for parsing dates with various formats and delimiters.
"""

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import re


class DateFormatParser:
    """
    Parses dates with various formats and delimiters.
    """
    
    FORMAT_MAPPINGS = {
        'iso_8601': ['%Y-%m-%d', '%Y/%m/%d'],
        'ddmmyyyy': ['%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y', '%d %m %Y', '%d%m%Y'],
        'mmddyyyy': ['%m-%d-%Y', '%m/%d/%Y', '%m.%d.%Y', '%m %d %Y', '%m%d%Y'],
        'yyyymmdd': ['%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y %m %d', '%Y%m%d'],
        'ddmmyy': ['%d-%m-%y', '%d/%m/%y', '%d.%m.%y', '%d %m %y', '%d%m%y'],
        'mmddyy': ['%m-%d-%y', '%m/%d/%y', '%m.%d.%y', '%m %d %y', '%m%d%y'],
        'yymmdd': ['%y-%m-%d', '%y/%m/%d', '%y.%m.%d', '%y %m %d', '%y%m%d'],
        'dmy': ['%d-%m-%y', '%d/%m/%y', '%d.%m.%y', '%d %m %y', '%d%m%y'],
        'mdy': ['%m-%d-%y', '%m/%d/%y', '%m.%d.%y', '%m %d %y', '%m%d%y'],
        'ymd': ['%y-%m-%d', '%y/%m/%d', '%y.%m.%d', '%y %m %d', '%y%m%d'],
    }
    
    @staticmethod
    def parse_date(date_string, format_choice):
        """
        Attempts to parse date string with specified format.
        Tries multiple delimiter variations.
        
        Args:
            date_string (str): Date string to parse
            format_choice (str): Format choice from DateFormat model
            
        Returns:
            date: Parsed date object
            
        Raises:
            ValueError: If date cannot be parsed
        """
        if not date_string or date_string == '':
            return None
        
        # Convert to string and strip whitespace
        date_string = str(date_string).strip()
        
        if not date_string:
            return None
        
        formats = DateFormatParser.FORMAT_MAPPINGS.get(format_choice, [])
        if isinstance(formats, str):
            formats = [formats]
        
        # Try each format variation
        for fmt in formats:
            try:
                return datetime.strptime(date_string, fmt).date()
            except ValueError:
                continue
        
        # If no format worked, raise error
        raise ValueError(
            f"Could not parse '{date_string}' with format '{format_choice}'. "
            f"Expected formats: {formats}"
        )
    
    @staticmethod
    def calculate_date_from_duration(reference_date, duration_value, duration_unit, reference_type='start'):
        """
        Calculate a date by adding/subtracting duration from reference date.
        
        Args:
            reference_date (date): Reference date
            duration_value (int/float): Duration value
            duration_unit (str): Unit (year, month, week, day, etc.)
            reference_type (str): 'start' or 'end'
            
        Returns:
            date: Calculated date
        """
        if not reference_date or not duration_value:
            return None
        
        try:
            duration_value = float(duration_value)
        except (ValueError, TypeError):
            return None
        
        # Convert duration to timedelta or relativedelta
        if duration_unit == 'year':
            delta = relativedelta(years=int(duration_value))
        elif duration_unit == 'month':
            delta = relativedelta(months=int(duration_value))
        elif duration_unit == 'fortnight':
            delta = timedelta(days=duration_value * 14)
        elif duration_unit == 'week':
            delta = timedelta(weeks=duration_value)
        elif duration_unit == 'day':
            delta = timedelta(days=duration_value)
        elif duration_unit == 'hour':
            delta = timedelta(hours=duration_value)
        elif duration_unit == 'minute':
            delta = timedelta(minutes=duration_value)
        elif duration_unit == 'second':
            delta = timedelta(seconds=duration_value)
        elif duration_unit == 'millisecond':
            delta = timedelta(milliseconds=duration_value)
        elif duration_unit == 'microsecond':
            delta = timedelta(microseconds=duration_value)
        elif duration_unit == 'nanosecond':
            delta = timedelta(microseconds=duration_value / 1000)
        else:
            return None
        
        # Apply delta based on reference type
        if reference_type == 'start':
            # Reference is start date, add duration to get end date
            return reference_date + delta
        else:
            # Reference is end date, subtract duration to get start date
            return reference_date - delta
    
    @staticmethod
    def validate_date_format(date_string, format_choice):
        """
        Validate if a date string matches the expected format.
        
        Args:
            date_string (str): Date string to validate
            format_choice (str): Format choice
            
        Returns:
            bool: True if valid, False otherwise
        """
        try:
            DateFormatParser.parse_date(date_string, format_choice)
            return True
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def get_format_example(format_choice):
        """
        Get example date string for a given format.
        
        Args:
            format_choice (str): Format choice
            
        Returns:
            str: Example date string
        """
        examples = {
            'iso_8601': '2024-01-15',
            'ddmmyyyy': '15/01/2024 or 15-01-2024',
            'mmddyyyy': '01/15/2024 or 01-15-2024',
            'yyyymmdd': '2024/01/15 or 2024-01-15',
            'ddmmyy': '15/01/24 or 15-01-24',
            'mmddyy': '01/15/24 or 01-15-24',
            'yymmdd': '24/01/15 or 24-01-15',
            'dmy': '15/01/24',
            'mdy': '01/15/24',
            'ymd': '24/01/15',
        }
        return examples.get(format_choice, 'Unknown format')

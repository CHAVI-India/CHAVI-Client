"""
Service for fuzzy matching imported data field names to CHAVI database fields.
Uses RapidFuzz for efficient string matching.
"""
from rapidfuzz import fuzz, process
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class FuzzyMatcherService:
    """
    Service to match imported data field names against CHAVI database fields
    using fuzzy string matching. Works with both CSV and JSON imports.
    """
    
    # Matching thresholds
    AUTO_MATCH_THRESHOLD = 90  # Auto-select if score > 90
    STRONG_MATCH_THRESHOLD = 70  # Show as suggestions if score 70-90
    
    def __init__(self, field_introspection_service):
        """
        Initialize the fuzzy matcher.
        
        Args:
            field_introspection_service: Instance of FieldIntrospectionService
        """
        self.field_service = field_introspection_service
        self.chavi_fields = field_introspection_service.get_all_fields()
        
    def match_source_fields(self, source_field_names: List[str]) -> Dict[str, Dict]:
        """
        Match all imported data field names against CHAVI fields.
        
        Args:
            source_field_names: List of field names from imported file (CSV/JSON)
            
        Returns:
            Dictionary mapping source field names to match results:
            {
                'source_field_name': {
                    'match_type': 'auto' | 'suggestions' | 'manual',
                    'auto_match': {...} or None,
                    'suggestions': [...],
                    'all_fields': [...]  # For manual selection
                }
            }
        """
        results = {}
        
        for source_field in source_field_names:
            match_result = self.match_single_field(source_field)
            results[source_field] = match_result
            
        return results
    
    def match_single_field(self, source_field_name: str) -> Dict:
        """
        Match a single imported data field against CHAVI fields.
        
        Args:
            source_field_name: Name of the field from imported file (CSV/JSON)
            
        Returns:
            Dictionary with match results
        """
        # Get all potential matches with scores
        matches = self._find_matches(source_field_name)
        
        # Categorize matches
        auto_match = None
        suggestions = []
        
        for match in matches:
            score = match['score']
            
            if score >= self.AUTO_MATCH_THRESHOLD:
                # Auto match - take the best one
                if auto_match is None:
                    auto_match = match
            elif score >= self.STRONG_MATCH_THRESHOLD:
                # Strong suggestion
                suggestions.append(match)
        
        # Determine match type
        if auto_match:
            match_type = 'auto'
        elif suggestions:
            match_type = 'suggestions'
        else:
            match_type = 'manual'
        
        return {
            'match_type': match_type,
            'auto_match': auto_match,
            'suggestions': suggestions[:3],  # Top 3 suggestions
            'all_fields': self.chavi_fields,  # For manual selection dropdown
        }
    
    def _find_matches(self, source_field_name: str) -> List[Dict]:
        """
        Find all potential matches for an imported data field.
        
        Args:
            source_field_name: Name of the field from imported file (CSV/JSON)
            
        Returns:
            List of matches sorted by score (highest first)
        """
        matches = []
        
        for chavi_field in self.chavi_fields:
            # Create search strings from field metadata
            search_strings = self._create_search_strings(chavi_field)
            
            # Calculate match scores for each search string
            scores = []
            for search_str in search_strings:
                # Use token_set_ratio for better matching of multi-word fields
                score = fuzz.token_set_ratio(
                    source_field_name.lower(),
                    search_str.lower()
                )
                scores.append(score)
            
            # Take the best score
            best_score = max(scores) if scores else 0
            
            if best_score > 0:
                match_info = {
                    'score': best_score,
                    'field': chavi_field,
                    'model_name': chavi_field['model_name'],
                    'table_name': chavi_field['table_name'],
                    'field_name': chavi_field['field_name'],
                    'verbose_name': chavi_field['verbose_name'],
                    'help_text': chavi_field['help_text'],
                    'data_type': chavi_field['data_type'],
                    'is_required': chavi_field['is_required'],
                    'is_foreign_key': chavi_field['is_foreign_key'],
                    'is_many_to_many': chavi_field['is_many_to_many'],
                    'is_lookup': chavi_field['is_lookup'],
                }
                matches.append(match_info)
        
        # Sort by score (highest first)
        matches.sort(key=lambda x: x['score'], reverse=True)
        
        return matches
    
    def _create_search_strings(self, field: Dict) -> List[str]:
        """
        Create search strings from field metadata for matching.
        
        Args:
            field: Field metadata dictionary
            
        Returns:
            List of search strings
        """
        search_strings = []
        
        # Add field name
        if field['field_name']:
            search_strings.append(field['field_name'])
            # Also add with underscores replaced by spaces
            search_strings.append(field['field_name'].replace('_', ' '))
        
        # Add verbose name
        if field['verbose_name']:
            search_strings.append(field['verbose_name'])
        
        # Add help text (first 100 chars to avoid too long strings)
        if field['help_text']:
            help_text = field['help_text'][:100]
            search_strings.append(help_text)
        
        # Add combined string for better matching
        combined = f"{field['field_name']} {field['verbose_name']} {field['help_text'][:50]}"
        search_strings.append(combined)
        
        return search_strings
    
    def get_field_by_identifier(self, model_name: str, field_name: str) -> Dict:
        """
        Get a specific CHAVI field by model and field name.
        
        Args:
            model_name: Name of the model
            field_name: Name of the field
            
        Returns:
            Field metadata dictionary or None
        """
        for field in self.chavi_fields:
            if field['model_name'] == model_name and field['field_name'] == field_name:
                return field
        return None
    
    def search_fields(self, query: str, limit: int = 20) -> List[Dict]:
        """
        Search for fields matching a query string.
        Useful for Select2 autocomplete.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching fields with scores
        """
        if not query:
            return self.chavi_fields[:limit]
        
        matches = self._find_matches(query)
        return matches[:limit]
    
    def get_fields_grouped_by_model(self) -> Dict[str, List[Dict]]:
        """
        Get all fields grouped by model.
        Useful for Select2 optgroups.
        
        Returns:
            Dictionary mapping model names to field lists
        """
        grouped = {}
        
        for field in self.chavi_fields:
            model_name = field['model_name']
            if model_name not in grouped:
                grouped[model_name] = []
            grouped[model_name].append(field)
        
        return grouped
    
    def validate_match(self, source_field_name: str, chavi_field: Dict) -> Dict:
        """
        Validate if a manual match is reasonable.
        
        Args:
            source_field_name: Imported data field name
            chavi_field: CHAVI field metadata
            
        Returns:
            Dictionary with validation result and warnings
        """
        warnings = []
        
        # Calculate similarity score
        search_strings = self._create_search_strings(chavi_field)
        scores = [
            fuzz.token_set_ratio(source_field_name.lower(), s.lower())
            for s in search_strings
        ]
        best_score = max(scores) if scores else 0
        
        # Check for very low similarity
        if best_score < 30:
            warnings.append(
                f"Very low similarity ({best_score}%) between '{source_field_name}' "
                f"and '{chavi_field['field_name']}'. Please verify this is correct."
            )
        
        # Check for data type mismatches (if we can infer from field name)
        source_field_lower = source_field_name.lower()
        chavi_type = chavi_field['data_type']
        
        if 'date' in source_field_lower and chavi_type not in ['Date', 'DateTime']:
            warnings.append(
                f"Source field '{source_field_name}' suggests a date, but CHAVI field "
                f"'{chavi_field['field_name']}' is type '{chavi_type}'."
            )
        
        if any(word in source_field_lower for word in ['count', 'number', 'age']) and chavi_type not in ['Integer', 'Float']:
            warnings.append(
                f"Source field '{source_field_name}' suggests a numeric value, but CHAVI field "
                f"'{chavi_field['field_name']}' is type '{chavi_type}'."
            )
        
        return {
            'is_valid': True,  # We allow any manual match
            'similarity_score': best_score,
            'warnings': warnings,
        }

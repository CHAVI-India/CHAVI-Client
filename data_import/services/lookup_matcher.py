"""
Service for matching imported data string values to lookup table entries.
"""
from rapidfuzz import fuzz, process
from django.apps import apps
from typing import Dict, List, Set, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class LookupMatcherService:
    """
    Service to match string values from imported data to lookup table entries.
    Works with both CSV and JSON imports.
    """
    
    # Matching threshold for auto-match
    AUTO_MATCH_THRESHOLD = 90
    STRONG_MATCH_THRESHOLD = 70
    
    def __init__(self, field_introspection_service):
        """
        Initialize the lookup matcher.
        
        Args:
            field_introspection_service: Instance of FieldIntrospectionService
        """
        self.field_service = field_introspection_service
        self.lookup_cache = {}
        
    def identify_lookup_fields(self, field_mappings: Dict[str, Dict]) -> List[Dict]:
        """
        Identify which mapped fields reference lookup tables.
        
        Args:
            field_mappings: Dictionary mapping source field names to CHAVI field metadata
            
        Returns:
            List of lookup field information
        """
        lookup_fields = []
        
        print(f"[DEBUG LOOKUP MATCHER] Checking {len(field_mappings)} field mappings")
        
        for source_field, chavi_field in field_mappings.items():
            is_lookup = chavi_field.get('is_lookup', False)
            is_fk = chavi_field.get('is_foreign_key', False)
            is_m2m = chavi_field.get('is_many_to_many', False)
            
            print(f"[DEBUG LOOKUP MATCHER] Field: {source_field} -> {chavi_field.get('field_name')}")
            print(f"  - is_lookup: {is_lookup}, is_fk: {is_fk}, is_m2m: {is_m2m}")
            print(f"  - related_app: {chavi_field.get('related_app')}, lookup_model: {chavi_field.get('lookup_model')}")
            
            if chavi_field.get('is_lookup'):
                print(f"  ✓ IDENTIFIED AS LOOKUP FIELD")
                lookup_fields.append({
                    'source_field': source_field,
                    'chavi_field': chavi_field['field_name'],
                    'model_name': chavi_field['model_name'],
                    'lookup_model': chavi_field['lookup_model'],
                    'lookup_table': chavi_field['related_table'],
                })
        
        print(f"[DEBUG LOOKUP MATCHER] Found {len(lookup_fields)} lookup fields")
        return lookup_fields
    
    def extract_unique_values(
        self, 
        data_rows: List[Dict], 
        source_field_name: str
    ) -> Set[str]:
        """
        Extract unique non-empty values from an imported data field.
        
        Args:
            data_rows: List of data rows from imported file
            source_field_name: Name of the source field
            
        Returns:
            Set of unique string values
        """
        unique_values = set()
        
        for row in data_rows:
            value = row.get(source_field_name)
            if value is not None and str(value).strip():
                unique_values.add(str(value).strip())
        
        return unique_values
    
    def get_lookup_table_values(self, lookup_model_name: str) -> List[Dict]:
        """
        Get all values from a lookup table with caching.
        
        Args:
            lookup_model_name: Name of the lookup model
            
        Returns:
            List of lookup value dictionaries
        """
        # Check cache first
        if lookup_model_name in self.lookup_cache:
            return self.lookup_cache[lookup_model_name]
        
        # Get from field service
        values = self.field_service.get_lookup_table_values(lookup_model_name)
        
        # Cache the results
        self.lookup_cache[lookup_model_name] = values
        
        return values
    
    def match_lookup_values(
        self, 
        source_values: Set[str], 
        lookup_model_name: str
    ) -> Dict[str, Dict]:
        """
        Match imported data values to lookup table entries.
        
        Args:
            source_values: Set of unique values from imported data
            lookup_model_name: Name of the lookup model
            
        Returns:
            Dictionary mapping source values to match results:
            {
                'source_value': {
                    'match_type': 'auto' | 'suggestions' | 'manual',
                    'auto_match': {...} or None,
                    'suggestions': [...],
                    'all_lookup_values': [...]
                }
            }
        """
        # Get lookup table values
        lookup_values = self.get_lookup_table_values(lookup_model_name)
        
        print(f"[DEBUG LOOKUP MATCHER] Fetched {len(lookup_values)} values from {lookup_model_name}")
        if lookup_values:
            print(f"[DEBUG LOOKUP MATCHER] Sample values: {lookup_values[:3]}")
        
        if not lookup_values:
            logger.warning(f"No values found in lookup table: {lookup_model_name}")
            return {}
        
        results = {}
        
        for source_value in source_values:
            match_result = self._match_single_value(source_value, lookup_values)
            results[source_value] = match_result
        
        return results
    
    def _match_single_value(
        self, 
        source_value: str, 
        lookup_values: List[Dict]
    ) -> Dict:
        """
        Match a single imported data value against lookup table entries.
        
        Args:
            source_value: Value from imported data
            lookup_values: List of lookup table entries
            
        Returns:
            Dictionary with match results
        """
        matches = []
        
        for lookup_entry in lookup_values:
            # Create search strings from lookup entry
            search_strings = self._create_lookup_search_strings(lookup_entry)
            
            # Calculate match scores
            scores = []
            for search_str in search_strings:
                score = fuzz.token_set_ratio(
                    source_value.lower(),
                    search_str.lower()
                )
                scores.append(score)
            
            best_score = max(scores) if scores else 0
            
            if best_score > 0:
                matches.append({
                    'score': best_score,
                    'lookup_entry': lookup_entry,
                    'pk': lookup_entry['pk'],
                    'str': lookup_entry.get('str', ''),
                })
        
        # Sort by score
        matches.sort(key=lambda x: x['score'], reverse=True)
        
        # Categorize matches
        auto_match = None
        suggestions = []
        
        for match in matches:
            score = match['score']
            
            if score >= self.AUTO_MATCH_THRESHOLD:
                if auto_match is None:
                    auto_match = match
            elif score >= self.STRONG_MATCH_THRESHOLD:
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
            'suggestions': suggestions[:5],  # Top 5 suggestions
            'all_lookup_values': lookup_values,
        }
    
    def _create_lookup_search_strings(self, lookup_entry: Dict) -> List[str]:
        """
        Create search strings from a lookup table entry.
        
        Args:
            lookup_entry: Lookup table entry dictionary
            
        Returns:
            List of search strings
        """
        search_strings = []
        
        # Add all available fields
        for field in ['code', 'name', 'description', 'value', 'str']:
            if field in lookup_entry and lookup_entry[field]:
                search_strings.append(str(lookup_entry[field]))
        
        # Add combined string
        combined = ' '.join([
            str(lookup_entry.get(f, ''))
            for f in ['code', 'name', 'description']
            if lookup_entry.get(f)
        ])
        if combined:
            search_strings.append(combined)
        
        return search_strings
    
    def process_all_lookup_fields(
        self, 
        data_rows: List[Dict], 
        field_mappings: Dict[str, Dict]
    ) -> Dict[str, Dict]:
        """
        Process all lookup fields and generate match results.
        
        Args:
            data_rows: List of data rows from imported file
            field_mappings: Dictionary mapping source field names to CHAVI field metadata
            
        Returns:
            Dictionary mapping source field names to their lookup match results
        """
        lookup_fields = self.identify_lookup_fields(field_mappings)
        
        results = {}
        
        for lookup_field in lookup_fields:
            source_field = lookup_field['source_field']
            lookup_model = lookup_field['lookup_model']
            
            # Extract unique values from imported data
            unique_values = self.extract_unique_values(data_rows, source_field)
            
            # Match against lookup table
            match_results = self.match_lookup_values(unique_values, lookup_model)
            
            results[source_field] = {
                'lookup_field_info': lookup_field,
                'unique_values': list(unique_values),
                'match_results': match_results,
                'total_values': len(unique_values),
                'auto_matched': sum(1 for r in match_results.values() if r['match_type'] == 'auto'),
                'needs_review': sum(1 for r in match_results.values() if r['match_type'] in ['suggestions', 'manual']),
            }
        
        return results
    
    def create_lookup_mappings(
        self, 
        user_selections: Dict[str, Dict[str, str]]
    ) -> Dict[str, Dict[str, str]]:
        """
        Create final lookup mappings from user selections.
        
        Args:
            user_selections: Dictionary mapping source fields to their value mappings
                {
                    'source_field': {
                        'source_value': 'lookup_pk',
                        ...
                    }
                }
            
        Returns:
            Validated lookup mappings
        """
        final_mappings = {}
        
        for source_field, value_mappings in user_selections.items():
            final_mappings[source_field] = {}
            
            for source_value, lookup_pk in value_mappings.items():
                if lookup_pk and lookup_pk != '':
                    final_mappings[source_field][source_value] = lookup_pk
        
        return final_mappings
    
    def validate_lookup_mappings(
        self, 
        data_rows: List[Dict], 
        field_mappings: Dict[str, Dict],
        lookup_mappings: Dict[str, Dict[str, str]]
    ) -> Dict:
        """
        Validate that all lookup values in the data have mappings.
        
        Args:
            data_rows: List of data rows from imported file
            field_mappings: Field mappings
            lookup_mappings: Lookup value mappings
            
        Returns:
            Validation result dictionary
        """
        unmapped_values = {}
        total_unmapped = 0
        
        lookup_fields = self.identify_lookup_fields(field_mappings)
        
        for lookup_field in lookup_fields:
            source_field = lookup_field['source_field']
            
            # Get mappings for this field
            field_mappings_dict = lookup_mappings.get(source_field, {})
            
            # Check each row
            unmapped_in_field = set()
            
            for row in data_rows:
                value = row.get(source_field)
                if value is not None and str(value).strip():
                    str_value = str(value).strip()
                    if str_value not in field_mappings_dict:
                        unmapped_in_field.add(str_value)
            
            if unmapped_in_field:
                unmapped_values[source_field] = list(unmapped_in_field)
                total_unmapped += len(unmapped_in_field)
        
        return {
            'is_valid': total_unmapped == 0,
            'unmapped_values': unmapped_values,
            'total_unmapped': total_unmapped,
        }
    
    def get_lookup_statistics(
        self, 
        lookup_match_results: Dict[str, Dict]
    ) -> Dict:
        """
        Generate statistics about lookup matching.
        
        Args:
            lookup_match_results: Results from process_all_lookup_fields()
            
        Returns:
            Statistics dictionary
        """
        total_fields = len(lookup_match_results)
        total_values = sum(r['total_values'] for r in lookup_match_results.values())
        total_auto_matched = sum(r['auto_matched'] for r in lookup_match_results.values())
        total_needs_review = sum(r['needs_review'] for r in lookup_match_results.values())
        
        return {
            'total_lookup_fields': total_fields,
            'total_unique_values': total_values,
            'auto_matched_values': total_auto_matched,
            'values_needing_review': total_needs_review,
            'auto_match_percentage': (total_auto_matched / total_values * 100) if total_values > 0 else 0,
        }
    
    def search_lookup_values(
        self, 
        lookup_model_name: str, 
        query: str, 
        limit: int = 20
    ) -> List[Dict]:
        """
        Search lookup table values for Select2 autocomplete.
        
        Args:
            lookup_model_name: Name of the lookup model
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching lookup entries
        """
        lookup_values = self.get_lookup_table_values(lookup_model_name)
        
        if not query:
            return lookup_values[:limit]
        
        # Score each lookup value
        scored_values = []
        
        for lookup_entry in lookup_values:
            search_strings = self._create_lookup_search_strings(lookup_entry)
            
            scores = [
                fuzz.token_set_ratio(query.lower(), s.lower())
                for s in search_strings
            ]
            
            best_score = max(scores) if scores else 0
            
            if best_score > 0:
                scored_values.append({
                    'score': best_score,
                    'entry': lookup_entry,
                })
        
        # Sort by score and return top results
        scored_values.sort(key=lambda x: x['score'], reverse=True)
        
        return [sv['entry'] for sv in scored_values[:limit]]

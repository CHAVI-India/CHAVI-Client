import logging
from typing import Dict, Any, List, Type, Tuple, Optional
from django.db import models
from django.db import transaction
from django.apps import apps

from .api_service import fetch_lookup_data

logger = logging.getLogger(__name__)

def map_api_data_to_model(data: Dict[str, Any], model_class: Type[models.Model]) -> Dict[str, Any]:
    """
    Map API data to model fields.
    Customize this function to handle field name differences between API and model.
    
    Args:
        data: Data from API
        model_class: Model class to map to
        
    Returns:
        Dict with field names matching the model
    """
    # Get field names from the model
    field_names = [field.name for field in model_class._meta.fields]
    
    # Filter data to only include fields that exist in the model
    filtered_data = {k: v for k, v in data.items() if k in field_names}
    
    # Here you could add any specific field mappings if API field names differ from model field names
    # For example: if data contains 'external_code' but model uses 'code'
    # if 'external_code' in data and 'code' in field_names:
    #     filtered_data['code'] = data['external_code']
    
    return filtered_data

def sync_model_from_api(
    model_class: Type[models.Model], 
    endpoint: str,
    pk_field: str = 'code',
    params: Optional[Dict[str, Any]] = None
) -> Tuple[int, int, List[str]]:
    """
    Sync data from API to the given model.
    
    Args:
        model_class: Model class to sync data to
        endpoint: API endpoint to fetch data from
        pk_field: Primary key field name
        params: Optional query parameters
        
    Returns:
        Tuple of (created_count, updated_count, errors)
    """
    success, response = fetch_lookup_data(endpoint, params)
    
    if not success:
        return 0, 0, [str(response)]
    
    # Ensure we have a list of items
    items = response if isinstance(response, list) else [response]
    
    created_count = 0
    updated_count = 0
    errors = []
    
    with transaction.atomic():
        for item in items:
            try:
                # Map API data to model fields
                model_data = map_api_data_to_model(item, model_class)
                
                # Check if record exists
                pk_value = model_data.get(pk_field)
                if not pk_value:
                    errors.append(f"Missing primary key '{pk_field}' in item {item}")
                    continue
                
                # Try to update or create
                instance, created = model_class.objects.update_or_create(
                    **{pk_field: pk_value},
                    defaults=model_data
                )
                
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                    
            except Exception as e:
                logger.exception(f"Error syncing item {item}: {e}")
                errors.append(f"Error syncing item: {str(e)}")
    
    return created_count, updated_count, errors 
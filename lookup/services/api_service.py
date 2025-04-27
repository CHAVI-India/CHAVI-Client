import requests
import logging
from django.conf import settings
from typing import Dict, Any, Optional, List, Tuple, Union

logger = logging.getLogger(__name__)

def get_proxies() -> Dict[str, str]:
    """Get proxy settings from Django settings"""
    proxies = {}
    if settings.HTTP_PROXY:
        proxies['http'] = settings.HTTP_PROXY
    if settings.HTTPS_PROXY:
        proxies['https'] = settings.HTTPS_PROXY
    return proxies

def get_auth_headers() -> Dict[str, str]:
    """Get authorization headers for API requests"""
    headers = {}
    if settings.LOOKUP_API_KEY:
        headers['Authorization'] = f'Api-Key {settings.LOOKUP_API_KEY}'
    return headers

def fetch_lookup_data(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
    """
    Fetch data from the lookup API
    
    Args:
        endpoint: API endpoint to fetch data from
        params: Optional query parameters
        
    Returns:
        Tuple of (success, data/error_message)
    """
    if not settings.LOOKUP_API_URL:
        return False, "API URL not configured"
    
    # Ensure the URL has correct slash handling (base_url/endpoint/)
    url = f"{settings.LOOKUP_API_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    if not url.endswith('/'):
        url = f"{url}/"
    
    headers = get_auth_headers()
    proxies = get_proxies()
    
    try:
        response = requests.get(
            url, 
            headers=headers,
            params=params,
            proxies=proxies,
            timeout=settings.LOOKUP_API_TIMEOUT,
            verify=True
        )
        
        response.raise_for_status()
        return True, response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return False, f"API request failed: {str(e)}"
    except ValueError as e:
        logger.error(f"Failed to parse API response: {e}")
        return False, "Failed to parse API response" 
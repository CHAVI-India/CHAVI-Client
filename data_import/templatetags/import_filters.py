"""
Custom template filters for data import templates.
"""

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary using a key.
    Usage: {{ mydict|get_item:key }}
    """
    if dictionary is None:
        return None
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter
def get_nested_item(dictionary, keys):
    """
    Get a nested item from a dictionary.
    Usage: {{ mydict|get_nested_item:"key1,key2" }}
    """
    if dictionary is None:
        return None
    
    if isinstance(keys, str):
        keys = keys.split(',')
    
    result = dictionary
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key.strip())
        else:
            return None
    
    return result

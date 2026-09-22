import os
from django import template

register = template.Library()


@register.filter
def basename(value):
    """
    Returns the base name of a file path.
    Example: 'uploads/file.pdf' -> 'file.pdf'
    """
    return os.path.basename(value)


@register.filter
def get_item(mapping, key):
    """Dictionary lookup for template use; returns None for missing keys."""
    if isinstance(mapping, dict):
        return mapping.get(key)
    return None

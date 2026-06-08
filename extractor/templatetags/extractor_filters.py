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

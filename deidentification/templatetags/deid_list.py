"""
Custom template tags for deidentification list templates.
"""

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def sort_link(context, key):
    """
    Build the URL and icon for a sortable column header.

    Toggles direction when the column is already the active sort; otherwise
    defaults to ascending. Preserves all current GET params except `page`.

    Usage:
        {% sort_link 'patient_id' as s %}
        <a href="{{ s.url }}">Patient ID <i class="fas {{ s.icon }}"></i></a>
    """
    request = context['request']
    params = request.GET.copy()
    params.pop('page', None)

    current_sort = context.get('current_sort')
    current_dir = context.get('current_dir', 'asc')

    active = current_sort == key
    params['sort'] = key
    params['dir'] = 'desc' if (active and current_dir == 'asc') else 'asc'

    icon = 'fa-sort'
    if active:
        icon = 'fa-sort-down' if current_dir == 'desc' else 'fa-sort-up'

    return {
        'url': '?' + params.urlencode(),
        'icon': icon,
        'active': active,
    }

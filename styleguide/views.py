from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def styleguide_view(request):
    """Render the living UI styleguide: every design token and component."""
    return render(request, 'styleguide/index.html', {
        'stepper_demo': [
            {'label': 'Upload', 'state': 'complete'},
            {'label': 'Match Studies', 'state': 'complete'},
            {'label': 'Confirm', 'state': 'active'},
            {'label': 'Complete', 'state': 'pending'},
        ],
        'datalist_demo': [
            {'label': 'AE Title', 'value': 'CHAVI_SCP'},
            {'label': 'Listening on', 'value': '0.0.0.0:11112'},
            {'label': 'Patient', 'value': 'PAT-0001'},
            {'label': 'Fields Extracted', 'value': '24'},
        ],
        'tabs_demo': [
            {'id': 'overview', 'label': 'Overview', 'active': True, 'href': '#'},
            {'id': 'records', 'label': 'Records', 'active': False, 'href': '#'},
            {'id': 'audit', 'label': 'Audit Log', 'active': False, 'href': '#'},
        ],
        'log_demo': [
            {'timestamp': '10:32:01', 'type': 'info', 'message': 'Schema discovery started'},
            {'timestamp': '10:32:04', 'type': 'processing', 'message': 'Reading table patient'},
            {'timestamp': '10:32:07', 'type': 'success', 'message': 'Discovered 12 tables'},
            {'timestamp': '10:32:09', 'type': 'error', 'message': 'Skipped view audit_log'},
        ],
        'link_chip_demo_url': '/patient-search/',
        'nav_dropdown_demo': [
            {'section': 'Run'},
            {'icon': 'fa-robot', 'label': 'Data Extraction', 'href': '#'},
            {'divider': True},
            {'section': 'Configure'},
            {'icon': 'fa-server', 'label': 'LLM Clients', 'href': '#'},
        ],
    })

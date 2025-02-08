from django.shortcuts import render
import os
from django.conf import settings
from django.views.static import serve

# Create your views here.

def documentation_view(request, path=''):
    """Serve the Sphinx documentation."""
    doc_root = os.path.join(settings.BASE_DIR, 'docs', '_build', 'html')
    if not path:
        path = 'index.html'
    return serve(request, path, document_root=doc_root)

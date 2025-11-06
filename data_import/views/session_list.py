"""
View for listing all import sessions.
"""

from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from ..models import FileImportSession


class ImportSessionListView(LoginRequiredMixin, ListView):
    """
    List all import sessions.
    """
    model = FileImportSession
    template_name = 'data_import/session_list.html'
    context_object_name = 'sessions'
    paginate_by = 20
    
    def get_queryset(self):
        """
        Get all sessions ordered by most recent first.
        """
        return FileImportSession.objects.all().order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Data Import Sessions'
        return context

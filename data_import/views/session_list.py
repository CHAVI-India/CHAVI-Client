"""
View for listing all import sessions.
"""

from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.views import redirect_to_login
from ..models import FileImportSession


class ImportSessionListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """
    List all import sessions.
    """
    permission_required = 'data_import.view_fileimportsession'
    raise_exception = True
    model = FileImportSession

    def handle_no_permission(self):
        # Anonymous → login redirect; authenticated without perm → 403.
        if self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect_to_login(
            self.request.get_full_path(),
            self.get_login_url(),
            self.get_redirect_field_name(),
        )
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

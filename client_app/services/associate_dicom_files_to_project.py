from django import forms
from django.contrib import messages
from django.http import HttpRequest
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from unfold.decorators import action
from unfold.widgets import UnfoldAdminSelectWidget
from client_app.models import DICOMStudy, Project, DICOMStudyProject
import logging

logger = logging.getLogger('client_app')

class ProjectSelectionForm(forms.Form):
    project = forms.ModelChoiceField(
        queryset=Project.objects.all(),
        label=_("Select Project"),
        help_text=_("Choose the project to associate with the selected DICOM studies"),
        widget=UnfoldAdminSelectWidget
    )

    class Media:
        js = [
            "admin/js/vendor/jquery/jquery.js",
            "admin/js/jquery.init.js",
            "admin/js/core.js",
        ]

@action(description=_("Associate selected DICOM studies with a project"))
def associate_dicom_files_to_project(modeladmin, request: HttpRequest, queryset) -> str:
    '''This admin action will link individual DICOMStudyObjects to selected Project instance(s). The admin action will be available on the DICOMStudy model. When the dicom objects are selected, then the admin action will open a intermediate form which allows users to selec the project(s) to associate the DICOM study with and after selection add the appropriate links through the M2M model.'''
    
    logger.debug("Action called")
    logger.debug(f"Request method: {request.method}")
    logger.debug(f"POST data: {request.POST}")
    logger.debug(f"Selected queryset count: {queryset.count()}")
    
    form = ProjectSelectionForm(request.POST or None)
    
    if request.method == "POST" and 'project' in request.POST:
        logger.debug(f"Form is valid: {form.is_valid()}")
        if form.is_valid():
            project = form.cleaned_data['project']
            associations_created = 0
            
            logger.info(f"Processing association of {queryset.count()} DICOM studies with project {project}")
            
            for dicom_study in queryset:
                try:
                    logger.debug(f"Attempting to create association for DICOM study {dicom_study}")
                    association, created = DICOMStudyProject.objects.get_or_create(
                        study_instance_uid=dicom_study,
                        project=project
                    )
                    if created:
                        associations_created += 1
                        logger.info(f"Created association between DICOM study {dicom_study} and project {project}")
                except Exception as e:
                    logger.error(f"Error creating association: {str(e)}")
                    messages.error(
                        request,
                        _('Error associating DICOM study {} with project {}: {}').format(
                            dicom_study, project, str(e)
                        )
                    )
            
            if associations_created > 0:
                messages.success(
                    request,
                    _('Successfully associated {} DICOM studies with project {}').format(
                        associations_created, project.project_name
                    )
                )
            else:
                messages.warning(
                    request,
                    _('No new associations were created. The DICOM studies may already be associated with this project.')
                )
            
            return reverse_lazy('admin:client_app_dicomstudy_changelist')
        else:
            logger.error(f"Form errors: {form.errors}")
            messages.error(request, _('Please correct the errors below.'))

    context = {
        'form': form,
        'queryset': queryset,
        'title': _('Associate DICOM Studies with Project'),
        **modeladmin.admin_site.each_context(request),
    }
    logger.debug(f"Rendering template with context: {context}")
    
    return render(
        request,
        'admin/associate_dicom_to_project.html',
        context
    )


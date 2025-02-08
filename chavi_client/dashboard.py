"""
This file was generated with the customdashboard management command and
contains the class for the main dashboard.

To activate your index dashboard add the following to your settings.py::
    GRAPPELLI_INDEX_DASHBOARD = 'chavi_client.dashboard.CustomIndexDashboard'
"""

from django.utils.translation import gettext_lazy as _
from django.urls import reverse

from grappelli.dashboard import modules, Dashboard
from grappelli.dashboard.utils import get_admin_site_name


class CustomIndexDashboard(Dashboard):
    """
    Custom index dashboard for www.
    """

    def init_with_context(self, context):
        site_name = get_admin_site_name(context)

        self.children.append(modules.ModelList(
            _('Configurations'),
            collapsible=True,
            column=2,
            css_classes=('collapse closed',),
            models=('client_app.models.SiteConfiguration',
                    'client_app.models.Project',
                    ),
        ))
        self.children.append(modules.ModelList(
            _('DICOM Data'),
            collapsible=True,
            column=2,
            css_classes=('collapse closed',),
            models=('client_app.models.DICOMStudy',
                    'client_app.models.PatientDicomFile',
                    'client_app.models.BulkDICOMUpload',
                    ),
        ))        

        # append a group for "Administration" & "Applications"
        self.children.append(modules.Group(
            _('Administration'),
            column=2,
            collapsible=True,
            children = [
                modules.AppList(
                    _('Administration'),
                    column=1,
                    collapsible=False,
                    models=('django.contrib.auth.models.User',
                            'django.contrib.auth.models.Group',
                                                                                    ),
                ),
                modules.AppList(
                    _('Accounts'),
                    column=1,
                    collapsible=False,
                    models=('allauth.*',),
                )
            ]
        ))

        # append an app list module for "Applications"
        self.children.append(modules.ModelList(
            _('Patient Data'),
            collapsible=True,
            column=1,
            css_classes=('collapse closed',),
            models=('client_app.models.Patient',
                    'client_app.models.Symptom',
                    'client_app.models.Comorbidity',
                    'client_app.models.LaboratoryResults',
                    'client_app.models.GermlineGenomicAlterations',
                    ),
        ))
        self.children.append(modules.ModelList(
            _('Disease Data'),
            collapsible=True,
            column=1,
            css_classes=('collapse closed',),
            models=('client_app.models.Diagnosis',
                    'client_app.models.Pathology',
                    'client_app.models.StageInformation',
                    'client_app.models.Lesion',
                    ),
        ))        
        self.children.append(modules.ModelList(
            _('Treatment Data'),
            collapsible=True,
            column=1,
            css_classes=('collapse closed',),
            models=('client_app.models.Radiotherapy',
                    'client_app.models.Surgery',
                    'client_app.models.SystemicTherapy',
                    'client_app.models.ConcomitantMedications',
                    'client_app.models.OtherTreatment',
                    ),
        ))
        self.children.append(modules.ModelList(
            _('Outcome Data'),
            collapsible=True,
            column=1,
            css_classes=('collapse closed',),
            models=('client_app.models.PatientOutcome',
                    'client_app.models.Outcome',
                    'client_app.models.AdverseEffects',
                    'client_app.models.LesionResponse',
                    'client_app.models.PatientReportedOutcome',
                    ),
        ))                 

        # append another link list module for "support".
        # self.children.append(modules.LinkList(
        #     _('Media Management'),
        #     column=2,
        #     children=[
        #         {
        #             'title': _('FileBrowser'),
        #             'url': '/admin/filebrowser/browse/',
        #             'external': False,
        #         },
        #     ]
        # ))

        # append another link list module for "support".
        self.children.append(modules.LinkList(
            _('Account Links'),
            column=3,
            children=[
                {
                    'title': _('Accounts & Mulifactor Authentication'),
                    'url': '/accounts/',
                    'external': False,
                },
            ]
        ))
        self.children.append(modules.LinkList(
            _('Help and Documentation'),
            column=3,
            children=[
                {
                    'title': _('Documentation'),
                    'url': '/docs/',
                    'external': False,
                },
            ]
        ))        

        # append a feed module
        # self.children.append(modules.Feed(
        #     _('Latest Django News'),
        #     column=2,
        #     feed_url='http://www.djangoproject.com/rss/weblog/',
        #     limit=5
        # ))

        # append a recent actions module
        self.children.append(modules.RecentActions(
            _('Recent actions'),
            limit=5,
            collapsible=False,
            column=3,
        ))

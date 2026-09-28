"""RBAC regression tests: model permission gating, role groups, link hiding.

Covers:
- anonymous users redirect to login on every gated URL,
- authenticated users without permissions get 403,
- users holding the mapped model permission get 200,
- the seven role groups created by migration 0029 grant the expected
  access pattern,
- the navbar hides links whose target views the user cannot access.
"""
from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.urls import reverse

from client_app.models import Patient, SiteConfiguration


# (url_name, 'app_label.codename') for GET endpoints that take no arguments.
GATED_GET_URLS = [
    ('client_app:patient_search', 'client_app.view_patient'),
    ('client_app:bulk_dicom_upload', 'client_app.add_bulkdicomuploadsession'),
    ('client_app:bulk_dicom_session_list', 'client_app.view_bulkdicomuploadsession'),
    ('client_app:patient_data_export', 'client_app.view_patient'),
    ('client_app:dicom_data_export', 'client_app.view_dicomstudy'),
    ('client_app:taskrun_list', 'client_app.view_taskrun'),
    ('client_app:comorbidity_list', 'client_app.view_comorbidity'),
    ('client_app:comorbidity_add', 'client_app.add_comorbidity'),
    ('data_import:session_list', 'data_import.view_fileimportsession'),
    ('data_import:step1', 'data_import.add_fileimportsession'),
    ('deidentification:patient_list', 'deidentification.view_deidpatient'),
    ('deidentification:legacy_import', 'deidentification.add_deidpatient'),
    ('extractor:file_upload_list', 'extractor.view_fileupload'),
    ('extractor:extraction_dashboard', 'extractor.view_processedtext'),
    ('extractor:client_configuration_list', 'extractor.view_clientconfiguration'),
]


class PermissionGatingTests(TestCase):
    """Every gated URL: anonymous → login redirect; plain user → 403;
    a user carrying the mapped model permission → 200."""

    @classmethod
    def setUpTestData(cls):
        cls.plain = User.objects.create_user('plain', password='pw')

    def test_anonymous_redirected_to_login(self):
        for url_name, _perm in GATED_GET_URLS:
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 302, url_name)
            self.assertIn('/accounts/login/', resp.url, url_name)

    def test_plain_user_forbidden(self):
        self.client.force_login(self.plain)
        for url_name, _perm in GATED_GET_URLS:
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 403, url_name)

    def test_permission_holder_allowed(self):
        counter = 0
        for url_name, perm in GATED_GET_URLS:
            counter += 1
            user = User.objects.create_user(f'holder{counter}', password='pw')
            app_label, codename = perm.split('.')
            user.user_permissions.add(Permission.objects.get(
                content_type__app_label=app_label, codename=codename,
            ))
            self.client.force_login(user)
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, url_name)

    def test_staff_flag_alone_is_not_enough(self):
        # is_staff no longer opens deidentification or DICOM-server pages —
        # the model permission is required.
        staff = User.objects.create_user('staffonly', password='pw', is_staff=True)
        self.client.force_login(staff)
        for url_name in (
            'deidentification:patient_list',
            'dicom_server:config_edit',
            'dicom_server:retrieve',
        ):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 403, url_name)


class RoleGroupTests(TestCase):
    """The groups created by migration 0029 grant the expected access."""

    def _user_in_group(self, name, username):
        user = User.objects.create_user(username, password='pw')
        user.groups.add(Group.objects.get(name=name))
        self.client.force_login(user)
        return user

    def test_role_groups_created_by_migration(self):
        for name in (
            'Clinical Data Viewer', 'Clinical Data Entry', 'Data Import Operator',
            'LLM Extraction Operator', 'LLM Configuration',
            'Deidentification Operator', 'DICOM Administrator',
        ):
            group = Group.objects.filter(name=name).first()
            self.assertIsNotNone(group, name)
            self.assertGreater(group.permissions.count(), 0, name)

    def test_clinical_viewer_can_read_but_not_write(self):
        self._user_in_group('Clinical Data Viewer', 'cv')
        for url_name in (
            'client_app:patient_search',
            'client_app:comorbidity_list',
            'client_app:diagnosis_list',
            'client_app:patient_data_export',
            'client_app:taskrun_list',
        ):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, url_name)
        for url_name in (
            'client_app:patient_add',
            'client_app:comorbidity_add',
            'deidentification:patient_list',
            'extractor:extraction_dashboard',
        ):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 403, url_name)

    def test_clinical_data_entry_can_add_and_change(self):
        self._user_in_group('Clinical Data Entry', 'ce')
        for url_name in ('client_app:patient_add', 'client_app:comorbidity_add'):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, url_name)
        # change permission is evaluated before object lookup, so a missing
        # pk proves the permission check passed (404, not 403).
        resp = self.client.get(
            reverse('client_app:comorbidity_edit',
                    args=['00000000-0000-0000-0000-000000000000'])
        )
        self.assertEqual(resp.status_code, 404)

    def test_data_import_operator(self):
        self._user_in_group('Data Import Operator', 'di')
        for url_name in (
            'data_import:session_list',
            'data_import:step1',
            'client_app:bulk_dicom_upload',
            'client_app:bulk_dicom_session_list',
            'client_app:patient_search',
            'dicom_server:retrieve',
        ):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, url_name)
        # No clinical data-entry or deidentification access.
        resp = self.client.get(reverse('client_app:comorbidity_add'))
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get(reverse('deidentification:patient_list'))
        self.assertEqual(resp.status_code, 403)

    def test_llm_extraction_operator(self):
        self._user_in_group('LLM Extraction Operator', 'llmop')
        for url_name in (
            'extractor:file_upload_list',
            'extractor:extraction_dashboard',
            'extractor:extraction_results_list',
            'client_app:taskrun_list',
        ):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, url_name)
        # No access to LLM client configuration, but response models are
        # readable (operators pick one when starting an extraction).
        resp = self.client.get(reverse('extractor:client_configuration_list'))
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get(reverse('extractor:response_model_list'))
        self.assertEqual(resp.status_code, 200)

    def test_llm_configuration(self):
        self._user_in_group('LLM Configuration', 'llmcfg')
        for url_name in (
            'extractor:client_configuration_list',
            'extractor:response_model_list',
            'extractor:instructor_message_list',
            'extractor:semantic_search_settings',
            'extractor:file_upload_list',
            'extractor:extraction_dashboard',
        ):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, url_name)
        # Read-only on operational models: no upload, no extraction start.
        resp = self.client.get(reverse('extractor:file_upload_create'))
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get(reverse('client_app:patient_search'))
        self.assertEqual(resp.status_code, 403)

    def test_deidentification_operator(self):
        self._user_in_group('Deidentification Operator', 'deidop')
        for url_name in (
            'deidentification:patient_list',
            'deidentification:legacy_import',
            'client_app:taskrun_list',
        ):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, url_name)
        resp = self.client.get(reverse('client_app:comorbidity_add'))
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get(reverse('extractor:extraction_dashboard'))
        self.assertEqual(resp.status_code, 403)

    def test_dicom_administrator(self):
        self._user_in_group('DICOM Administrator', 'dicomadmin')
        for url_name in (
            'dicom_server:dashboard',
            'dicom_server:node_list',
            'dicom_server:node_create',
            'dicom_server:config_edit',
            'dicom_server:job_list',
            'client_app:taskrun_list',
        ):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, url_name)
        # Admin manages nodes/config but cannot itself trigger retrievals.
        resp = self.client.get(reverse('dicom_server:retrieve'))
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get(reverse('client_app:patient_search'))
        self.assertEqual(resp.status_code, 403)


class NavbarVisibilityTests(TestCase):
    """Nav links are hidden when the user lacks the underlying permission.

    Assertions use the rendered ``>Label<`` markup so they can't match the
    HTML comments that annotate the template blocks.
    """

    HIDDEN_LABELS = (
        '>Data Import<', '>LLM Extraction<', '>Deidentification<',
        '>Patient Search<', '>Task Runs<', '>Admin<',
    )

    def _homepage(self):
        return self.client.get(reverse('client_app:homepage'))

    def test_anonymous_nav_has_no_privileged_links(self):
        resp = self._homepage()
        self.assertContains(resp, 'Docs')
        for label in self.HIDDEN_LABELS:
            self.assertNotContains(resp, label)

    def test_plain_user_sees_no_privileged_links(self):
        user = User.objects.create_user('navplain', password='pw')
        self.client.force_login(user)
        resp = self._homepage()
        for label in self.HIDDEN_LABELS:
            self.assertNotContains(resp, label)

    def test_clinical_viewer_nav(self):
        user = User.objects.create_user('navviewer', password='pw')
        user.groups.add(Group.objects.get(name='Clinical Data Viewer'))
        self.client.force_login(user)
        resp = self._homepage()
        self.assertContains(resp, '>Patient Search<')
        self.assertContains(resp, '>Task Runs<')
        for label in ('>Data Import<', '>LLM Extraction<', '>Deidentification<'):
            self.assertNotContains(resp, label)

    def test_llm_extraction_operator_nav(self):
        user = User.objects.create_user('navllm', password='pw')
        user.groups.add(Group.objects.get(name='LLM Extraction Operator'))
        self.client.force_login(user)
        resp = self._homepage()
        self.assertContains(resp, '>LLM Extraction<')
        self.assertContains(resp, '>Data Extraction<')
        # Operator has no configuration perms — config links stay hidden.
        self.assertNotContains(resp, '>LLM Clients<')
        self.assertNotContains(resp, '>Deidentification<')

    def test_llm_configuration_nav(self):
        user = User.objects.create_user('navcfg', password='pw')
        user.groups.add(Group.objects.get(name='LLM Configuration'))
        self.client.force_login(user)
        resp = self._homepage()
        self.assertContains(resp, '>LLM Extraction<')
        self.assertContains(resp, '>LLM Clients<')
        self.assertContains(resp, '>Start Wizard<')
        self.assertNotContains(resp, '>Deidentification<')

    def test_staff_user_sees_admin_link(self):
        user = User.objects.create_user('navstaff', password='pw', is_staff=True)
        self.client.force_login(user)
        resp = self._homepage()
        self.assertContains(resp, '>Admin<')


class PatientSummaryPermissionTests(TestCase):
    """Summary page: view_patient opens it, action links follow per-model perms."""

    @classmethod
    def setUpTestData(cls):
        # Patient.center auto-resolves to the SiteConfiguration row.
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Hospital',
        )
        cls.patient = Patient.objects.create(patient_id='MR/25/000001', gender='Female')

    def test_plain_user_cannot_view_summary(self):
        user = User.objects.create_user('sumplain', password='pw')
        self.client.force_login(user)
        resp = self.client.get(
            reverse('client_app:patient_summary'),
            {'patient_id': self.patient.patient_id},
        )
        self.assertEqual(resp.status_code, 403)

    def test_viewer_sees_view_links_but_no_add_links(self):
        user = User.objects.create_user('sumviewer', password='pw')
        user.groups.add(Group.objects.get(name='Clinical Data Viewer'))
        self.client.force_login(user)
        resp = self.client.get(
            reverse('client_app:patient_summary'),
            {'patient_id': self.patient.patient_id},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'View All')
        self.assertNotContains(resp, 'Add New Diagnosis')
        self.assertNotContains(resp, 'Edit Diagnosis')

    def test_data_entry_sees_add_links(self):
        user = User.objects.create_user('sumentry', password='pw')
        user.groups.add(Group.objects.get(name='Clinical Data Entry'))
        self.client.force_login(user)
        resp = self.client.get(
            reverse('client_app:patient_summary'),
            {'patient_id': self.patient.patient_id},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Add New Diagnosis')

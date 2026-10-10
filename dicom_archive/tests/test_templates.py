"""Render tests for the dicom_archive templates (plan 03, Task 4)."""
import re

from django.template import engines
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from client_app.models import DICOMStudy
from dicom_archive.models import ArchivedStudy
from dicom_archive.tests.test_views import ArchiveViewTestCase


class TestComponentExtraClassIsolation(ArchiveViewTestCase):
    """Regression: a nested component must NOT inherit the outer
    component's extra_class via template context fallback.

    Previously the dashboard's Recent-archived card (extra_class="mb-8")
    leaked mb-8 into the nested table wrapper, status badge and footer
    button — the badge's 2rem bottom margin shifted it out of alignment
    with the rest of the row's text."""

    def test_nested_components_do_not_inherit_outer_extra_class(self):
        html = engines['django'].from_string(
            '{% component "card" extra_class="mb-8" %}'
            '{% fill "body" %}'
            '{% if items %}'
            '{% component "table" compact=True %}'
            '{% fill "head" %}<th>A</th>{% endfill %}'
            '{% fill "body" %}'
            '<tr><td>{% component "badge" style="success" %}X{% endcomponent %}</td></tr>'
            '{% endfill %}'
            '{% endcomponent %}'
            '{% endif %}'
            '{% endfill %}'
            '{% fill "footer" %}'
            '{% component "button" style="link" %}All{% endcomponent %}'
            '{% endfill %}'
            '{% endcomponent %}'
        ).render({'items': [1]})
        # exactly one mb-8 — on the card root only
        self.assertEqual(html.count('mb-8'), 1)
        self.assertNotIn(
            'mb-8', html[html.find('<span class="inline-flex'):])

    def test_dashboard_badge_carries_no_inherited_margin(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        html = resp.content.decode()
        i = html.find('Recent Archived Studies')
        table = html[i:html.find('</table>', i)]
        # the status badge inside the table has no mb-* margin classes
        badge = re.search(
            r'<span class="inline-flex items-center[^>]*>', table)
        self.assertIsNotNone(badge)
        self.assertNotIn('mb-', badge.group(0))
        # and neither does the table wrapper
        wrapper = re.search(
            r'<div class="overflow-x-auto[^"]*"', table)
        self.assertIsNotNone(wrapper)
        self.assertNotIn('mb-', wrapper.group(0))


class TestPageRendering(ArchiveViewTestCase):
    def setUp(self):
        super().setUp()  # cache.clear() from ArchiveViewTestCase
        self.client.force_login(self.admin)

    def test_dashboard_renders_config_and_recent(self):
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, 'Archive Configuration')
        self.assertContains(resp, 'Default Archive Location')
        self.assertContains(resp, self.study.study_instance_uid)
        self.assertContains(resp, 'Manage locations')

    def test_dashboard_config_card_reflects_defaults(self):
        # no config row in the DB -> ArchiveConfiguration.load() creates
        # the singleton with defaults (archive_after_days=90, enabled=False)
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        self.assertContains(resp, '90 days')
        self.assertContains(resp, 'Disabled')

    def test_config_edit_renders_form_fields(self):
        resp = self.client.get(reverse('dicom_archive:config_edit'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, 'archive_after_days')
        self.assertContains(resp, 'archive_minute')
        self.assertContains(resp, 'batch_limit')

    def test_location_list_shows_location_and_delete_form(self):
        resp = self.client.get(reverse('dicom_archive:location_list'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, 'NAS archive')
        self.assertContains(
            resp,
            reverse('dicom_archive:location_delete', args=[self.location.pk]))

    def test_location_form_renders_for_create(self):
        resp = self.client.get(reverse('dicom_archive:location_create'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, 'storage_type')
        self.assertContains(resp, 'path')

    def test_browse_renders_rows_with_checkboxes_and_triggers(self):
        resp = self.client.get(reverse('dicom_archive:browse'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, self.study.study_instance_uid)
        self.assertContains(resp, 'archive-selected-btn')
        self.assertContains(resp, 'study-uid-check')
        self.assertContains(resp, reverse('dicom_archive:archive_trigger'))
        self.assertContains(
            resp, reverse('dicom_archive:task_status', args=['0']))

    def test_browse_hides_trigger_ui_without_add_perm(self):
        self.client.force_login(self.viewer)  # view only, no add_archivedstudy
        resp = self.client.get(reverse('dicom_archive:browse'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'archive-selected-btn')
        self.assertNotContains(
            resp, reverse('dicom_archive:archive_trigger'))

    def test_browse_filters_by_q(self):
        DICOMStudy.objects.create(
            patient=self.patient,
            study_instance_uid='1.2.3.4.5.6.7.8.42',
            study_date='2025-02-01',
            folder_path='/media/processed_dicom/MR_25_000001/1.2.3.4.5.6.7.8.42',
        )
        resp = self.client.get(
            reverse('dicom_archive:browse') + '?q=1.2.3.4.5.6.7.8.42')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.42')
        self.assertNotContains(resp, '1.2.3.4.5.6.7.8.9')

    def test_browse_paginates_at_25(self):
        for i in range(30):
            uid = f'1.2.88.{i:02d}.1'
            DICOMStudy.objects.create(
                patient=self.patient, study_instance_uid=uid,
                folder_path=f'/media/processed_dicom/p/{uid}')
        resp = self.client.get(reverse('dicom_archive:browse'))
        self.assertEqual(len(resp.context['studies']), 25)
        # fixture study + 30 = 31 rows -> page 2 holds 6
        resp = self.client.get(reverse('dicom_archive:browse') + '?page=2')
        self.assertEqual(len(resp.context['studies']), 6)

    def test_archived_list_renders_with_filters_and_trigger(self):
        resp = self.client.get(reverse('dicom_archive:archived_list'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, 'NAS archive')
        self.assertContains(resp, 'dearchive-selected-btn')
        self.assertContains(resp, reverse('dicom_archive:dearchive_trigger'))

    def test_archived_list_defaults_to_archived_only(self):
        """De-archived studies are local again — the default view must
        not show them; they remain reachable via the status filter."""
        other_study = DICOMStudy.objects.create(
            patient=self.patient,
            study_instance_uid='1.2.3.4.5.6.7.8.42',
            folder_path='/media/processed_dicom/MR_25_000001/1.2.3.4.5.6.7.8.42',
        )
        ArchivedStudy.objects.create(
            study=other_study, location=self.location,
            status=ArchivedStudy.Status.DEARCHIVED,
            local_path_before=other_study.folder_path,
            archive_rel_path='MR_25_000001/1.2.3.4.5.6.7.8.42',
            dearchived_at=timezone.now(),
        )
        # default: ARCHIVED only — the DEARCHIVED study is hidden
        resp = self.client.get(reverse('dicom_archive:archived_list'))
        self.assertContains(resp, '1.2.3.4.5.6.7.8.9')
        self.assertNotContains(resp, '1.2.3.4.5.6.7.8.42')
        # explicit DEARCHIVED filter shows it
        resp = self.client.get(
            reverse('dicom_archive:archived_list') + '?status=DEARCHIVED')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.42')
        self.assertNotContains(resp, '1.2.3.4.5.6.7.8.9')
        # "All statuses" (?status= present but empty) shows both
        resp = self.client.get(
            reverse('dicom_archive:archived_list') + '?status=')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.9')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.42')

    def test_archived_list_filters_by_status_and_location(self):
        other_study = DICOMStudy.objects.create(
            patient=self.patient,
            study_instance_uid='1.2.3.4.5.6.7.8.42',
            folder_path='/media/processed_dicom/MR_25_000001/1.2.3.4.5.6.7.8.42',
        )
        ArchivedStudy.objects.create(
            study=other_study, location=self.location,
            status=ArchivedStudy.Status.DEARCHIVED,
            local_path_before=other_study.folder_path,
            archive_rel_path='MR_25_000001/1.2.3.4.5.6.7.8.42',
            dearchived_at=timezone.now(),
        )
        resp = self.client.get(
            reverse('dicom_archive:archived_list') + '?status=ARCHIVED')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.9')
        self.assertNotContains(resp, '1.2.3.4.5.6.7.8.42')
        resp = self.client.get(
            reverse('dicom_archive:archived_list')
            + f'?status=DEARCHIVED&location_id={self.location.pk}')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.42')


class TestLocationTestButtons(ArchiveViewTestCase):
    """The Test buttons and their result containers render on the
    locations pages."""

    def test_location_list_has_test_button_per_row(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('dicom_archive:location_list'))
        html = resp.content.decode()
        self.assertContains(resp, 'location-test-btn')
        self.assertContains(resp, reverse('dicom_archive:location_test'))
        self.assertIn('id="location-test-result"', html)

    def test_location_form_has_test_path_button(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('dicom_archive:location_create'))
        self.assertContains(resp, 'id="test-path-btn"')
        self.assertContains(resp, 'id="path-test-result"')
        self.assertContains(resp, 'chavi_archive_write_test.txt')

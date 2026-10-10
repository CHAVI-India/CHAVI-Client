"""Nav integration tests: DICOM Archive entry in DATA IMPORT (plan 03).

The desktop dropdown and mobile menu share templates/base.html, so one
authenticated GET through any base-extending page covers both renderings.
fa-box-archive appears ONLY in the new nav items (page headers use other
icons — design note 5), making it a unique marker.
"""
from django.test import TestCase
from django.urls import reverse

from dicom_archive.tests.test_views import ArchiveViewTestCase


class TestNavIntegration(ArchiveViewTestCase):
    def test_nav_shows_archive_for_user_with_config_view_perm(self):
        # admin has view_archiveconfiguration; dashboard renders base.html
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        self.assertContains(resp, 'fa-box-archive')
        self.assertContains(resp, 'DICOM Archive')

    def test_nav_hides_archive_without_config_view_perm(self):
        # viewer has only view_archivedstudy -> no nav entry
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse('dicom_archive:browse'))
        self.assertContains(resp, 'Local Studies')
        self.assertNotContains(resp, 'fa-box-archive')

    def test_section_gate_opens_with_archive_perm_alone(self):
        # user with ONLY view_archiveconfiguration (no other section perms)
        # must still see the DATA IMPORT section via the extended gate.
        from django.contrib.auth.models import Permission, User
        user = User.objects.create_user('archive-only', password='pw')
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_archive',
            codename__in=['view_archiveconfiguration'],
        ))
        self.client.force_login(user)
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        self.assertContains(resp, 'Data Import')
        self.assertContains(resp, 'fa-box-archive')

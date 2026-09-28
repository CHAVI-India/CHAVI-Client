from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from client_app.models import Notification, TaskRun
from client_app.tasks import (
    MAX_AUTO_CONTINUE_ATTEMPTS,
    _auto_continue_task,
    task_associate_dicom_to_project,
)


class AutoContinueTaskTests(TestCase):
    """Regression tests for the soft-time-limit auto-continue mechanism."""

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pw')
        self.task_run = TaskRun.objects.create(
            task_id='old-task-id',
            task_name='task_export_dicom_data_parallel',
            task_type=TaskRun.TaskType.DICOM_EXPORT,
            status=TaskRun.Status.PROGRESS,
            user=self.user,
            resume_count=0,
            task_args=[[1, 2, 3], 'uuid-123'],
            task_kwargs={'include_patient_data': False, 'user_id': 1},
        )

    def _mock_task_func(self, new_task_id='new-task-id'):
        mock_func = MagicMock()
        mock_func.apply_async.return_value = MagicMock(id=new_task_id)
        return mock_func

    def test_auto_continue_dispatches_new_task_and_updates_task_run(self):
        mock_func = self._mock_task_func('new-task-id')

        result = _auto_continue_task(
            self.task_run, mock_func, self.task_run.task_args, self.task_run.task_kwargs
        )

        mock_func.apply_async.assert_called_once_with(
            args=self.task_run.task_args, kwargs=self.task_run.task_kwargs, countdown=2
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.id, 'new-task-id')

        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.task_id, 'new-task-id')
        self.assertEqual(self.task_run.status, TaskRun.Status.PENDING)
        self.assertEqual(self.task_run.resume_count, 1)

        self.assertTrue(
            Notification.objects.filter(
                task_run=self.task_run,
                notification_type=Notification.NotificationType.TASK_RESUMED,
            ).exists()
        )

    def test_auto_continue_stops_after_max_attempts(self):
        self.task_run.resume_count = MAX_AUTO_CONTINUE_ATTEMPTS
        self.task_run.save(update_fields=['resume_count'])
        mock_func = self._mock_task_func()

        result = _auto_continue_task(
            self.task_run, mock_func, self.task_run.task_args, self.task_run.task_kwargs
        )

        self.assertIsNone(result)
        mock_func.apply_async.assert_not_called()

        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.status, TaskRun.Status.FAILURE)
        self.assertIn('maximum auto-continue attempts', self.task_run.error_log)


class TaskRunResumeRetryViewTests(TestCase):
    """Regression tests for generic resume/retry redispatch using stored task_args."""

    def setUp(self):
        self.user = User.objects.create_user(username='tester2', password='pw')
        # Resume/retry need view_taskrun + change_taskrun plus the per-type
        # permission from TASK_TYPE_PERMISSIONS (ASSOCIATE → view_patient).
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='client_app',
            codename__in=['view_patient', 'view_taskrun', 'change_taskrun'],
        ))
        self.client.force_login(self.user)

    def _make_task_run(self, status, task_args=None, task_kwargs=None, task_name='task_associate_dicom_to_project'):
        return TaskRun.objects.create(
            task_id='task-id-1',
            task_name=task_name,
            task_type=TaskRun.TaskType.ASSOCIATE,
            status=status,
            user=self.user,
            task_args=task_args,
            task_kwargs=task_kwargs,
        )

    @patch.object(task_associate_dicom_to_project, 'delay')
    def test_resume_redispatches_with_stored_args(self, mock_delay):
        mock_delay.return_value = MagicMock(id='new-id-1')
        task_run = self._make_task_run(
            TaskRun.Status.STALLED, task_args=[[1, 2], 5], task_kwargs={'user_id': 1}
        )

        response = self.client.post(reverse('client_app:taskrun_resume', args=[task_run.pk]))

        mock_delay.assert_called_once_with([1, 2], 5, user_id=1)
        task_run.refresh_from_db()
        self.assertEqual(task_run.task_id, 'new-id-1')
        self.assertEqual(task_run.resume_count, 1)
        self.assertEqual(task_run.status, TaskRun.Status.PENDING)
        self.assertRedirects(
            response, reverse('client_app:task_progress', kwargs={'task_id': 'new-id-1'}), fetch_redirect_response=False
        )

    def test_resume_fails_gracefully_without_stored_args(self):
        task_run = self._make_task_run(TaskRun.Status.FAILURE, task_args=None)

        response = self.client.post(reverse('client_app:taskrun_resume', args=[task_run.pk]))

        self.assertRedirects(response, reverse('client_app:taskrun_detail', kwargs={'pk': task_run.pk}))
        task_run.refresh_from_db()
        # Status should remain unchanged since redispatch was not possible.
        self.assertEqual(task_run.status, TaskRun.Status.FAILURE)

    def test_resume_rejected_for_non_resumable_status(self):
        task_run = self._make_task_run(TaskRun.Status.SUCCESS, task_args=[[1], 2])

        response = self.client.post(reverse('client_app:taskrun_resume', args=[task_run.pk]))

        self.assertRedirects(response, reverse('client_app:taskrun_detail', kwargs={'pk': task_run.pk}))

    @patch.object(task_associate_dicom_to_project, 'delay')
    def test_retry_creates_new_task_run_row(self, mock_delay):
        mock_delay.return_value = MagicMock(id='new-id-2')
        task_run = self._make_task_run(
            TaskRun.Status.SUCCESS, task_args=[[3, 4], 6], task_kwargs={'user_id': 2}
        )

        response = self.client.post(reverse('client_app:taskrun_retry', args=[task_run.pk]))

        mock_delay.assert_called_once_with([3, 4], 6, user_id=2)
        self.assertTrue(TaskRun.objects.filter(task_id='new-id-2').exists())
        new_run = TaskRun.objects.get(task_id='new-id-2')
        self.assertEqual(new_run.status, TaskRun.Status.PENDING)
        self.assertEqual(new_run.task_args, [[3, 4], 6])
        self.assertRedirects(
            response, reverse('client_app:task_progress', kwargs={'task_id': 'new-id-2'}), fetch_redirect_response=False
        )

class FlashMessageRenderingTests(TestCase):
    """base.html renders django.contrib.messages once per page, so messages
    surface on their redirect target and cannot leak onto unrelated pages."""

    def setUp(self):
        self.user = User.objects.create_superuser(username='admin', password='pw')
        self.client.force_login(self.user)
        self.task_run = TaskRun.objects.create(
            task_id='task-id-1',
            task_name='task_associate_dicom_to_project',
            task_type=TaskRun.TaskType.ASSOCIATE,
            status=TaskRun.Status.SUCCESS,
            user=self.user,
        )

    def test_error_message_renders_on_redirect_target(self):
        # taskrun_detail has no message block of its own — the alert must still
        # render via the shared block in base.html.
        response = self.client.post(
            reverse('client_app:taskrun_resume', args=[self.task_run.pk]), follow=True,
        )
        self.assertContains(response, 'role="alert"')
        self.assertContains(response, 'Only failed or stalled tasks can be resumed.')

    def test_consumed_message_does_not_leak_to_next_page(self):
        self.client.post(reverse('client_app:taskrun_resume', args=[self.task_run.pk]))
        # Consume the queued message by rendering its redirect target.
        self.client.get(reverse('client_app:taskrun_detail', args=[self.task_run.pk]))
        # A subsequent page must not re-display it.
        response = self.client.get(reverse('client_app:taskrun_list'))
        self.assertNotContains(response, 'Only failed or stalled tasks can be resumed.')

# Create your tests here.

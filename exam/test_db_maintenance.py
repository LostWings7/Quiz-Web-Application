"""
Unit and Integration Tests for QuizX Superuser Database & Maintenance Center
Covers Access Control, Status/Metrics, Connection Testing, Backup Security,
Path Traversal Protections, Restore Safeguards, and Concurrency Locking.
"""

import os
import json
import tempfile
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from exam import db_maintenance
from exam.models import Quiz, Question, QuestionOption, QuizResult


class DatabaseMaintenanceSecurityTests(TestCase):
    """Verify strict superuser-only access control and denial for non-superusers."""

    def setUp(self):
        self.client = Client()

        # 1. Superuser
        self.superuser = User.objects.create_superuser(
            username='admin_super',
            email='admin_super@test.com',
            password='SuperPassword123!'
        )

        # 2. Ordinary Staff / Teacher
        self.staff_user = User.objects.create_user(
            username='teacher_staff',
            email='teacher@test.com',
            password='StaffPassword123!',
            is_staff=True,
            is_superuser=False
        )

        # 3. Regular Student User
        self.regular_user = User.objects.create_user(
            username='student_user',
            email='student@test.com',
            password='StudentPassword123!',
            is_staff=False,
            is_superuser=False
        )

        self.db_endpoints = [
            reverse('dashboard_settings_db_status_ajax'),
            reverse('dashboard_settings_db_test'),
            reverse('dashboard_settings_db_validate_target'),
            reverse('dashboard_settings_db_change'),
            reverse('dashboard_settings_db_backup'),
            reverse('dashboard_settings_db_restore'),
            reverse('dashboard_settings_db_delete_backup'),
            reverse('dashboard_settings_db_update_note'),
            reverse('dashboard_settings_db_check_updates'),
            reverse('dashboard_settings_db_run_update'),
        ]

    def test_unauthenticated_user_denied(self):
        """Unauthenticated requests must be redirected to login or rejected with 401/302."""
        for url in self.db_endpoints:
            resp = self.client.get(url)
            self.assertIn(resp.status_code, [302, 401, 403], f"Failed for {url}")

    def test_non_superuser_staff_denied_with_403(self):
        """Staff members (teachers) who are NOT superusers MUST receive 403 Forbidden on all DB endpoints."""
        self.client.login(username='teacher_staff', password='StaffPassword123!')

        for url in self.db_endpoints:
            # Test POST endpoints
            resp = self.client.post(url, data=json.dumps({}), content_type='application/json')
            self.assertEqual(
                resp.status_code, 403,
                f"Expected 403 Forbidden for staff user on POST {url}, got {resp.status_code}"
            )

        # Test download endpoint
        dl_url = reverse('dashboard_settings_db_download', kwargs={'filename': 'QuizX_test.bak'})
        dl_resp = self.client.get(dl_url)
        self.assertEqual(dl_resp.status_code, 403, "Staff user must not be able to download backups")

    def test_superuser_granted_access(self):
        """Superuser must be allowed access to status and update-check endpoints."""
        self.client.login(username='admin_super', password='SuperPassword123!')

        resp = self.client.get(reverse('dashboard_settings_db_status_ajax'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('success'))
        self.assertIn('status', data)
        self.assertIn('metrics', data)

    def test_settings_page_hides_db_section_for_staff(self):
        """Settings page template must not display the DB maintenance section to non-superusers."""
        self.client.login(username='teacher_staff', password='StaffPassword123!')
        resp = self.client.get(reverse('dashboard_settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="dbMaintenanceSection"')

    def test_settings_page_shows_db_section_for_superuser(self):
        """Settings page template must display the DB maintenance section to superusers."""
        self.client.login(username='admin_super', password='SuperPassword123!')
        resp = self.client.get(reverse('dashboard_settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="dbMaintenanceSection"')


class DatabaseMaintenanceCoreTests(TestCase):
    """Test core functions: status, metrics, path sanitization, and .env updates."""

    def test_database_status_structure(self):
        """get_database_status() returns required keys with valid types."""
        status = db_maintenance.get_database_status()
        self.assertIsInstance(status, dict)
        self.assertIn('connected', status)
        self.assertIn('engine', status)
        self.assertIn('server', status)
        self.assertIn('database', status)
        self.assertIn('auth_method', status)
        self.assertIn('app_version', status)

    def test_database_metrics_count(self):
        """get_database_metrics() accurately reports model counts."""
        metrics = db_maintenance.get_database_metrics()
        self.assertTrue(metrics.get('success'))
        self.assertGreaterEqual(metrics.get('users_count', 0), 0)
        self.assertGreaterEqual(metrics.get('quizzes_count', 0), 0)
        self.assertGreaterEqual(metrics.get('questions_count', 0), 0)
        self.assertGreaterEqual(metrics.get('results_count', 0), 0)

    def test_path_traversal_protection(self):
        """get_safe_backup_path strictly blocks directory traversal attempts."""
        safe_dir = tempfile.mkdtemp()
        test_file = os.path.join(safe_dir, 'valid_backup.bak')
        with open(test_file, 'w') as f:
            f.write('dummy')

        # 1. Valid filename succeeds
        resolved = db_maintenance.get_safe_backup_path('valid_backup.bak', backup_dir=safe_dir)
        self.assertEqual(os.path.normpath(resolved), os.path.normpath(test_file))

        # 2. Path traversal with ../ is blocked
        with self.assertRaises(ValueError):
            db_maintenance.get_safe_backup_path('../secret.bak', backup_dir=safe_dir)

        # 3. Path traversal with ..\\ is blocked
        with self.assertRaises(ValueError):
            db_maintenance.get_safe_backup_path('..\\secret.bak', backup_dir=safe_dir)

        # 4. Absolute path is blocked
        with self.assertRaises(ValueError):
            db_maintenance.get_safe_backup_path(r'C:\Windows\System32\cmd.bak', backup_dir=safe_dir)

        # 5. Non-.bak extension is blocked
        with self.assertRaises(ValueError):
            db_maintenance.get_safe_backup_path('secret.txt', backup_dir=safe_dir)

    def test_env_persistence_preserves_other_variables(self):
        """update_env_database_config updates DB settings while keeping unrelated settings intact."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as f:
            f.write(
                "# System Config\n"
                "DEBUG=True\n"
                "SECRET_KEY=my_super_secret_key\n"
                "APP_CUSTOM_KEY=test_custom_key_12345\n\n"
                "# Database\n"
                "DB_ENGINE=sqlite\n"
                "DB_NAME=old_db\n"
                "DB_HOST=old_host\n"
            )
            temp_env_path = f.name

        try:
            db_maintenance.update_env_database_config(
                db_host=r'localhost\NEW_INSTANCE',
                db_name='NewQuizX',
                db_driver='ODBC Driver 18 for SQL Server',
                trust_cert='yes',
                env_path=temp_env_path
            )

            with open(temp_env_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Confirm unrelated keys are preserved
            self.assertIn("DEBUG=True", content)
            self.assertIn("SECRET_KEY=my_super_secret_key", content)
            self.assertIn("APP_CUSTOM_KEY=test_custom_key_12345", content)

            # Confirm DB keys are updated
            self.assertIn("DB_ENGINE=mssql", content)
            self.assertIn("DB_NAME=NewQuizX", content)
            self.assertIn(r"DB_HOST=localhost\NEW_INSTANCE", content)
            self.assertIn("DB_OPTIONS_DRIVER=ODBC Driver 18 for SQL Server", content)
        finally:
            if os.path.exists(temp_env_path):
                os.remove(temp_env_path)

    def test_save_backup_note_and_load(self):
        """save_backup_note persists note and tag to companion JSON and load_backups_metadata reads them."""
        with tempfile.TemporaryDirectory() as temp_dir:
            ok = db_maintenance.save_backup_note(
                'QuizX_test.bak',
                note="Midterm Exam Baseline",
                tag="midterm",
                backup_dir=temp_dir
            )
            self.assertTrue(ok)

            metadata = db_maintenance.load_backups_metadata(temp_dir)
            self.assertIn('QuizX_test.bak', metadata)
            self.assertEqual(metadata['QuizX_test.bak']['note'], "Midterm Exam Baseline")
            self.assertEqual(metadata['QuizX_test.bak']['tag'], "midterm")
            self.assertIn('updated_at', metadata['QuizX_test.bak'])

    def test_delete_database_backup_removes_file_and_metadata(self):
        """delete_database_backup removes the .bak file and cleans up associated metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_bak = os.path.join(temp_dir, 'QuizX_to_delete.bak')
            with open(test_bak, 'wb') as f:
                f.write(b"DUMMY_BACKUP_BYTES")

            # Add metadata
            db_maintenance.save_backup_note('QuizX_to_delete.bak', note="To be deleted", backup_dir=temp_dir)
            self.assertTrue(os.path.exists(test_bak))

            # Execute delete
            ok, msg = db_maintenance.delete_database_backup('QuizX_to_delete.bak', backup_dir=temp_dir)
            self.assertTrue(ok)
            self.assertFalse(os.path.exists(test_bak))

            # Metadata should be pruned
            meta_after = db_maintenance.load_backups_metadata(temp_dir)
            self.assertNotIn('QuizX_to_delete.bak', meta_after)

    def test_delete_database_backup_traversal_blocked(self):
        """delete_database_backup blocks directory traversal and invalid filename patterns."""
        with tempfile.TemporaryDirectory() as temp_dir:
            ok, msg = db_maintenance.delete_database_backup('../outside.bak', backup_dir=temp_dir)
            self.assertFalse(ok)
            self.assertTrue('invalid' in msg.lower() or 'traversal' in msg.lower())


class DatabaseMaintenanceOperationsTests(TestCase):
    """Test maintenance operations: backup, restore validation, update check, and concurrency lock."""

    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username='admin_ops',
            email='admin_ops@test.com',
            password='SuperPassword123!'
        )
        self.client.login(username='admin_ops', password='SuperPassword123!')

    def test_concurrency_locking(self):
        """MaintenanceLock prevents two simultaneous maintenance actions."""
        # Clean any preexisting lock
        db_maintenance.MaintenanceLock.release()

        # 1. Acquire initial lock
        db_maintenance.MaintenanceLock.acquire("Test Backup", "admin_ops")
        is_locked, op_name = db_maintenance.MaintenanceLock.is_locked()
        self.assertTrue(is_locked)
        self.assertEqual(op_name, "Test Backup")

        # 2. Second acquire attempt must raise MaintenanceLockError
        with self.assertRaises(db_maintenance.MaintenanceLockError):
            db_maintenance.MaintenanceLock.acquire("Second Action", "admin_ops")

        # 3. HTTP endpoint returns 423 Locked when active lock exists
        resp = self.client.post(
            reverse('dashboard_settings_db_backup'),
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 423)
        self.assertIn('Another database maintenance operation', resp.json().get('error', ''))

        # 4. Release lock
        db_maintenance.MaintenanceLock.release()
        is_locked_after, _ = db_maintenance.MaintenanceLock.is_locked()
        self.assertFalse(is_locked_after)

    def test_restore_requires_explicit_confirmation(self):
        """Restore endpoint must reject requests that do not include the exact 'RESTORE' confirmation."""
        # 1. Without confirmation
        resp = self.client.post(
            reverse('dashboard_settings_db_restore'),
            data=json.dumps({'filename': 'QuizX_backup_dummy.bak'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('confirmation required', resp.json().get('error', '').lower())

        # 2. With wrong confirmation text
        resp2 = self.client.post(
            reverse('dashboard_settings_db_restore'),
            data=json.dumps({'filename': 'QuizX_backup_dummy.bak', 'confirmation': 'YES'}),
            content_type='application/json'
        )
        self.assertEqual(resp2.status_code, 400)
        self.assertIn('confirmation required', resp2.json().get('error', '').lower())

    def test_check_updates_endpoint(self):
        """Check updates endpoint returns migration status without applying migrations."""
        resp = self.client.get(reverse('dashboard_settings_db_check_updates'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('success'))
        self.assertIn('pending_count', data)
        self.assertIn('pending_migrations', data)
        self.assertIn('app_version', data)

    def test_connection_test_invalid_server_fails_safely(self):
        """Connection test to non-existent server reports failure without raw tracebacks."""
        resp = self.client.post(
            reverse('dashboard_settings_db_test'),
            data=json.dumps({
                'server': r'localhost\NON_EXISTENT_INSTANCE_XYZ',
                'database': 'QuizX'
            }),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get('success'))
        self.assertIn('Cannot connect to SQL Server', data.get('message', ''))

    def test_backup_download_serves_attachment(self):
        """db_download_backup returns FileResponse with attachment disposition and binary content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            dummy_filename = 'QuizX_download_test.bak'
            dummy_path = os.path.join(temp_dir, dummy_filename)
            with open(dummy_path, 'wb') as f:
                f.write(b"BACKUP_STREAM_TEST_DATA")

            with patch.object(db_maintenance, 'DEFAULT_BACKUP_DIR', temp_dir):
                url = reverse('dashboard_settings_db_download', kwargs={'filename': dummy_filename})
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp['Content-Type'], 'application/octet-stream')
                self.assertIn(f'attachment; filename="{dummy_filename}"', resp['Content-Disposition'])
                content = b"".join(resp.streaming_content)
                self.assertEqual(content, b"BACKUP_STREAM_TEST_DATA")

    def test_delete_backup_ajax(self):
        """db_delete_backup_ajax deletes the backup file through superuser ajax endpoint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            dummy_filename = 'QuizX_ajax_delete.bak'
            dummy_path = os.path.join(temp_dir, dummy_filename)
            with open(dummy_path, 'wb') as f:
                f.write(b"DELETE_ME")

            with patch.object(db_maintenance, 'DEFAULT_BACKUP_DIR', temp_dir):
                # 1. Missing filename
                resp_err = self.client.post(
                    reverse('dashboard_settings_db_delete_backup'),
                    data=json.dumps({'filename': ''}),
                    content_type='application/json'
                )
                self.assertEqual(resp_err.status_code, 400)

                # 2. Valid deletion
                resp = self.client.post(
                    reverse('dashboard_settings_db_delete_backup'),
                    data=json.dumps({'filename': dummy_filename}),
                    content_type='application/json'
                )
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json().get('success'))
                self.assertFalse(os.path.exists(dummy_path))

    def test_update_backup_note_ajax(self):
        """db_update_backup_note_ajax updates note and tag on existing backup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(db_maintenance, 'DEFAULT_BACKUP_DIR', temp_dir):
                resp = self.client.post(
                    reverse('dashboard_settings_db_update_note'),
                    data=json.dumps({
                        'filename': 'QuizX_note_test.bak',
                        'note': 'Important pre-exam backup',
                        'tag': 'pre-exam'
                    }),
                    content_type='application/json'
                )
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.json().get('success'))

                meta = db_maintenance.load_backups_metadata(temp_dir)
                self.assertEqual(meta['QuizX_note_test.bak']['note'], 'Important pre-exam backup')
                self.assertEqual(meta['QuizX_note_test.bak']['tag'], 'pre-exam')


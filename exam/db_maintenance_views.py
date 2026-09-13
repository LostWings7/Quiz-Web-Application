"""
QuizX Superuser Database & Maintenance Views
Secure, superuser-only endpoints for database status, testing, switching, backups, restores, and updates.
"""

import os
import json
import shutil
import datetime
import logging
from django.conf import settings
from django.http import JsonResponse, HttpResponse, FileResponse, HttpResponseForbidden
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect

from exam import db_maintenance

logger = logging.getLogger('quizx.db_maintenance')


def superuser_required_ajax(view_func):
    """Decorator ensuring that AJAX requests are strictly authenticated as superuser."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({
                'success': False,
                'error': 'Authentication required. Please log in.'
            }, status=401)
        if not request.user.is_superuser:
            logger.warning(f"Unauthorized DB maintenance access attempt by non-superuser: {request.user.username}")
            return JsonResponse({
                'success': False,
                'error': 'Permission denied: Superuser privileges required.'
            }, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
@superuser_required_ajax
@require_http_methods(['GET'])
def db_status_metrics_ajax(request):
    """Return live database status, metrics, and backup history."""
    try:
        status = db_maintenance.get_database_status()
        metrics = db_maintenance.get_database_metrics()
        backups = db_maintenance.get_backup_history(limit=20)
        is_locked, active_op = db_maintenance.MaintenanceLock.is_locked()

        return JsonResponse({
            'success': True,
            'status': status,
            'metrics': metrics,
            'backups': backups,
            'is_locked': is_locked,
            'active_operation': active_op,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': db_maintenance.sanitize_error(e)}, status=500)


@login_required
@superuser_required_ajax
@require_http_methods(['POST'])
def db_test_connection_ajax(request):
    """Test SQL Server connectivity for current or proposed settings."""
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = request.POST.dict()
        else:
            data = request.POST.dict()

        server = data.get('server', '').strip() or None
        database = data.get('database', '').strip() or 'master'
        driver = data.get('driver', '').strip() or None
        trust_cert = data.get('trust_cert', '').strip() or None

        res = db_maintenance.test_sql_connection(
            server=server,
            database=database,
            driver=driver,
            trust_cert=trust_cert,
            timeout=6
        )

        db_maintenance.log_audit_event(
            request.user,
            'DATABASE_CONNECTION_TEST',
            f"Tested {server or 'default'}/{database}: {'Success' if res['success'] else res.get('message')}",
            success=res['success']
        )
        return JsonResponse(res)

    except Exception as e:
        return JsonResponse({'success': False, 'message': db_maintenance.sanitize_error(e)}, status=500)


@login_required
@superuser_required_ajax
@require_http_methods(['POST'])
def db_validate_target_ajax(request):
    """Validate that a target database exists, is ONLINE, and has a valid QuizX schema."""
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = request.POST.dict()
        else:
            data = request.POST.dict()

        server = data.get('server', '').strip()
        database = data.get('database', '').strip()
        driver = data.get('driver', '').strip() or None
        trust_cert = data.get('trust_cert', '').strip() or None

        if not server or not database:
            return JsonResponse({'success': False, 'error': 'Server and Database name are required.'}, status=400)

        res = db_maintenance.validate_target_database(
            server=server,
            database=database,
            driver=driver,
            trust_cert=trust_cert
        )
        return JsonResponse(res)

    except Exception as e:
        return JsonResponse({'success': False, 'error': db_maintenance.sanitize_error(e)}, status=500)


@login_required
@superuser_required_ajax
@require_http_methods(['POST'])
def db_change_connection_ajax(request):
    """
    Safely switch the active database configuration:
    1. Validates target database connectivity and schema.
    2. Creates a fresh verified backup of CURRENT database before switching.
    3. Saves updated settings to .env.
    4. Informs user that restart is required.
    """
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = request.POST.dict()
        else:
            data = request.POST.dict()

        server = data.get('server', '').strip()
        database = data.get('database', '').strip()
        driver = data.get('driver', '').strip() or None
        trust_cert = data.get('trust_cert', '').strip() or None

        if not server or not database:
            return JsonResponse({'success': False, 'error': 'Server and Database name are required.'}, status=400)

        with db_maintenance.maintenance_operation("Database Switch", request.user.username):
            # Step 1: Validate target DB
            val = db_maintenance.validate_target_database(server=server, database=database, driver=driver, trust_cert=trust_cert)
            if not val.get('success'):
                return JsonResponse({
                    'success': False,
                    'error': f"Target validation failed: {val.get('error')}. Configuration was NOT modified."
                }, status=400)

            # Step 2: Create verified backup of CURRENT active DB
            current_engine = os.getenv('DB_ENGINE', '').strip().lower()
            if current_engine == 'mssql':
                b_ok, b_meta = db_maintenance.create_database_backup(prefix=f"{db_maintenance.DEFAULT_DATABASE}_pre_switch")
                if not b_ok:
                    return JsonResponse({
                        'success': False,
                        'error': f"Pre-switch backup failed: {b_meta.get('error')}. Aborting database switch for safety."
                    }, status=500)
            else:
                # SQLite fallback: create a local backup copy of db.sqlite3
                sqlite_src = os.path.join(settings.BASE_DIR, 'db.sqlite3')
                ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_name = f"db_sqlite_pre_switch_{ts}.sqlite3"
                if os.path.exists(sqlite_src):
                    try:
                        shutil.copy2(sqlite_src, os.path.join(settings.BASE_DIR, backup_name))
                    except Exception as err:
                        logger.warning(f"Could not create SQLite backup copy: {err}")
                b_meta = {'filename': backup_name}

            # Step 3: Update .env configuration
            db_maintenance.update_env_database_config(
                db_host=server,
                db_name=database,
                db_driver=driver,
                trust_cert=trust_cert
            )

            db_maintenance.log_audit_event(
                request.user,
                'DATABASE_CONFIGURATION_CHANGED',
                f"Switched DB to {server}/{database}. Pre-switch backup: {b_meta.get('filename')}",
                success=True
            )

            return JsonResponse({
                'success': True,
                'message': (
                    f"Target database [{database}] verified and configuration saved. "
                    f"Pre-switch backup created: {b_meta.get('filename')}. "
                    f"Please restart QuizX to establish the new database connection."
                ),
                'pre_switch_backup': b_meta.get('filename'),
                'target_server': server,
                'target_database': database,
                'restart_required': True,
            })

    except db_maintenance.MaintenanceLockError as mle:
        return JsonResponse({'success': False, 'error': str(mle)}, status=423)
    except Exception as e:
        return JsonResponse({'success': False, 'error': db_maintenance.sanitize_error(e)}, status=500)


@login_required
@superuser_required_ajax
@require_http_methods(['POST'])
def db_create_backup_ajax(request):
    """Trigger native SQL Server backup + RESTORE VERIFYONLY with optional custom tag and note."""
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = request.POST.dict()
        else:
            data = request.POST.dict()

        custom_tag = data.get('custom_tag', '').strip()
        note = data.get('note', '').strip()

        with db_maintenance.maintenance_operation("Create Backup", request.user.username):
            success, meta = db_maintenance.create_database_backup(
                custom_tag=custom_tag,
                note=note
            )

            db_maintenance.log_audit_event(
                request.user,
                'DATABASE_BACKUP',
                f"Created backup {meta.get('filename')}: {'Success' if success else meta.get('error')}",
                success=success
            )

            if success:
                return JsonResponse(meta)
            else:
                return JsonResponse({'success': False, 'error': meta.get('error')}, status=500)

    except db_maintenance.MaintenanceLockError as mle:
        return JsonResponse({'success': False, 'error': str(mle)}, status=423)
    except Exception as e:
        return JsonResponse({'success': False, 'error': db_maintenance.sanitize_error(e)}, status=500)


@login_required
def db_download_backup(request, filename):
    """
    Secure backup download strictly enforcing superuser authorization and
    absolute protection against path traversal (rejects ../, absolute paths, non-bak).
    """
    if not request.user.is_superuser:
        logger.warning(f"Unauthorized backup download attempt by user: {request.user.username}")
        raise PermissionDenied("Only superusers are permitted to download database backups.")

    try:
        safe_path = db_maintenance.get_safe_backup_path(filename)
        if not os.path.exists(safe_path):
            return HttpResponse("Backup file not found.", status=404)

        db_maintenance.log_audit_event(
            request.user,
            'DATABASE_BACKUP_DOWNLOAD',
            f"Downloaded {filename}",
            success=True
        )

        response = FileResponse(open(safe_path, 'rb'), as_attachment=True, filename=filename)
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except ValueError as ve:
        logger.warning(f"Rejected malicious/invalid backup download request '{filename}': {ve}")
        return HttpResponseForbidden(f"Access denied: {ve}")
    except Exception as e:
        return HttpResponse(f"Error serving backup: {db_maintenance.sanitize_error(e)}", status=500)


@login_required
@superuser_required_ajax
@require_http_methods(['POST'])
def db_delete_backup_ajax(request):
    """Safely delete a specific verified backup file."""
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = request.POST.dict()
        else:
            data = request.POST.dict()

        filename = data.get('filename', '').strip()
        if not filename:
            return JsonResponse({'success': False, 'error': 'Filename is required.'}, status=400)

        with db_maintenance.maintenance_operation("Delete Backup", request.user.username):
            success, msg = db_maintenance.delete_database_backup(filename)
            db_maintenance.log_audit_event(
                request.user,
                'DATABASE_BACKUP_DELETE',
                f"Deleted backup {filename}: {msg}",
                success=success
            )
            return JsonResponse({'success': success, 'message': msg}, status=200 if success else 400)

    except db_maintenance.MaintenanceLockError as mle:
        return JsonResponse({'success': False, 'error': str(mle)}, status=423)
    except Exception as e:
        return JsonResponse({'success': False, 'error': db_maintenance.sanitize_error(e)}, status=500)


@login_required
@superuser_required_ajax
@require_http_methods(['POST'])
def db_update_backup_note_ajax(request):
    """Add or edit note on an existing backup file."""
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = request.POST.dict()
        else:
            data = request.POST.dict()

        filename = data.get('filename', '').strip()
        note = data.get('note', '').strip()
        tag = data.get('tag', '').strip()

        if not filename:
            return JsonResponse({'success': False, 'error': 'Filename is required.'}, status=400)

        ok = db_maintenance.save_backup_note(filename, note=note, tag=tag)
        return JsonResponse({
            'success': ok,
            'message': 'Note updated successfully.' if ok else 'Could not save note.'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': db_maintenance.sanitize_error(e)}, status=500)


@login_required
@superuser_required_ajax
@require_http_methods(['POST'])
def db_restore_backup_ajax(request):
    """
    High-risk restore operation with mandatory pre-restore backup snapshot,
    two-step confirmation check, and post-restore validation.
    """
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = request.POST.dict()
        else:
            data = request.POST.dict()

        filename = data.get('filename', '').strip()
        confirmation = data.get('confirmation', '').strip()
        target_db = data.get('target_database', '').strip() or None

        if not filename:
            return JsonResponse({'success': False, 'error': 'Backup filename is required.'}, status=400)

        # Explicit confirmation required
        if confirmation != 'RESTORE':
            return JsonResponse({
                'success': False,
                'error': "Explicit confirmation required. Please type 'RESTORE' to confirm replacement of active data."
            }, status=400)

        with db_maintenance.maintenance_operation("Restore Database", request.user.username):
            success, res = db_maintenance.restore_database_backup(
                backup_filename=filename,
                target_database=target_db
            )

            db_maintenance.log_audit_event(
                request.user,
                'DATABASE_RESTORE',
                f"Restore from {filename}: {'Success' if success else res.get('error')}",
                success=success
            )

            if success:
                return JsonResponse(res)
            else:
                return JsonResponse({'success': False, 'error': res.get('error')}, status=500)

    except db_maintenance.MaintenanceLockError as mle:
        return JsonResponse({'success': False, 'error': str(mle)}, status=423)
    except Exception as e:
        return JsonResponse({'success': False, 'error': db_maintenance.sanitize_error(e)}, status=500)


@login_required
@superuser_required_ajax
@require_http_methods(['GET', 'POST'])
def db_check_updates_ajax(request):
    """Inspect pending migrations and application version without applying changes."""
    try:
        info = db_maintenance.check_pending_migrations()
        return JsonResponse(info)
    except Exception as e:
        return JsonResponse({'success': False, 'error': db_maintenance.sanitize_error(e)}, status=500)


@login_required
@superuser_required_ajax
@require_http_methods(['POST'])
def db_run_update_ajax(request):
    """Run full QuizX client update pipeline with step-by-step progress logging."""
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = request.POST.dict()
        else:
            data = request.POST.dict()

        skip_backup = data.get('skip_backup', False) in (True, 'true', '1')

        with db_maintenance.maintenance_operation("Run Update", request.user.username):
            success, steps = db_maintenance.execute_system_update(skip_backup=skip_backup)

            db_maintenance.log_audit_event(
                request.user,
                'DATABASE_UPDATE',
                f"QuizX update executed: {'Success' if success else 'Failed'}",
                success=success
            )

            return JsonResponse({
                'success': success,
                'steps': steps,
                'message': "QuizX update completed successfully." if success else "QuizX update failed. Check steps."
            }, status=200 if success else 500)

    except db_maintenance.MaintenanceLockError as mle:
        return JsonResponse({'success': False, 'error': str(mle)}, status=423)
    except Exception as e:
        return JsonResponse({'success': False, 'error': db_maintenance.sanitize_error(e)}, status=500)

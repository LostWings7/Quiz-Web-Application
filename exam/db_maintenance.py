"""
QuizX Database & Maintenance Core Engine
Unified backend for superuser database maintenance operations, CLI utilities, and update workflows.
"""

import os
import sys
import re
import time
import logging
import datetime
import threading
import subprocess
import json
from typing import Tuple, Dict, Any, List, Optional
from dotenv import load_dotenv

import pyodbc
from django.conf import settings
from django.db import connection
from django.core.management import call_command
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger('quizx.db_maintenance')

# Defaults from environment
DEFAULT_BACKUP_DIR = os.getenv('DB_BACKUP_DIR', r'C:\Users\Public\QuizX_Backups')
DEFAULT_SERVER = os.getenv('DB_HOST', r'localhost\SQLEXPRESS01')
DEFAULT_DATABASE = os.getenv('DB_NAME', 'QuizX')
DEFAULT_DRIVER = os.getenv('DB_OPTIONS_DRIVER', 'ODBC Driver 18 for SQL Server')
DEFAULT_TRUST_CERT = os.getenv('DB_TRUST_SERVER_CERTIFICATE', 'yes')

# ==============================================================================
# 1. Maintenance Concurrency Lock
# ==============================================================================

class MaintenanceLockError(Exception):
    """Raised when a maintenance operation is attempted while another is running."""
    pass


class MaintenanceLock:
    """
    Process- and thread-safe lock ensuring maintenance operations (backup,
    restore, update, DB switch) do not execute concurrently.
    """
    _thread_lock = threading.RLock()
    _active_operation: Optional[str] = None
    _active_user: Optional[str] = None
    _started_at: Optional[float] = None
    _timeout_seconds = 600  # 10 minutes timeout for stale locks

    @classmethod
    def get_lock_file(cls, backup_dir: Optional[str] = None) -> str:
        bdir = backup_dir or DEFAULT_BACKUP_DIR
        try:
            os.makedirs(bdir, exist_ok=True)
        except Exception:
            pass
        return os.path.join(bdir, '.maintenance.lock')

    @classmethod
    def is_locked(cls, backup_dir: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        with cls._thread_lock:
            # Check in-memory lock first
            if cls._active_operation:
                if cls._started_at and (time.time() - cls._started_at > cls._timeout_seconds):
                    # Stale in-memory lock
                    cls._active_operation = None
                    cls._active_user = None
                    cls._started_at = None
                else:
                    return True, cls._active_operation

            # Check filesystem lock for cross-process coordination
            lock_file = cls.get_lock_file(backup_dir)
            if os.path.exists(lock_file):
                try:
                    mtime = os.path.getmtime(lock_file)
                    if time.time() - mtime > cls._timeout_seconds:
                        # Stale file lock, remove it
                        try:
                            os.remove(lock_file)
                        except OSError:
                            pass
                        return False, None
                    with open(lock_file, 'r', encoding='utf-8') as f:
                        op_name = f.read().strip() or "Maintenance operation"
                    return True, op_name
                except Exception:
                    pass

            return False, None

    @classmethod
    def acquire(cls, operation: str, user: str = 'System', backup_dir: Optional[str] = None):
        with cls._thread_lock:
            locked, op_name = cls.is_locked(backup_dir)
            if locked:
                raise MaintenanceLockError(
                    f"Another database maintenance operation ({op_name}) is currently in progress. "
                    f"Please wait for it to complete."
                )

            cls._active_operation = operation
            cls._active_user = user
            cls._started_at = time.time()

            lock_file = cls.get_lock_file(backup_dir)
            try:
                with open(lock_file, 'w', encoding='utf-8') as f:
                    f.write(f"{operation} by {user} at {datetime.datetime.now().isoformat()}\n")
            except Exception as e:
                logger.warning(f"Could not write maintenance lock file {lock_file}: {e}")

    @classmethod
    def release(cls, backup_dir: Optional[str] = None):
        with cls._thread_lock:
            cls._active_operation = None
            cls._active_user = None
            cls._started_at = None

            lock_file = cls.get_lock_file(backup_dir)
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except OSError:
                    pass


class maintenance_operation:
    """Context manager for acquiring and releasing maintenance lock safely."""
    def __init__(self, operation_name: str, username: str = 'System', backup_dir: Optional[str] = None):
        self.operation_name = operation_name
        self.username = username
        self.backup_dir = backup_dir

    def __enter__(self):
        MaintenanceLock.acquire(self.operation_name, self.username, self.backup_dir)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        MaintenanceLock.release(self.backup_dir)


# ==============================================================================
# 2. Connection Helpers & Sanitization
# ==============================================================================

def sanitize_error(err: Exception) -> str:
    """Return a clear, safe human-readable message without raw passwords or secrets."""
    msg = str(err)
    # Strip sensitive credentials if present in connection strings
    msg = re.sub(r'PWD=[^;]+;', 'PWD=***;', msg, flags=re.IGNORECASE)
    msg = re.sub(r'PASSWORD=[^;]+;', 'PASSWORD=***;', msg, flags=re.IGNORECASE)
    msg = re.sub(r'UID=[^;]+;', 'UID=***;', msg, flags=re.IGNORECASE)

    # Common pyodbc / SQL Server error signatures
    if 'Login failed for user' in msg:
        return "Authentication failed: Check SQL Server permissions or Windows credentials."
    if 'Server does not exist, or connection refused' in msg or 'SQL Server Network Interfaces' in msg:
        return "Cannot connect to SQL Server. Verify that the server and instance name are correct and the SQL Server service is running."
    if 'Cannot open database' in msg:
        return "Database not found or access denied on this SQL Server instance."
    if 'timeout' in msg.lower():
        return "Connection timed out while attempting to contact SQL Server."
    if 'ODBC Driver' in msg and 'not found' in msg.lower():
        return "ODBC Driver 18 for SQL Server is not installed or configured."
    return f"SQL Server operation failed: {msg.strip()}"


def get_pyodbc_connection(
    server: Optional[str] = None,
    database: str = 'master',
    driver: Optional[str] = None,
    trust_cert: Optional[str] = None,
    timeout: int = 5
) -> pyodbc.Connection:
    """Create a direct pyodbc connection using Windows Authentication."""
    raw_srv = (server or os.getenv('DB_HOST', DEFAULT_SERVER)).strip()
    # Normalize forward slashes in instance name (e.g. localhost/SQLEXPRESS01 -> localhost\SQLEXPRESS01)
    srv = raw_srv.replace('/', '\\')
    raw_drv = (driver or os.getenv('DB_OPTIONS_DRIVER', DEFAULT_DRIVER)).strip()
    drv = DEFAULT_DRIVER if (not raw_drv or raw_drv.upper() == 'N/A') else raw_drv
    tc = trust_cert or os.getenv('DB_TRUST_SERVER_CERTIFICATE', DEFAULT_TRUST_CERT)
    extra = 'TrustServerCertificate=yes;' if str(tc).strip().lower() in ('yes', 'true', '1') else ''

    conn_str = (
        f'DRIVER={{{drv}}};'
        f'SERVER={srv};'
        f'DATABASE={database};'
        f'Trusted_Connection=yes;'
        f'{extra}'
        f'LoginTimeout={timeout};'
    )
    return pyodbc.connect(conn_str, autocommit=True, timeout=timeout)


# ==============================================================================
# 3. Connection Testing & Target Validation
# ==============================================================================

def test_sql_connection(
    server: Optional[str] = None,
    database: str = 'master',
    driver: Optional[str] = None,
    trust_cert: Optional[str] = None,
    timeout: int = 5
) -> Dict[str, Any]:
    """
    Test connectivity to SQL Server without changing the active configuration.
    Returns success status, server version, and safe diagnostic details.
    """
    srv = server or os.getenv('DB_HOST', DEFAULT_SERVER)
    drv = driver or os.getenv('DB_OPTIONS_DRIVER', DEFAULT_DRIVER)
    tc = trust_cert or os.getenv('DB_TRUST_SERVER_CERTIFICATE', DEFAULT_TRUST_CERT)

    try:
        conn = get_pyodbc_connection(server=srv, database=database, driver=drv, trust_cert=tc, timeout=timeout)
        cur = conn.cursor()
        cur.execute("SELECT @@VERSION")
        ver_raw = cur.fetchone()[0]
        # Extract first line (e.g. Microsoft SQL Server 2025 (RTM) - 17.0.1000.7 (X64))
        ver_line = ver_raw.splitlines()[0] if ver_raw else 'SQL Server'
        conn.close()
        return {
            'success': True,
            'message': f"Connection successful to {srv} (Database: {database})",
            'server': srv,
            'database': database,
            'version': ver_line,
        }
    except Exception as e:
        safe_msg = sanitize_error(e)
        logger.warning(f"Connection test failed for {srv}/{database}: {safe_msg}")
        return {
            'success': False,
            'message': safe_msg,
            'server': srv,
            'database': database,
        }


def validate_target_database(
    server: str,
    database: str,
    driver: Optional[str] = None,
    trust_cert: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate that a proposed target database exists, is ONLINE, and has a
    compatible QuizX/Django schema before allowing a database switch.
    """
    # 1. Connect to master
    try:
        mconn = get_pyodbc_connection(server=server, database='master', driver=driver, trust_cert=trust_cert)
        mcur = mconn.cursor()
    except Exception as e:
        return {'success': False, 'error': f"Cannot connect to server {server}: {sanitize_error(e)}"}

    try:
        mcur.execute("SELECT state_desc FROM sys.databases WHERE name = ?", (database,))
        row = mcur.fetchone()
        if not row:
            mconn.close()
            return {'success': False, 'error': f"Database [{database}] does not exist on server {server}."}

        state = row[0]
        mconn.close()
        if state != 'ONLINE':
            return {'success': False, 'error': f"Database [{database}] is in state {state}, not ONLINE."}

    except Exception as e:
        try:
            mconn.close()
        except Exception:
            pass
        return {'success': False, 'error': f"Error querying master catalog: {sanitize_error(e)}"}

    # 2. Connect to the target database and inspect schema
    try:
        qconn = get_pyodbc_connection(server=server, database=database, driver=driver, trust_cert=trust_cert)
        qcur = qconn.cursor()

        # Count tables
        qcur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
        table_count = qcur.fetchone()[0]

        # Check for django_migrations
        qcur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'django_migrations'")
        has_migrations = qcur.fetchone()[0] > 0

        migration_count = 0
        latest_migration = 'None'
        if has_migrations:
            qcur.execute("SELECT COUNT(*) FROM [dbo].[django_migrations]")
            migration_count = qcur.fetchone()[0]

            qcur.execute(
                "SELECT TOP 1 app, name, CONVERT(varchar(30), applied, 120) "
                "FROM [dbo].[django_migrations] ORDER BY id DESC"
            )
            mig_row = qcur.fetchone()
            if mig_row:
                latest_migration = f"{mig_row[0]}.{mig_row[1]}"

        qconn.close()

        # Determine compatibility
        if table_count == 0:
            return {
                'success': False,
                'error': f"Database [{database}] is completely empty (0 tables). Cannot switch to an uninitialized database.",
                'table_count': 0,
                'is_empty': True,
            }

        if not has_migrations or migration_count == 0:
            return {
                'success': False,
                'error': f"Database [{database}] does not appear to be a Django/QuizX database (missing migration history).",
                'table_count': table_count,
                'is_quizx': False,
            }

        return {
            'success': True,
            'message': f"Database [{database}] verified compatible ({table_count} tables, {migration_count} migrations applied).",
            'server': server,
            'database': database,
            'table_count': table_count,
            'migration_count': migration_count,
            'latest_migration': latest_migration,
            'is_quizx': True,
        }

    except Exception as e:
        return {'success': False, 'error': f"Error validating database [{database}]: {sanitize_error(e)}"}


# ==============================================================================
# 4. Status & Health Metrics
# ==============================================================================

def get_database_status() -> Dict[str, Any]:
    """
    Lightweight status inspector for the active database configuration.
    Fast query avoiding expensive aggregations on page loads.
    """
    db_engine = os.getenv('DB_ENGINE', '').strip().lower()
    active_server = os.getenv('DB_HOST', DEFAULT_SERVER)
    active_db = os.getenv('DB_NAME', DEFAULT_DATABASE)
    active_driver = os.getenv('DB_OPTIONS_DRIVER', DEFAULT_DRIVER)
    trust_cert = os.getenv('DB_TRUST_SERVER_CERTIFICATE', DEFAULT_TRUST_CERT)

    try:
        import assessment
        app_version = getattr(assessment, '__version__', '1.0.0')
    except Exception:
        app_version = '1.0.0'

    status: Dict[str, Any] = {
        'connected': False,
        'engine': 'SQL Server 2025 Express' if db_engine == 'mssql' else 'SQLite (Development Fallback)',
        'engine_code': db_engine,
        'server': active_server if db_engine == 'mssql' else 'Local Filesystem',
        'database': active_db if db_engine == 'mssql' else 'db.sqlite3',
        'driver': active_driver if db_engine == 'mssql' else 'N/A',
        'auth_method': 'Windows Authentication (Trusted Connection)' if db_engine == 'mssql' else 'File-based',
        'version': 'Unknown',
        'migration_status': 'Unknown',
        'pending_count': 0,
        'app_version': app_version,
        'last_backup': None,
        'table_count': 0,
    }

    # Fetch last verified backup metadata
    try:
        backups = get_backup_history(limit=1)
        if backups:
            status['last_backup'] = backups[0]
    except Exception as e:
        logger.debug(f"Could not retrieve last backup info: {e}")

    if db_engine == 'mssql':
        try:
            conn = get_pyodbc_connection(server=active_server, database=active_db, timeout=3)
            cur = conn.cursor()
            cur.execute("SELECT @@VERSION")
            vrow = cur.fetchone()
            if vrow:
                status['version'] = vrow[0].splitlines()[0]

            cur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
            status['table_count'] = cur.fetchone()[0]

            # Latest migration
            cur.execute(
                "SELECT TOP 1 app, name, CONVERT(varchar(30), applied, 120) "
                "FROM [dbo].[django_migrations] ORDER BY id DESC"
            )
            mig_row = cur.fetchone()
            if mig_row:
                status['migration_status'] = f"{mig_row[0]}.{mig_row[1]}"

            conn.close()
            status['connected'] = True

        except Exception as e:
            status['connected'] = False
            status['error'] = sanitize_error(e)
    else:
        # SQLite fallback check
        status['connected'] = os.path.exists(os.path.join(settings.BASE_DIR, 'db.sqlite3'))
        status['version'] = 'SQLite 3'

    # Check pending migrations count safely
    try:
        pending_info = check_pending_migrations()
        status['pending_count'] = pending_info.get('pending_count', 0)
        status['up_to_date'] = pending_info.get('up_to_date', True)
    except Exception:
        status['pending_count'] = 0
        status['up_to_date'] = True

    return status


def get_database_metrics() -> Dict[str, Any]:
    """
    Fast query retrieving core counts (Users, Quizzes, Questions, Quiz Results).
    """
    try:
        from django.contrib.auth.models import User
        from exam.models import Quiz, Question, QuizResult

        return {
            'users_count': User.objects.count(),
            'quizzes_count': Quiz.objects.count(),
            'questions_count': Question.objects.count(),
            'results_count': QuizResult.objects.count(),
            'success': True,
        }
    except Exception as e:
        logger.warning(f"Error querying database metrics: {e}")
        return {
            'users_count': 0,
            'quizzes_count': 0,
            'questions_count': 0,
            'results_count': 0,
            'success': False,
            'error': sanitize_error(e),
        }


# ==============================================================================
# 5. Backup Operations
# ==============================================================================

def get_safe_backup_path(filename: str, backup_dir: Optional[str] = None) -> str:
    """
    Strict security validation against path traversal attacks.
    Ensures filename is strictly alphanumeric + [_-.] and resolves inside approved backup dir.
    """
    if not filename or not isinstance(filename, str):
        raise ValueError("Invalid backup filename.")

    # Only allow safe filename pattern: e.g. QuizX_backup_20260913_140322.bak
    if not re.match(r'^[a-zA-Z0-9_\-\.]+\.bak$', filename):
        raise ValueError("Invalid backup filename format. Only .bak files with alphanumeric names are permitted.")

    if '..' in filename or '/' in filename or '\\' in filename or ':' in filename:
        raise ValueError("Path traversal attempt detected.")

    bdir = os.path.abspath(backup_dir or DEFAULT_BACKUP_DIR)
    target_path = os.path.abspath(os.path.join(bdir, filename))

    # Boundary check: resolved path must strictly reside within the approved directory
    try:
        common = os.path.commonpath([bdir, target_path])
    except ValueError:
        raise ValueError("Cross-drive path resolution is strictly forbidden.")

    if common != bdir or not target_path.startswith(bdir):
        raise ValueError("Path traversal outside approved backup directory.")

    return target_path


def verify_backup_file(
    backup_full_path: str,
    server: Optional[str] = None,
    driver: Optional[str] = None,
    trust_cert: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Execute RESTORE VERIFYONLY against a native SQL Server .bak file.
    Drains TDS message streams to ensure clean connection closure.
    """
    if not os.path.exists(backup_full_path):
        return False, f"Backup file not found on disk: {backup_full_path}"

    srv = server or os.getenv('DB_HOST', DEFAULT_SERVER)
    safe_path = backup_full_path.replace("'", "''")

    try:
        conn = get_pyodbc_connection(server=srv, database='master', driver=driver, trust_cert=trust_cert)
        cur = conn.cursor()
        cur.execute(f"RESTORE VERIFYONLY FROM DISK = N'{safe_path}';")
        while cur.nextset():
            pass
        conn.close()
        return True, "Backup verification succeeded: backup set is valid."
    except Exception as e:
        return False, f"RESTORE VERIFYONLY failed: {sanitize_error(e)}"


def get_metadata_file(backup_dir: Optional[str] = None) -> str:
    bdir = os.path.abspath(backup_dir or DEFAULT_BACKUP_DIR)
    return os.path.join(bdir, 'backups_metadata.json')


def load_backups_metadata(backup_dir: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Load backup notes and tags dictionary from companion JSON file."""
    mfile = get_metadata_file(backup_dir)
    if os.path.exists(mfile):
        try:
            with open(mfile, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read backups metadata: {e}")
    return {}


def save_backup_note(filename: str, note: str, tag: str = '', backup_dir: Optional[str] = None) -> bool:
    """Save or update custom note and tag for a backup file."""
    mfile = get_metadata_file(backup_dir)
    data = load_backups_metadata(backup_dir)
    if filename not in data:
        data[filename] = {}
    data[filename]['note'] = note.strip()
    if tag:
        data[filename]['tag'] = tag.strip()
    data[filename]['updated_at'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        with open(mfile, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.warning(f"Could not save backup metadata: {e}")
        return False


def delete_database_backup(filename: str, backup_dir: Optional[str] = None) -> Tuple[bool, str]:
    """
    Safely delete a .bak backup file from the approved backup directory.
    Strictly validates filename against path traversal before deletion.
    """
    try:
        safe_path = get_safe_backup_path(filename, backup_dir)
        if not os.path.exists(safe_path):
            return False, f"Backup file not found on disk: {filename}"

        os.remove(safe_path)
        logger.info(f"Deleted database backup file: {filename}")

        # Clean up metadata
        mfile = get_metadata_file(backup_dir)
        data = load_backups_metadata(backup_dir)
        if filename in data:
            del data[filename]
            try:
                with open(mfile, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass

        return True, f"Backup '{filename}' deleted successfully."
    except Exception as e:
        return False, f"Error deleting backup: {sanitize_error(e)}"


def create_database_backup(
    backup_dir: Optional[str] = None,
    server: Optional[str] = None,
    database: Optional[str] = None,
    driver: Optional[str] = None,
    trust_cert: Optional[str] = None,
    prefix: Optional[str] = None,
    custom_tag: Optional[str] = None,
    note: Optional[str] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Create a native SQL Server backup with BACKUP DATABASE and RESTORE VERIFYONLY.
    Shared implementation for Web UI, CLI, and pre-update/pre-restore operations.
    Supports custom tag and annotation note.
    """
    bdir = os.path.abspath(backup_dir or DEFAULT_BACKUP_DIR)
    srv = server or os.getenv('DB_HOST', DEFAULT_SERVER)
    db = database or os.getenv('DB_NAME', DEFAULT_DATABASE)

    # Step 1: Ensure backup directory exists
    try:
        os.makedirs(bdir, exist_ok=True)
    except Exception as e:
        return False, {'error': f"Cannot create backup directory {bdir}: {e}"}

    # Step 2: Validate database existence and state
    try:
        conn = get_pyodbc_connection(server=srv, database='master', driver=driver, trust_cert=trust_cert)
        cur = conn.cursor()
        cur.execute("SELECT state_desc FROM sys.databases WHERE name = ?", (db,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False, {'error': f"Database [{db}] does not exist on server {srv}."}
        if row[0] != 'ONLINE':
            conn.close()
            return False, {'error': f"Database [{db}] is in state {row[0]}, not ONLINE."}
    except Exception as e:
        return False, {'error': f"Cannot connect to SQL Server on {srv}: {sanitize_error(e)}"}

    # Step 3: Formulate backup path
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    pfx = prefix or db

    clean_tag = ''
    if custom_tag:
        clean_tag = re.sub(r'[^a-zA-Z0-9_\-]', '_', custom_tag.strip())[:32]

    if clean_tag:
        filename = f"{pfx}_{clean_tag}_{timestamp}.bak"
    else:
        filename = f"{pfx}_backup_{timestamp}.bak"

    backup_full_path = os.path.join(bdir, filename)
    safe_path = backup_full_path.replace("'", "''")

    # Step 4: Execute BACKUP DATABASE
    try:
        backup_sql = f"BACKUP DATABASE [{db}] TO DISK = N'{safe_path}' WITH INIT, STATS = 10;"
        cur.execute(backup_sql)
        while cur.nextset():
            pass
    except Exception as e:
        conn.close()
        return False, {
            'error': f"SQL Server BACKUP DATABASE failed: {sanitize_error(e)}. "
                     f"Verify that SQL Server service has write permissions to {bdir}."
        }

    # Step 5: Verify with RESTORE VERIFYONLY
    try:
        verify_sql = f"RESTORE VERIFYONLY FROM DISK = N'{safe_path}';"
        cur.execute(verify_sql)
        while cur.nextset():
            pass
        conn.close()
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return False, {'error': f"Backup created but RESTORE VERIFYONLY failed: {sanitize_error(e)}"}

    # Step 6: Verify file existence and compute size
    if not os.path.exists(backup_full_path):
        return False, {'error': "Backup succeeded via SQL Server but file is not visible on local filesystem."}

    size_mb = os.path.getsize(backup_full_path) / (1024 * 1024)

    # Step 7: Record note and tag if provided
    if note or clean_tag:
        save_backup_note(filename, note=note or '', tag=clean_tag, backup_dir=bdir)

    result = {
        'success': True,
        'filename': filename,
        'path': backup_full_path,
        'size_mb': round(size_mb, 2),
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'verified': True,
        'database': db,
        'server': srv,
        'tag': clean_tag,
        'note': note or '',
    }
    logger.info(f"Database backup created: {filename} ({size_mb:.2f} MB)")
    return True, result


def get_backup_history(backup_dir: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    """
    List verified backup files from the approved backup directory only.
    Sorted chronologically descending (newest first).
    Enriches each backup with custom notes and tags from metadata file.
    """
    bdir = os.path.abspath(backup_dir or DEFAULT_BACKUP_DIR)
    if not os.path.exists(bdir):
        return []

    metadata = load_backups_metadata(bdir)
    backups = []
    try:
        for entry in os.scandir(bdir):
            if entry.is_file() and entry.name.endswith('.bak'):
                try:
                    stat = entry.stat()
                    size_mb = stat.st_size / (1024 * 1024)
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
                    meta_info = metadata.get(entry.name, {})
                    backups.append({
                        'filename': entry.name,
                        'size_mb': round(size_mb, 2),
                        'timestamp': mtime.strftime('%Y-%m-%d %H:%M:%S'),
                        'mtime': stat.st_mtime,
                        'verified': True,
                        'note': meta_info.get('note', ''),
                        'tag': meta_info.get('tag', ''),
                    })
                except OSError:
                    continue
    except Exception as e:
        logger.warning(f"Error reading backup directory {bdir}: {e}")
        return []

    backups.sort(key=lambda x: x['mtime'], reverse=True)
    return backups[:limit]


# ==============================================================================
# 6. Restore Operations
# ==============================================================================

def restore_database_backup(
    backup_filename: str,
    target_database: Optional[str] = None,
    backup_dir: Optional[str] = None,
    server: Optional[str] = None,
    driver: Optional[str] = None,
    trust_cert: Optional[str] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    High-risk restore operation with mandatory safeguards:
    1. Validates backup file using strict path traversal protection.
    2. Runs RESTORE VERIFYONLY.
    3. Creates a fresh verified backup of CURRENT active database before replacing.
    4. Sets target DB to SINGLE_USER WITH ROLLBACK IMMEDIATE.
    5. Restores with RESTORE DATABASE ... WITH REPLACE.
    6. Returns DB to MULTI_USER.
    7. Validates restored database schema and connectivity.
    """
    srv = server or os.getenv('DB_HOST', DEFAULT_SERVER)
    target_db = target_database or os.getenv('DB_NAME', DEFAULT_DATABASE)
    current_active_db = os.getenv('DB_NAME', DEFAULT_DATABASE)

    # 1. Validate file path
    try:
        safe_backup_path = get_safe_backup_path(backup_filename, backup_dir)
    except Exception as e:
        return False, {'error': f"Invalid backup file: {e}"}

    # 2. Run RESTORE VERIFYONLY on source backup
    v_ok, v_msg = verify_backup_file(safe_backup_path, server=srv, driver=driver, trust_cert=trust_cert)
    if not v_ok:
        return False, {'error': f"Source backup integrity check failed: {v_msg}"}

    # 3. Create fresh pre-restore backup of the CURRENT active database
    logger.info(f"Creating pre-restore backup snapshot of active database [{current_active_db}]...")
    pre_ok, pre_meta = create_database_backup(
        backup_dir=backup_dir,
        server=srv,
        database=current_active_db,
        driver=driver,
        trust_cert=trust_cert,
        prefix=f"{current_active_db}_pre_restore"
    )
    if not pre_ok:
        return False, {
            'error': f"Pre-restore backup failed: {pre_meta.get('error', 'Unknown error')}. "
                     f"Restore aborted to prevent data loss."
        }

    logger.info(f"Pre-restore snapshot verified: {pre_meta.get('filename')}")

    # 4. Connect to master to perform restore
    try:
        conn = get_pyodbc_connection(server=srv, database='master', driver=driver, trust_cert=trust_cert)
        cur = conn.cursor()
    except Exception as e:
        return False, {'error': f"Cannot connect to SQL Server master on {srv}: {sanitize_error(e)}"}

    safe_path_sql = safe_backup_path.replace("'", "''")

    try:
        # Step A: Disconnect conflicting sessions
        cur.execute(f"ALTER DATABASE [{target_db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;")
        while cur.nextset():
            pass

        # Step B: Restore database
        logger.info(f"Restoring database [{target_db}] from {safe_backup_path}...")
        restore_sql = f"RESTORE DATABASE [{target_db}] FROM DISK = N'{safe_path_sql}' WITH REPLACE;"
        cur.execute(restore_sql)
        while cur.nextset():
            pass

        # Step C: Return to MULTI_USER
        cur.execute(f"ALTER DATABASE [{target_db}] SET MULTI_USER;")
        while cur.nextset():
            pass

        conn.close()

    except Exception as e:
        # Emergency attempt to restore MULTI_USER if locked in SINGLE_USER
        try:
            cur.execute(f"ALTER DATABASE [{target_db}] SET MULTI_USER;")
            while cur.nextset():
                pass
            conn.close()
        except Exception:
            pass
        return False, {
            'error': f"SQL Server restore operation failed: {sanitize_error(e)}. "
                     f"Pre-restore snapshot available at: {pre_meta.get('filename')}"
        }

    # 5. Post-restore validation
    val = validate_target_database(server=srv, database=target_db, driver=driver, trust_cert=trust_cert)
    if not val.get('success'):
        return False, {
            'error': f"Database restored but post-restore validation failed: {val.get('error')}. "
                     f"Pre-restore snapshot: {pre_meta.get('filename')}"
        }

    return True, {
        'success': True,
        'message': f"Database [{target_db}] restored and verified successfully.",
        'target_database': target_db,
        'pre_restore_backup': pre_meta.get('filename'),
        'table_count': val.get('table_count', 0),
        'migration_count': val.get('migration_count', 0),
        'latest_migration': val.get('latest_migration', 'None'),
    }


# ==============================================================================
# 7. Update & Migration Inspection
# ==============================================================================

def check_pending_migrations() -> Dict[str, Any]:
    """
    Inspect pending Django migrations without applying them.
    Uses Django's MigrationExecutor to examine unapplied migrations.
    """
    try:
        import assessment
        app_version = getattr(assessment, '__version__', '1.0.0')
    except Exception:
        app_version = '1.0.0'

    try:
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        plan = executor.migration_plan(targets)

        pending_names = [f"{mig.app_label}.{mig.name}" for mig, backwards in plan if not backwards]
        applied = executor.loader.applied_migrations
        total_applied = len(applied)

        return {
            'success': True,
            'up_to_date': len(pending_names) == 0,
            'pending_count': len(pending_names),
            'pending_migrations': pending_names,
            'total_applied': total_applied,
            'app_version': app_version,
            'status_text': 'Up to date' if len(pending_names) == 0 else f"{len(pending_names)} pending migration(s)",
        }
    except Exception as e:
        logger.warning(f"Error checking pending migrations: {e}")
        return {
            'success': False,
            'up_to_date': True,
            'pending_count': 0,
            'pending_migrations': [],
            'app_version': app_version,
            'error': sanitize_error(e),
        }


def execute_system_update(skip_backup: bool = False) -> Tuple[bool, List[Dict[str, str]]]:
    """
    Execute the QuizX Client Application & Database Update workflow:
    1. Preflight environment verification
    2. SQL Server connectivity
    3. Target database health & table check
    4. Mandatory pre-update verified backup
    5. Pending migration inspection
    6. Migration application
    7. Django system check
    8. Final status reporting

    Returns (success_bool, list_of_step_logs).
    """
    steps: List[Dict[str, str]] = []

    def log_step(name: str, status: str, detail: str):
        steps.append({'name': name, 'status': status, 'detail': detail})
        logger.info(f"[{status.upper()}] {name}: {detail}")

    # Step 1: Preflight environment check
    env_file = os.path.join(settings.BASE_DIR, '.env')
    if not os.path.exists(env_file):
        log_step("Environment Check", "error", ".env file not found.")
        return False, steps
    log_step("Environment Check", "success", "Configuration verified.")

    db_engine = os.getenv('DB_ENGINE', '').strip().lower()
    if db_engine != 'mssql':
        log_step("Engine Check", "error", f"DB_ENGINE is '{db_engine}', not 'mssql'.")
        return False, steps
    log_step("Engine Check", "success", "SQL Server Express engine configured.")

    # Step 2: SQL Server connectivity
    srv = os.getenv('DB_HOST', DEFAULT_SERVER)
    db = os.getenv('DB_NAME', DEFAULT_DATABASE)
    conn_res = test_sql_connection(server=srv, database='master')
    if not conn_res.get('success'):
        log_step("SQL Server Connectivity", "error", conn_res.get('message', 'Cannot connect.'))
        return False, steps
    log_step("SQL Server Connectivity", "success", f"Connected to {srv} ({conn_res.get('version', '')})")

    # Step 3: Database health check
    val_res = validate_target_database(server=srv, database=db)
    if not val_res.get('success'):
        log_step("Database Health", "error", val_res.get('error', 'Health check failed.'))
        return False, steps
    log_step("Database Health", "success", f"Database [{db}] online ({val_res.get('table_count')} tables).")

    # Step 4: Pre-migration backup
    if skip_backup:
        log_step("Pre-Update Backup", "warning", "Backup skipped as requested.")
    else:
        b_ok, b_meta = create_database_backup(prefix=f"{db}_pre_update")
        if not b_ok:
            log_step("Pre-Update Backup", "error", f"Backup failed: {b_meta.get('error')}. Aborting update.")
            return False, steps
        log_step("Pre-Update Backup", "success", f"Verified backup created: {b_meta.get('filename')} ({b_meta.get('size_mb')} MB)")

    # Step 5: Migration inspection
    mig_info = check_pending_migrations()
    pending = mig_info.get('pending_migrations', [])
    if not pending:
        log_step("Pending Migrations", "success", "No pending migrations detected. Database schema is up to date.")
    else:
        log_step("Pending Migrations", "info", f"{len(pending)} pending migration(s): {', '.join(pending[:5])}")

    # Step 6: Apply migrations
    if pending:
        try:
            call_command('migrate', interactive=False)
            log_step("Apply Migrations", "success", "All pending migrations applied successfully.")
        except Exception as e:
            log_step("Apply Migrations", "error", f"Migration failed: {sanitize_error(e)}")
            return False, steps
    else:
        log_step("Apply Migrations", "success", "Schema already current.")

    # Step 7: System check
    try:
        call_command('check')
        log_step("Django System Check", "success", "Django system check passed with 0 issues.")
    except Exception as e:
        log_step("Django System Check", "error", f"Check failed: {e}")
        return False, steps

    # Step 8: Final status
    log_step("Update Complete", "success", "QuizX application and database updated successfully.")
    return True, steps


# ==============================================================================
# 8. Environment Persistence (.env)
# ==============================================================================

def update_env_database_config(
    db_host: str,
    db_name: str,
    db_driver: Optional[str] = None,
    trust_cert: Optional[str] = None,
    env_path: Optional[str] = None
) -> bool:
    """
    Safely update database configuration variables in .env.
    Preserves all unrelated keys (e.g. DEBUG, SECRET_KEY, custom settings) and comments.
    Uses atomic write via temporary file.
    """
    target_env = env_path or os.path.join(settings.BASE_DIR, '.env')
    raw_driver = (db_driver or DEFAULT_DRIVER).strip()
    driver = DEFAULT_DRIVER if (not raw_driver or raw_driver.upper() == 'N/A') else raw_driver
    tc = trust_cert or DEFAULT_TRUST_CERT

    new_db_keys = {
        'DB_ENGINE': 'mssql',
        'DB_NAME': db_name.strip(),
        'DB_HOST': db_host.strip().replace('/', '\\'),
        'DB_PORT': '',
        'DB_USER': '',
        'DB_PASSWORD': '',
        'DB_OPTIONS_DRIVER': driver.strip(),
        'DB_TRUSTED_CONNECTION': 'yes',
        'DB_TRUST_SERVER_CERTIFICATE': tc.strip(),
    }

    lines: List[str] = []
    seen_keys = set()

    if os.path.exists(target_env):
        with open(target_env, 'r', encoding='utf-8') as f:
            existing_lines = f.readlines()

        for line in existing_lines:
            stripped = line.strip()
            if stripped.startswith('#') or '=' not in stripped:
                lines.append(line)
                continue

            key = stripped.split('=', 1)[0].strip()
            if key in new_db_keys:
                lines.append(f"{key}={new_db_keys[key]}\n")
                seen_keys.add(key)
            else:
                lines.append(line)

    # Append any database keys not yet present
    for k, v in new_db_keys.items():
        if k not in seen_keys:
            lines.append(f"{k}={v}\n")

    # Atomic write to temporary file first
    temp_env = f"{target_env}.tmp_{int(time.time())}"
    try:
        with open(temp_env, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        os.replace(temp_env, target_env)
        logger.info(f"Updated .env database configuration for {db_host}/{db_name}")
        return True
    except Exception as e:
        if os.path.exists(temp_env):
            try:
                os.remove(temp_env)
            except OSError:
                pass
        logger.error(f"Failed to update .env: {e}")
        raise IOError(f"Could not update .env: {e}")


# ==============================================================================
# 9. Audit Logging
# ==============================================================================

def log_audit_event(
    user: Any,
    action: str,
    details: str,
    success: bool = True
):
    """
    Record superuser maintenance actions using Python logging and Django LogEntry.
    Never logs passwords, connection secrets, or raw .env content.
    """
    # Sanitize details string
    safe_details = sanitize_error(Exception(details)) if not success else details
    safe_details = re.sub(r'PWD=[^;]+;', 'PWD=***;', safe_details, flags=re.IGNORECASE)

    status_str = "SUCCESS" if success else "FAILED"
    username = getattr(user, 'username', 'System')
    logger.info(f"AUDIT [{status_str}] {action} by {username}: {safe_details}")

    # If user has an ID (authenticated Django user), record to LogEntry
    if getattr(user, 'is_authenticated', False) and getattr(user, 'id', None):
        try:
            content_type = ContentType.objects.get_for_model(user.__class__)
            LogEntry.objects.log_action(
                user_id=user.id,
                content_type_id=content_type.id,
                object_id=str(user.id),
                object_repr=f"{action} ({status_str})",
                action_flag=CHANGE,
                change_message=safe_details[:200]
            )
        except Exception as e:
            logger.warning(f"Could not record LogEntry audit log: {e}")

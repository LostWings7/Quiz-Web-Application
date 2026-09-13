# Production SQL Server Backup Utility for QuizX
# Creates native, verified .bak backups before migrations or updates
# Delegates to canonical exam.db_maintenance engine

import os
import sys

# Ensure Django settings are initialized for standalone CLI usage
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'assessment.settings')
    import django
    django.setup()

from exam.db_maintenance import (
    create_database_backup,
    DEFAULT_BACKUP_DIR,
    DEFAULT_SERVER,
    DEFAULT_DATABASE,
)

def backup_quizx(backup_dir=None):
    bdir = backup_dir or DEFAULT_BACKUP_DIR
    print('=====================================================')
    print('QUIZX PRODUCTION SQL SERVER BACKUP')
    print('=====================================================')
    print(f'Server: {DEFAULT_SERVER}')
    print(f'Database: {DEFAULT_DATABASE}')
    print(f'Target Backup Directory: {bdir}\n')

    print(f'Initiating native SQL Server backup via maintenance engine...')
    success, meta = create_database_backup(backup_dir=bdir)

    if success:
        print(f"SQL Server backup operation completed successfully.")
        print(f"Backup file: {meta.get('path')}")
        print(f"Backup verified on disk. Size: {meta.get('size_mb')} MB")
        print('\nBackup status: SUCCESS')
        print('=====================================================\n')
        return True, meta.get('path')
    else:
        print(f"ERROR: {meta.get('error')}")
        print('\nBackup status: FAILED')
        print('=====================================================\n')
        return False, None

if __name__ == '__main__':
    target_dir = sys.argv[1] if len(sys.argv) > 1 else None
    success, path = backup_quizx(target_dir)
    sys.exit(0 if success else 1)

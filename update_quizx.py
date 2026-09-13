# QuizX Safe Client Update Utility
# Automates pre-flight checks, backup, migration, and system verification
# Delegates to canonical exam.db_maintenance engine

import os
import sys

# Ensure Django settings are initialized for standalone CLI usage
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'assessment.settings')
    import django
    django.setup()

from exam.db_maintenance import execute_system_update

def print_header(title):
    print('\n' + '=' * 60)
    print(f'  {title}')
    print('=' * 60)

def update_quizx(skip_backup=False):
    print_header('QUIZX CLIENT APPLICATION & DATABASE UPDATE')
    print('Executing update workflow via maintenance engine...\n')

    success, steps = execute_system_update(skip_backup=skip_backup)

    for i, step in enumerate(steps, 1):
        status_tag = '[OK]' if step['status'] == 'success' else ('[WARN]' if step['status'] == 'warning' else '[FAIL]')
        print(f"[{i}/{len(steps)}] {status_tag} {step['name']}: {step['detail']}")

    if success:
        print_header('UPDATE SUCCESSFUL')
        print('QuizX is ready for production use.')
        print('=' * 60 + '\n')
        return True
    else:
        print_header('UPDATE FAILED')
        print('Please inspect the failed step above. Pre-update backup is available for rollback.')
        print('=' * 60 + '\n')
        return False

if __name__ == '__main__':
    skip = '--skip-backup' in sys.argv
    success = update_quizx(skip_backup=skip)
    sys.exit(0 if success else 1)

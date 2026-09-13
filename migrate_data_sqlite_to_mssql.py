# Migration utility: SQLite -> SQL Server 2025 Express
# Deterministic, safe, transactional migration for QuizX

import os
import sys
import sqlite3
import pyodbc
from dotenv import load_dotenv

load_dotenv('.env')

SQLITE_PATH = 'db.sqlite3'
MSSQL_SERVER = os.getenv('DB_HOST', r'localhost\SQLEXPRESS01')
MSSQL_DATABASE = os.getenv('DB_NAME', 'QuizX')
MSSQL_DRIVER = os.getenv('DB_OPTIONS_DRIVER', 'ODBC Driver 18 for SQL Server')
TRUST_CERT = os.getenv('DB_TRUST_SERVER_CERTIFICATE', 'yes')

TABLE_MIGRATION_ORDER = [
    ('auth_user', True),
    ('exam_class', True),
    ('exam_schoolprofile', True),
    ('exam_section', True),
    ('exam_quiz', True),
    ('exam_studentprofile', True),
    ('exam_quiz_assigned_classes', True),
    ('exam_quiz_assigned_sections', True),
    ('exam_subtopic', True),
    ('exam_question', True),
    ('exam_quizresult', True),
    ('exam_questionoption', True),
    ('exam_questionimage', True),
    ('exam_optionimage', True),
    ('django_admin_log', True),
]

def migrate():
    print('Starting controlled migration from SQLite to SQL Server...')
    print(f'Source SQLite: {SQLITE_PATH}')
    print(f'Target SQL Server: {MSSQL_SERVER} / {MSSQL_DATABASE}')

    if not os.path.exists(SQLITE_PATH):
        raise FileNotFoundError(f'Source database {SQLITE_PATH} does not exist!')

    # Connect to SQLite read-only
    sq_conn = sqlite3.connect(f'file:{SQLITE_PATH}?mode=ro', uri=True)
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()

    # Connect to SQL Server
    extra = 'TrustServerCertificate=yes;' if TRUST_CERT.lower() in ('yes', 'true', '1') else ''
    ms_conn = pyodbc.connect(
        f'DRIVER={{{MSSQL_DRIVER}}};'
        f'SERVER={MSSQL_SERVER};'
        f'DATABASE={MSSQL_DATABASE};'
        f'Trusted_Connection=yes;'
        f'{extra}'
    )
    ms_cur = ms_conn.cursor()

    # Build ContentType mapping for django_admin_log
    sq_cur.execute('SELECT id, app_label, model FROM django_content_type')
    sq_ct_map = {row['id']: (row['app_label'], row['model']) for row in sq_cur.fetchall()}

    ms_cur.execute('SELECT id, app_label, model FROM django_content_type')
    ms_ct_reverse = {(row[1], row[2]): row[0] for row in ms_cur.fetchall()}

    ct_id_translation = {}
    for sq_id, key in sq_ct_map.items():
        if key in ms_ct_reverse:
            ct_id_translation[sq_id] = ms_ct_reverse[key]

    results = []

    try:
        for table, has_identity in TABLE_MIGRATION_ORDER:
            # Check existing count in SQL Server
            ms_cur.execute(f'SELECT COUNT(*) FROM [{table}]')
            target_count_before = ms_cur.fetchone()[0]

            sq_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            source_count = sq_cur.fetchone()[0]

            if target_count_before > 0:
                print(f'Notice: [{table}] already has {target_count_before} rows in SQL Server.')
                if target_count_before == source_count:
                    print(f'[{table}] already populated with {target_count_before} rows. Skipping.')
                    results.append((table, source_count, target_count_before, 'SKIPPED (ALREADY POPULATED)'))
                    continue
                else:
                    raise RuntimeError(f'[{table}] has {target_count_before} rows, but SQLite has {source_count} rows! Stop to prevent collision.')

            if source_count == 0:
                print(f'[{table}]: 0 rows to migrate.')
                results.append((table, 0, 0, 'MATCH (EMPTY)'))
                continue

            # Fetch columns from SQLite
            sq_cur.execute(f'PRAGMA table_info("{table}")')
            cols = [c['name'] for c in sq_cur.fetchall()]

            # Fetch all rows from SQLite
            col_list_str = ', '.join([f'"{c}"' for c in cols])
            sq_cur.execute(f'SELECT {col_list_str} FROM "{table}"')
            rows = sq_cur.fetchall()

            # Enable IDENTITY_INSERT if applicable
            if has_identity:
                ms_cur.execute(f'SET IDENTITY_INSERT [{table}] ON')

            ms_col_list_str = ', '.join([f'[{c}]' for c in cols])
            placeholders = ', '.join(['?' for _ in cols])
            insert_sql = f'INSERT INTO [{table}] ({ms_col_list_str}) VALUES ({placeholders})'

            inserted = 0
            max_id = 0

            for r in rows:
                val_list = []
                for c in cols:
                    val = r[c]
                    # Map content_type_id for django_admin_log
                    if table == 'django_admin_log' and c == 'content_type_id' and val is not None:
                        val = ct_id_translation.get(val, val)
                    val_list.append(val)
                ms_cur.execute(insert_sql, val_list)
                inserted += 1
                if 'id' in cols and r['id'] is not None and r['id'] > max_id:
                    max_id = r['id']

            if has_identity:
                ms_cur.execute(f'SET IDENTITY_INSERT [{table}] OFF')

            # Reseed identity counter if rows inserted
            if has_identity and max_id > 0:
                ms_cur.execute(f"DBCC CHECKIDENT ('[{table}]', RESEED, {max_id})")

            ms_conn.commit()

            # Verify target count
            ms_cur.execute(f'SELECT COUNT(*) FROM [{table}]')
            target_count = ms_cur.fetchone()[0]

            status = 'MATCH' if target_count == source_count else 'MISMATCH'
            print(f'[{table}]: SQLite={source_count}, MSSQL={target_count} -> {status}')
            results.append((table, source_count, target_count, status))

            if status == 'MISMATCH':
                raise RuntimeError(f'Row count mismatch for {table}: SQLite={source_count}, MSSQL={target_count}')

        print('\nAll application tables successfully migrated and verified!')
    except Exception as e:
        ms_conn.rollback()
        print(f'Error during migration: {e}')
        raise
    finally:
        sq_conn.close()
        ms_conn.close()

    return results

if __name__ == '__main__':
    migrate()

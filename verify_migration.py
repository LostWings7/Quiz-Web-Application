# Comprehensive verification utility for QuizX migration
# Compares SQLite and SQL Server databases in-depth

import os
import sys
import json
import sqlite3
import pyodbc
from dotenv import load_dotenv

load_dotenv('.env')

SQLITE_PATH = 'db.sqlite3'
MSSQL_SERVER = os.getenv('DB_HOST', r'localhost\SQLEXPRESS01')
MSSQL_DATABASE = os.getenv('DB_NAME', 'QuizX')
MSSQL_DRIVER = os.getenv('DB_OPTIONS_DRIVER', 'ODBC Driver 18 for SQL Server')
TRUST_CERT = os.getenv('DB_TRUST_SERVER_CERTIFICATE', 'yes')

def run_verification():
    print('=====================================================')
    print('QUIZX DATABASE MIGRATION VERIFICATION SUITE')
    print('=====================================================\n')

    sq_conn = sqlite3.connect(f'file:{SQLITE_PATH}?mode=ro', uri=True)
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()

    extra = 'TrustServerCertificate=yes;' if TRUST_CERT.lower() in ('yes', 'true', '1') else ''
    ms_conn = pyodbc.connect(
        f'DRIVER={{{MSSQL_DRIVER}}};'
        f'SERVER={MSSQL_SERVER};'
        f'DATABASE={MSSQL_DATABASE};'
        f'Trusted_Connection=yes;'
        f'{extra}'
    )
    ms_cur = ms_conn.cursor()

    all_passed = True

    # 1. Row count comparison
    print('--- 1. TABLE ROW COUNTS ---')
    tables_to_check = [
        'auth_user',
        'exam_class',
        'exam_schoolprofile',
        'exam_section',
        'exam_quiz',
        'exam_studentprofile',
        'exam_quiz_assigned_classes',
        'exam_quiz_assigned_sections',
        'exam_subtopic',
        'exam_question',
        'exam_quizresult',
        'exam_questionoption',
        'exam_questionimage',
        'exam_optionimage',
        'django_admin_log',
    ]

    for t in tables_to_check:
        sq_cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        sq_cnt = sq_cur.fetchone()[0]
        ms_cur.execute(f'SELECT COUNT(*) FROM [{t}]')
        ms_cnt = ms_cur.fetchone()[0]
        status = 'OK' if sq_cnt == ms_cnt else 'MISMATCH'
        if status != 'OK':
            all_passed = False
        print(f'{t:30}: SQLite={sq_cnt:4} | MSSQL={ms_cnt:4} -> {status}')

    # 2. QuizResult.answers JSON integrity check
    print('\n--- 2. QUIZRESULT.ANSWERS JSON INTEGRITY ---')
    sq_cur.execute('SELECT id, quiz_id, user_id, score, answers FROM exam_quizresult ORDER BY id')
    sq_results = sq_cur.fetchall()
    ms_cur.execute('SELECT id, quiz_id, user_id, score, answers FROM [exam_quizresult] ORDER BY id')
    ms_results = ms_cur.fetchall()

    if len(sq_results) != len(ms_results):
        print(f'MISMATCH in QuizResult row counts: SQLite={len(sq_results)}, MSSQL={len(ms_results)}')
        all_passed = False
    else:
        for sq_r, ms_r in zip(sq_results, ms_results):
            qid, q_quiz, q_user, q_score, q_ans = sq_r['id'], sq_r['quiz_id'], sq_r['user_id'], sq_r['score'], sq_r['answers']
            m_id, m_quiz, m_user, m_score, m_ans = ms_r[0], ms_r[1], ms_r[2], ms_r[3], ms_r[4]

            match_basic = (qid == m_id and q_quiz == m_quiz and q_user == m_user and q_score == m_score)
            sq_json = json.loads(q_ans) if isinstance(q_ans, str) else q_ans
            ms_json = json.loads(m_ans) if isinstance(m_ans, str) else m_ans

            json_match = (sq_json == ms_json)
            if not match_basic or not json_match:
                print(f'QuizResult {qid} FAILED match! Basic: {match_basic}, JSON: {json_match}')
                all_passed = False
            else:
                print(f'QuizResult ID={qid} (Quiz={q_quiz}, User={q_user}, Score={q_score}): JSON Match OK! Keys count={len(sq_json)}')

    # 3. Bloom taxonomy classification verification
    print('\n--- 3. BLOOM METADATA VERIFICATION ---')
    sq_cur.execute('SELECT id, bloom_level, bloom_confidence, bloom_classification_source, bloom_reviewed FROM exam_question ORDER BY id')
    sq_questions = sq_cur.fetchall()
    ms_cur.execute('SELECT id, bloom_level, bloom_confidence, bloom_classification_source, bloom_reviewed FROM [exam_question] ORDER BY id')
    ms_questions = ms_cur.fetchall()

    bloom_mismatches = 0
    for sq_q, ms_q in zip(sq_questions, ms_questions):
        sq_bloom = (sq_q['id'], sq_q['bloom_level'], round(sq_q['bloom_confidence'], 4) if sq_q['bloom_confidence'] is not None else None, sq_q['bloom_classification_source'], bool(sq_q['bloom_reviewed']))
        ms_bloom = (ms_q[0], ms_q[1], round(ms_q[2], 4) if ms_q[2] is not None else None, ms_q[3], bool(ms_q[4]))
        if sq_bloom != ms_bloom:
            print(f'Bloom mismatch on question {sq_q["id"]}: SQLite={sq_bloom} vs MSSQL={ms_bloom}')
            bloom_mismatches += 1
            all_passed = False

    if bloom_mismatches == 0:
        print(f'All {len(sq_questions)} questions Bloom classification metadata match 100%!')

    # 4. Media paths integrity check
    print('\n--- 4. MEDIA PATHS DATABASE PRESERVATION & INTEGRITY ---')
    sq_cur.execute("SELECT id, image FROM exam_question WHERE image IS NOT NULL AND image != '' ORDER BY id")
    sq_q_images = {r['id']: r['image'] for r in sq_cur.fetchall()}
    ms_cur.execute("SELECT id, image FROM [exam_question] WHERE image IS NOT NULL AND image != '' ORDER BY id")
    ms_q_images = {r[0]: r[1] for r in ms_cur.fetchall()}

    if sq_q_images != ms_q_images:
        print(f'MISMATCH in question image paths: SQLite={sq_q_images} vs MSSQL={ms_q_images}')
        all_passed = False
    else:
        print(f'Question image paths match 100% ({len(sq_q_images)} images preserved).')

    sq_cur.execute("SELECT id, school_logo, school_banner_image FROM exam_schoolprofile ORDER BY id")
    sq_sp_images = [(r['id'], r['school_logo'], r['school_banner_image']) for r in sq_cur.fetchall()]
    ms_cur.execute("SELECT id, school_logo, school_banner_image FROM [exam_schoolprofile] ORDER BY id")
    ms_sp_images = [(r[0], r[1], r[2]) for r in ms_cur.fetchall()]

    if sq_sp_images != ms_sp_images:
        print(f'MISMATCH in school profile images: SQLite={sq_sp_images} vs MSSQL={ms_sp_images}')
        all_passed = False
    else:
        print(f'School profile image paths match 100% ({len(sq_sp_images)} profile records preserved).')

    # Disk existence check
    for q_id, img_path in ms_q_images.items():
        disk_path = os.path.normpath(os.path.join('media', img_path))
        exists = os.path.exists(disk_path)
        print(f'  Question {q_id} image path "{img_path}": disk exists={exists}')

    for sp_id, logo, banner in ms_sp_images:
        if logo:
            logo_disk = os.path.normpath(os.path.join('media', logo))
            print(f'  SchoolProfile {sp_id} logo "{logo}": disk exists={os.path.exists(logo_disk)}')
        if banner:
            banner_disk = os.path.normpath(os.path.join('media', banner))
            print(f'  SchoolProfile {sp_id} banner "{banner}": disk exists={os.path.exists(banner_disk)}')

    # 5. Relationship integrity
    print('\n--- 5. RELATIONSHIP & FOREIGN KEY INTEGRITY ---')
    # Check for orphan StudentProfiles
    ms_cur.execute('''
        SELECT sp.id, sp.user_id FROM [exam_studentprofile] sp
        LEFT JOIN [auth_user] u ON sp.user_id = u.id
        WHERE u.id IS NULL
    ''')
    orphan_sp = ms_cur.fetchall()
    if orphan_sp:
        print(f'Orphan StudentProfiles found: {orphan_sp}')
        all_passed = False
    else:
        print('StudentProfile -> User: 0 orphans.')

    # Check for orphan Questions
    ms_cur.execute('''
        SELECT q.id, q.quiz_id FROM [exam_question] q
        LEFT JOIN [exam_quiz] z ON q.quiz_id = z.id
        WHERE z.id IS NULL
    ''')
    orphan_q = ms_cur.fetchall()
    if orphan_q:
        print(f'Orphan Questions found: {orphan_q}')
        all_passed = False
    else:
        print('Question -> Quiz: 0 orphans.')

    # Check for orphan QuestionOptions
    ms_cur.execute('''
        SELECT qo.id, qo.question_id FROM [exam_questionoption] qo
        LEFT JOIN [exam_question] q ON qo.question_id = q.id
        WHERE q.id IS NULL
    ''')
    orphan_qo = ms_cur.fetchall()
    if orphan_qo:
        print(f'Orphan QuestionOptions found: {orphan_qo}')
        all_passed = False
    else:
        print('QuestionOption -> Question: 0 orphans.')

    # Check Many-to-many
    ms_cur.execute('''
        SELECT qc.id FROM [exam_quiz_assigned_classes] qc
        LEFT JOIN [exam_quiz] z ON qc.quiz_id = z.id
        LEFT JOIN [exam_class] c ON qc.class_id = c.id
        WHERE z.id IS NULL OR c.id IS NULL
    ''')
    orphan_qc = ms_cur.fetchall()
    if orphan_qc:
        print(f'Orphan Quiz Assigned Classes found: {orphan_qc}')
        all_passed = False
    else:
        print('Quiz Assigned Classes M2M: 0 orphans.')

    # 6. Primary Key & Identity sequence check
    print('\n--- 6. PRIMARY KEY & IDENTITY STATUS ---')
    ms_cur.execute('''
        SELECT t.name AS TableName, IDENT_CURRENT(t.name) as CurrentIdent
        FROM sys.tables t
        JOIN sys.columns c ON t.object_id = c.object_id
        WHERE c.is_identity = 1
        GROUP BY t.name
        ORDER BY t.name
    ''')
    ident_rows = ms_cur.fetchall()
    for t_name, cur_ident in ident_rows:
        ms_cur.execute(f'SELECT MAX(id) FROM [{t_name}]')
        max_id = ms_cur.fetchone()[0]
        if max_id is not None:
            status = 'OK' if cur_ident >= max_id else 'RESEED NEEDED'
            print(f'{t_name:30}: Max ID={max_id:4} | IDENT_CURRENT={cur_ident:4} -> {status}')
            if status != 'OK':
                all_passed = False

    # 7. Controlled Write Test
    print('\n--- 7. CONTROLLED WRITE TEST (INSERT & CLEANUP) ---')
    test_code = '__MIGRATION_VERIFY_TEMP_QUIZ__'
    try:
        # Check max quiz id before
        ms_cur.execute('SELECT MAX(id) FROM [exam_quiz]')
        max_quiz_id_before = ms_cur.fetchone()[0] or 0

        # Insert via standard SQL Server identity generation (no IDENTITY_INSERT)
        ms_cur.execute('''
            INSERT INTO [exam_quiz] (code, title, is_active, randomize_questions, timer_enabled, duration_minutes, show_detailed_results, created_at)
            VALUES (?, ?, 1, 1, 0, 30, 0, GETDATE())
        ''', (test_code, 'Migration Temporary Test Quiz'))
        ms_conn.commit()

        ms_cur.execute('SELECT id, code FROM [exam_quiz] WHERE code = ?', (test_code,))
        new_quiz = ms_cur.fetchone()
        new_quiz_id = new_quiz[0]
        print(f'Created test quiz with ID={new_quiz_id}. Previous max was {max_quiz_id_before}.')

        if new_quiz_id <= max_quiz_id_before:
            print('ERROR: Generated identity collided with existing IDs!')
            all_passed = False
        else:
            print(f'Identity increment confirmed: {new_quiz_id} > {max_quiz_id_before}!')

        # Safely delete the temporary test record
        ms_cur.execute('DELETE FROM [exam_quiz] WHERE id = ?', (new_quiz_id,))
        ms_conn.commit()
        # Reseed back to original max id
        ms_cur.execute(f"DBCC CHECKIDENT ('[exam_quiz]', RESEED, {max_quiz_id_before})")
        ms_conn.commit()
        print('Temporary test quiz deleted and identity reseeded cleanly.')

    except Exception as e:
        print(f'Controlled write test failed: {e}')
        all_passed = False

    sq_conn.close()
    ms_conn.close()

    print('\n=====================================================')
    if all_passed:
        print('VERIFICATION STATUS: ALL CHECKS PASSED PERFECTLY (100%)')
    else:
        print('VERIFICATION STATUS: FAILURES DETECTED!')
    print('=====================================================')
    return all_passed

if __name__ == '__main__':
    ok = run_verification()
    sys.exit(0 if ok else 1)

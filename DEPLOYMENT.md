# QuizX Production Deployment & Update Guide

This document defines the deployment, database versioning, and update workflow for **QuizX** (`QuizWebApplication`) running on **Microsoft SQL Server 2025 Express**.

---

## 1. Architectural Principles

QuizX follows a strict, safe database versioning architecture:

```
Django Models (Code)
       ↓
python manage.py makemigrations
       ↓
Migration files committed to Git repository
       ↓
Client pulls updated QuizX release
       ↓
Automatic Pre-Migration SQL Server Backup (.bak)
       ↓
python manage.py migrate
       ↓
Existing SQL Server Database Evolving in Place (Preserving All Data)
```

### Core Rules
1. **Single Source of Truth**: Django migration files committed to Git are the sole authority for database schema.
2. **Zero In-Place Recreations**: Normal client updates **never** drop, recreate, or re-import the database. Existing client data, primary keys, relationships, Bloom classification metadata, and quiz responses persist across all updates.
3. **No Ad-Hoc Manual Schema Edits**: Tables, columns, constraints, and indexes must not be manually modified in SSMS; all changes must flow through version-controlled Django migrations.
4. **Mandatory Backup Gate**: A native SQL Server `.bak` backup is created and validated with `RESTORE VERIFYONLY` prior to applying any database migration.

---

## 2. Versioning Strategy

QuizX tracks versioning across two independent dimensions:
- **Application Version**: Declared in `assessment/__init__.py` (e.g. `__version__ = '1.0.0'`).
- **Database Migration State**: The latest migration applied to `[dbo].[django_migrations]` (e.g. `exam.0014_question_bloom_classification_source_and_more`).

This decoupled reporting allows operators to verify immediately whether an application instance has pending schema operations.

---

## 3. Initial Client Installation

### Prerequisites
1. **Operating System**: Windows 10/11 or Windows Server.
2. **Python**: Python 3.10 to 3.14 (64-bit).
3. **Database Engine**: Microsoft SQL Server 2025 Express (or SQL Server 2019/2022).
4. **ODBC Driver**: Microsoft ODBC Driver 18 for SQL Server (64-bit).
5. **Authentication**: Windows Authentication (or SQL Server Authentication if configured).

### Installation Steps
1. **Clone or Download Application**:
   ```powershell
   git clone https://github.com/LostWings7/Quiz-Web-Application.git
   cd Quiz-Web-Application
   ```

2. **Configure Environment (`.env`)**:
   Copy the provided template and configure connection parameters:
   ```powershell
   Copy-Item .env.example .env
   ```
   Edit `.env`:
   ```env
   DEBUG=False
   SECRET_KEY=your-production-random-secret-key

   # Database Configuration
   DB_ENGINE=mssql
   DB_NAME=QuizX
   DB_HOST=localhost\SQLEXPRESS01
   DB_PORT=
   DB_USER=
   DB_PASSWORD=
   DB_OPTIONS_DRIVER=ODBC Driver 18 for SQL Server
   DB_TRUSTED_CONNECTION=yes
   DB_TRUST_SERVER_CERTIFICATE=yes
   DB_BACKUP_DIR=C:\Users\Public\QuizX_Backups
   ```

3. **Install Dependencies**:
   ```powershell
   python -m pip install -r requirements.txt
   ```

4. **Initialize Database**:
   Create the database in SQL Server (if not already created):
   ```powershell
   sqlcmd -S "localhost\SQLEXPRESS01" -E -C -Q "CREATE DATABASE [QuizX];"
   ```
   Apply Django migrations:
   ```powershell
   python manage.py migrate
   ```

5. **Create Initial Administrator**:
   ```powershell
   python manage.py createsuperuser
   ```

6. **Verify and Run**:
   ```powershell
   python manage.py check
   python manage.py runserver 0.0.0.0:8000
   ```

---

## 4. Routine Client Update Workflow

When a new version of QuizX is released, update the installation safely using the automated update script:

### Recommended Update Command
In PowerShell:
```powershell
.\update_quizx.ps1
```
Or via Python:
```powershell
python update_quizx.py
```

### What the Update Workflow Does:
1. **[1/8] Environment Verification**: Confirms Python runtime, `.env` file presence, and that `DB_ENGINE=mssql`.
2. **[2/8] Connectivity Check**: Tests connection to the configured SQL Server instance.
3. **[3/8] Database Health Check**: Confirms `QuizX` exists, is `ONLINE`, and contains existing populated tables.
4. **[4/8] Pre-Migration Backup**: Creates a native SQL Server backup (`.bak`) in `C:\Users\Public\QuizX_Backups` and runs `RESTORE VERIFYONLY` to confirm backup validity.
5. **[5/8] Pending Migration Review**: Evaluates `python manage.py migrate --plan`. If no migrations are pending, reports that the schema is already current.
6. **[6/8] Migration Execution**: Applies pending migrations incrementally.
7. **[7/8] System Check**: Executes `python manage.py check` to verify system integrity.
8. **[8/8] Reporting**: Reports application version, latest applied migration, and target database.

> [!NOTE]
> Routine updates do **not** run the full automated test suite to avoid creating temporary test databases on client production instances.

---

## 5. Standalone Backup Utility

You can generate an on-demand SQL Server backup at any time:

```powershell
python backup_quizx.py
```
Or specify a custom backup directory:
```powershell
python backup_quizx.py "D:\DedicatedBackups\QuizX"
```

The backup utility:
- Connects using the configured Windows credentials.
- Uses native `BACKUP DATABASE [QuizX] TO DISK = ... WITH INIT, STATS = 10;`.
- Validates the backup integrity using `RESTORE VERIFYONLY`.
- Reports timestamped file path (e.g. `QuizX_backup_20260913_144703.bak`).

---

## 6. Disaster Recovery & Rollback Runbook

If an update fails or a hardware issue requires restoring the database:

### Option A: Restore via SQLCMD / T-SQL
Replace the database using the verified `.bak` file:
```powershell
sqlcmd -S "localhost\SQLEXPRESS01" -E -C -Q "
ALTER DATABASE [QuizX] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
RESTORE DATABASE [QuizX] FROM DISK = 'C:\Users\Public\QuizX_Backups\QuizX_backup_<timestamp>.bak' WITH REPLACE;
ALTER DATABASE [QuizX] SET MULTI_USER;
"
```

### Option B: Restore via SQL Server Management Studio (SSMS)
1. Open SSMS and connect to `localhost\SQLEXPRESS01`.
2. Right-click **Databases** → **Restore Database...**.
3. Select **Device** → browse to `C:\Users\Public\QuizX_Backups\QuizX_backup_<timestamp>.bak`.
4. In **Options**, check **Overwrite the existing database (WITH REPLACE)** and **Close existing connections**.
5. Click **OK**.

---

## 7. High-Risk Migration Policy (Developer Guidelines)

Schema changes fall into two categories:

### A. Low-Risk Changes (Standard)
- Adding a new model/table.
- Adding a nullable field (`null=True, blank=True`).
- Adding a field with a static default (`default=...`).
- Adding a new database index (`db_index=True`).

### B. High-Risk Changes (Mandatory Review Required)
The following 11 scenarios require developer review, staging database verification, and explicit client communication prior to release:
1. **Removing fields**: Can cause application code looking for the field to error immediately.
2. **Removing models/tables**: Irreversible data destruction if applied to production.
3. **Renaming columns**: Django generates a `RemoveField` + `AddField` pair unless manually configured via `db_column` or state operations, which would destroy column data.
4. **Renaming models/tables**: Can drop and recreate tables if not explicitly structured.
5. **Changing field types**: E.g. CharField to IntegerField; can fail or truncate if incompatible records exist.
6. **Adding required fields without defaults**: Fails when existing rows cannot satisfy `NOT NULL`.
7. **Changing uniqueness constraints**: Fails if existing production rows have duplicates.
8. **Foreign-key behavior changes**: Changing `CASCADE` to `PROTECT` or `SET_NULL` can block operations on existing records.
9. **Large data migrations (`RunPython`)**: Transforming millions of rows can timeout or lock tables.
10. **Batch operations on active quizzes/results**: Can lock `exam_quizresult` during exam hours.
11. **Index restructuring on large tables**: May lock tables during recreation.

### Data Migrations (`RunPython`) Policy
When data must be converted:
1. Always implement both forward and `reverse_code` functions in `migrations.RunPython`.
2. Access models via `apps.get_model('app_label', 'ModelName')`, never import models directly.
3. Test the migration on an isolated database populated from a client backup before committing.

---

## 8. Historical Tooling Note

- `migrate_data_sqlite_to_mssql.py`: Historical utility used for the one-time transition from SQLite to SQL Server. **Not used** for routine updates.
- `verify_migration.py`: Integrity comparison tool between SQLite and SQL Server used during initial migration sign-off.

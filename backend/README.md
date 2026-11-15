# BrandShield AI — Backend Engine

> **CodeNova India 2026 Round 2**  
> *Phase 2A: Backend Foundation & Health Verification*

---

## 1. Overview
The backend of **BrandShield AI** is an asynchronous API service and agentic governance engine built with **FastAPI** and **Python**. It provides the core API infrastructure for brand knowledge indexing, compliance verification, and human-in-the-loop review lifecycles.

In **Phase 2A**, the foundational API structure is established, verified, and equipped with structured health-check endpoints, Pydantic schemas, centralized configuration, and automated tests.

---

## 2. Technology Stack & Runtime
- **Runtime**: Python 3.14+ (Verified: `Python 3.14.6` on Windows)
- **Web Framework**: FastAPI (`0.162.6`)
- **ASGI Server**: Uvicorn (`0.54.0`)
- **Data Validation**: Pydantic v2 (`2.14.3`) & `pydantic-settings` (`2.16.3`)
- **Database & ORM**: SQLAlchemy 2.x (`2.1.8`), Asyncpg (`0.32.0`), Aiosqlite (`0.22.1`), Greenlet (`3.5.6`)
- **Database Migrations**: Alembic (`1.20.1`)
- **Test Framework**: pytest (`9.2.0`), `pytest-asyncio` (`1.5.0`), HTTPX (`0.28.1`)

---

## 3. Directory Structure
```text
backend/
├── alembic/                    # Database migrations
│   ├── versions/
│   │   └── 0001_initial_core_schema.py # Initial core relational schema
│   ├── env.py                  # Alembic environment runner
│   └── script.py.mako          # Migration template
├── alembic.ini                 # Alembic configuration
├── app/
│   ├── api/                    # API route definitions
│   │   └── v1/
│   │       ├── health.py       # GET /api/v1/health endpoint
│   │       └── router.py       # Main v1 API router aggregation
│   ├── core/                   # Application configuration & settings
│   │   ├── config.py           # Pydantic Settings singleton with CORS policy & DB configs
│   │   └── database.py         # SQLAlchemy engine, session maker, base & tenant helpers
│   ├── models/                 # SQLAlchemy 2.0 ORM models
│   │   ├── __init__.py         # Clean model exports
│   │   ├── compliance.py       # ComplianceReport, RuleViolation, EvidenceCitation, CorrectionSuggestion
│   │   ├── guideline.py        # BrandGuideline
│   │   ├── organization.py     # Organization (tenant boundary)
│   │   ├── review.py           # ReviewDecision, AuditEntry (immutable ledger)
│   │   ├── submission.py       # ContentSubmission
│   │   └── user.py             # User
│   ├── schemas/                # Central Pydantic v2 schemas
│   │   ├── __init__.py         # Clean schema exports
│   │   ├── common.py           # Enums: RuleType, SeverityLevel, SubmissionStatus, ReviewAction, TargetChannel
│   │   ├── guidelines.py       # GuidelineCreate, GuidelineUpdate, GuidelineResponse
│   │   ├── health.py           # HealthResponse structured model
│   │   ├── reviews.py          # ReviewDecision, AuditEntry with human authorization invariants
│   │   ├── submissions.py      # SubmissionCreate, SubmissionResponse
│   │   └── violations.py       # ViolationDetail, EvidenceCitation, CorrectionSuggestion, ComplianceReport
│   └── main.py                 # FastAPI application factory, lifespan, CORS & error handlers
├── tests/                      # Automated test suite
│   ├── conftest.py             # pytest fixtures (TestClient, paths)
│   ├── test_cors.py            # Comprehensive tests for CORS isolation & production security
│   ├── test_database.py        # Database models, relationships, immutability, constraints & tenant isolation
│   ├── test_health.py          # Comprehensive test cases for /health & routing
│   └── test_schemas.py         # Comprehensive tests for validation, serialization & governance invariants
├── .venv/                      # Isolated Python virtual environment (ignored in git)
├── pytest.ini                  # Pytest configuration
├── requirements.txt            # Locked backend dependencies
└── README.md                   # Backend documentation & setup guide
```

---

## 4. Setup Instructions

### Prerequisites
- Python 3.12+ or 3.14 (Installed: `Python 3.14.6`)
- Git

### 1. Create Virtual Environment
From the workspace root:
```powershell
python -m venv backend\.venv
```

Or from inside `backend/`:
```powershell
cd backend
python -m venv .venv
```

### 2. Activate Virtual Environment
**Windows PowerShell**:
```powershell
.\backend\.venv\Scripts\Activate.ps1
```

**Linux / macOS**:
```bash
source backend/.venv/bin/activate
```

### 3. Install Dependencies
```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

---

## 5. Running the Application Locally

### Development Server with Live Reload
From the workspace root:
```powershell
backend\.venv\Scripts\uvicorn.exe app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

From inside the `backend/` directory:
```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Endpoints Available
- **Root Status**: `GET http://127.0.0.1:8000/`
- **Root Health Check**: `GET http://127.0.0.1:8000/health`
- **Version 1 Health Check**: `GET http://127.0.0.1:8000/api/v1/health`
- **Interactive OpenAPI Documentation (Swagger UI)**: `http://127.0.0.1:8000/docs`
- **Alternative API Documentation (ReDoc)**: `http://127.0.0.1:8000/redoc`

### Example Health Response
```json
{
  "status": "healthy",
  "app_name": "BrandShield AI Backend",
  "version": "0.1.0",
  "environment": "development",
  "timestamp": "2026-11-13T15:36:39.665558Z"
}
```

---

## 6. Running Automated Tests

Run the full pytest suite from the project root:
```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests -v -c backend/pytest.ini
```

Or from inside `backend/`:
```powershell
pytest tests -v
```

### Test Coverage Highlights
- `test_health_check_root`: Validates `GET /health` returns 200, valid JSON headers, and matching Pydantic schema with ISO-8601 UTC timestamp.
- `test_health_check_v1`: Validates versioned route `GET /api/v1/health`.
- `test_root_discovery`: Validates `GET /` service metadata and discovery links.
- `test_not_found_returns_structured_error`: Validates structured 404 error responses for unmapped routes.
- `test_openapi_docs_availability`: Validates OpenAPI JSON schema generation exposes `/health` and `/api/v1/health`.
- `test_dev_cors_headers_allowed`: Validates preflight CORS headers for configured development origins.
- `test_dev_cors_unauthorized_origin_rejected`: Verifies unauthorized origins do not receive CORS allow headers.
- `test_cors_origins_comma_separated_parsing`: Validates string-based comma-separated origin parsing in Settings.
- `test_production_rejects_default_dev_origins`: Ensures production environment rejects unconfigured or localhost fallback origins.
- `test_production_rejects_localhost_origin`: Rejects explicit localhost or loopback origins in production.
- `test_production_rejects_insecure_http_scheme`: Requires HTTPS scheme for all production origins.
- `test_production_valid_origins_and_restricted_methods`: Confirms valid production origins and restricts allowed methods and headers.
- `test_complete_entity_graph_and_relationships`: Verifies complete 10-table ORM graph instantiation, foreign keys, cascading deletes, and 1:N evidence citations per violation.
- `test_audit_entry_immutability`: Verifies immutable audit ledger events reject modifications and deletions via `ImmutableAuditError`.
- `test_database_check_constraints`: Verifies database-level check constraints enforcing human-only approval invariants and mandatory reviewer feedback.
- `test_tenant_isolation_filtering`: Verifies multi-tenant isolation and organizational query scoping.
- `test_cascade_delete_integrity`: Verifies cascading deletion boundaries and foreign-key integrity.
- `test_database_engine_options`: Verifies connection pool sizing and lifecycle defaults.

---

## 7. Database Migrations (Alembic)

The backend uses **Alembic** for relational database migrations against PostgreSQL.

### Generate SQL Offline (Dry Run)
Generate DDL upgrade script without applying changes to a live database:
```powershell
backend\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head --sql
```

Generate DDL downgrade script:
```powershell
backend\.venv\Scripts\alembic.exe -c backend/alembic.ini downgrade 0001_initial_core_schema:base --sql
```

### Apply Migrations to a Live PostgreSQL Database
```powershell
backend\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head
```

---

## 8. Current Status & Next Steps

- [x] **Phase 1: Project Initialization** (Completed)
- [x] **Phase 2A: Backend Foundation & Phase 2A.1 CORS Hardening** (Completed)
  - Isolated Python 3.14 virtual environment configured.
  - FastAPI application initialized with CORS, lifespan, and structured error handlers.
  - Health check endpoints (`/health` and `/api/v1/health`) functional and tested.
  - Dynamic CORS environment separation implemented and verified (localhost rejected in production, HTTPS enforced, restricted methods and headers).
- [x] **Phase 2B: Core Data Models & Schemas** (Completed)
  - Pydantic v2 schemas defined for Brand Guidelines, Submissions, Violations, and Reviews.
  - Mandatory evidence citations enforced for every reported violation.
  - Inviolable human authorization invariant enforced: AI suggestions strictly separated from human decisions, auto-approval strictly forbidden.
- [x] **Phase 2C: Database Architecture Planning** (Completed & Approved)
  - Production-ready schema designed with tenant isolation, immutable audit ledger, and database check constraints.
- [x] **Phase 2D: Database Implementation** (Completed)
  - Configured SQLAlchemy 2.x with asynchronous database sessions and connection pooling.
  - Implemented 10 relational models: `Organization`, `User`, `BrandGuideline`, `ContentSubmission`, `ComplianceReport`, `RuleViolation`, `EvidenceCitation`, `CorrectionSuggestion`, `ReviewDecision`, `AuditEntry`.
  - Configured Alembic migration environment and created initial baseline migration `0001_initial_core_schema`.
  - Verified static SQL generation for both upgrade and downgrade paths.
  - Enforced audit log immutability via ORM lifecycle events (`ImmutableAuditError`).
  - Implemented database-level check constraints enforcing human-only approval invariants (`chk_submission_approved_has_review`, `chk_audit_human_approval_only`).
  - Automated test suite expanded to 35 tests with 100% pass rate.
- [ ] **Phase 3: Brand Knowledge Ingestion & Vector Retrieval** (Recommended Next Phase)
  - Configure PostgreSQL `pgvector` extension and vector embedding models.
  - Ingest brand guidelines, style rules, and terminologies into vector collections.
  - Implement hybrid semantic + lexical search for evidence retrieval.

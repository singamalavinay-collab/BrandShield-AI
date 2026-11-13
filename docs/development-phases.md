# BrandShield AI — Development Phases & Implementation Roadmap

**Event**: CodeNova India 2026 Round 2  
**Target Product**: BrandShield AI — Intelligent Brand-Governance Platform

This document establishes the structured, incremental roadmap for the design, development, testing, and final submission packaging of BrandShield AI.

---

## Roadmap Overview

```mermaid
flowchart LR
    P1["Phase 1: Project Initialization"] --> P2["Phase 2: Data Models & Backend API"]
    P2 --> P3["Phase 3: AI Engine & LangGraph"]
    P3 --> P4["Phase 4: Frontend & Human Review UI"]
    P4 --> P5["Phase 5: End-to-End Testing & Submission"]

    classDef done fill:#22c55e,stroke:#15803d,color:#ffffff;
    classDef planned fill:#3b82f6,stroke:#1d4ed8,color:#ffffff;

    class P1 done;
    class P2,P3,P4,P5 planned;
```

---

## Phase 1: Project Initialization & Environment Setup (CURRENT PHASE)

- [x] Verify environment versions (Node.js, npm, Python, pip, Git).
- [x] Verify Git repository boundary; isolate from parent user-profile directory.
- [x] Initialize Git repository inside `BrandShield AI`.
- [x] Configure comprehensive `.gitignore` (node_modules, .venv, .env, caches, archives).
- [x] Establish clean monorepo folder structure (`frontend/`, `backend/`, `docs/`).
- [x] Document submission ZIP specification and protocol.
- [x] Author core documentation (`README.md`, `docs/architecture.md`, `docs/development-phases.md`, `docs/submission-spec.md`).
- [x] Validate zero placeholder/mock code introduced.

**Status**: **COMPLETED** (Pending user review and approval to proceed to Phase 2).

---

## Phase 2: Core Data Models, Database Integration & API Foundation (PLANNED)

### Objectives
- Configure backend virtual environment (`backend/.venv`) and install core dependencies (FastAPI, Pydantic, SQLAlchemy/asyncpg, uvicorn).
- Define Pydantic request/response schemas for:
  - Brand guidelines, terminology rules, and facts.
  - Content submissions (copy, target channels, metadata).
  - Compliance reports and violations.
  - Human review decisions and audit history.
- Set up connection to managed PostgreSQL with `pgvector` extension enabled.
- Implement REST API endpoints:
  - `/api/v1/guidelines`: CRUD operations for brand guidelines and assets.
  - `/api/v1/submissions`: Submit content, fetch analysis status.
  - `/api/v1/reviews`: Submit human decisions (approve, reject, revise, edit).
  - `/api/v1/audit`: Retrieve immutable revision and approval history.
- Write initial backend unit and integration tests using `pytest` and `httpx`.

---

## Phase 3: AI Engine, LangGraph Orchestration & Verification Workflow (PLANNED)

### Objectives
- Build provider abstraction layer for LLM and Embedding models (allowing dynamic configuration of providers without vendor lock-in).
- Implement document chunking and vector embedding pipeline into PostgreSQL `pgvector`.
- Build LangGraph stateful graph:
  - **Retrieval Node**: Query relevant guidelines and extract deterministic rule sets.
  - **Audit Node**: Check tone, prohibited terms, factual consistency, and messaging pillars.
  - **Explanation Node**: Extract exact source quotes and formulate rule violation rationales.
  - **Suggestion Node**: Generate compliant alternatives preserving authorial intent.
- Implement structured output validation to guarantee JSON outputs strictly match Pydantic schemas.
- Implement test suite for violation detection accuracy, citation correctness, and edge-case handling.

---

## Phase 4: Frontend Development & Human-in-the-Loop Review UI (PLANNED)

### Objectives
- Scaffold modern React + TypeScript + Vite + Tailwind CSS application in `frontend/`.
- Build responsive, professional UI components:
  - **Navigation & Brand Header**: Clean SaaS aesthetic.
  - **Brand Assets Manager**: Ingest, edit, and organize guidelines, facts, and forbidden terms.
  - **Content Submission Form**: Rich text or markdown input with channel selection.
  - **Violation Dashboard**: Severity badges (Critical, High, Medium, Low), collapsible violation cards, and direct guideline citations.
  - **Interactive Diff & Suggestion Viewer**: Visual comparison between original text and AI-suggested corrections.
  - **Human Review Actions Console**: Primary action buttons for **Approve**, **Reject**, **Request Revision**, and **Edit & Approve**.
  - **Audit Log & History View**: Chronological timeline of all changes and sign-offs.
- Integrate frontend client with FastAPI backend endpoints.
- Build frontend tests and verify cross-browser responsiveness.

---

## Phase 5: Verification, Security Audits, Packaging & Submission (PLANNED)

### Objectives
- Run full automated test suite (backend pytest + frontend build/tests).
- Verify end-to-end user journey from guideline ingestion to human approval.
- Execute security audit:
  - Confirm no API keys or credentials exist in codebase.
  - Confirm `.env` files are excluded from version control.
  - Confirm CORS and input validation prevent injection or data leakage.
- Assemble final submission archive: `BrandShield-AI-Submission.zip`.
- Perform pre-delivery integrity checks (archive extractability, complete source inclusion, zero secret leakage, execution verification).
- Deliver final verification report for CodeNova India 2026 Round 2.

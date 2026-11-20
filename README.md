# BrandShield AI — Intelligent Brand-Governance Platform

> **CodeNova India Round 3 Release**  
> *An enterprise-grade, agentic brand compliance platform with multimodal verification and inviolable human-in-the-loop governance.*

---

## 1. Project Overview & Mission

**BrandShield AI** is an enterprise brand-governance system engineered to inspect, audit, and verify corporate communications across diverse media before public dissemination. It ensures that marketing copy, announcements, social campaigns, advertising creative, visual assets, audio recordings, video content, and executive presentations adhere strictly to approved brand standards, tone directives, trademark conventions, and verified factual evidence.

In modern multi-channel marketing, editorial teams struggle with:
- **Cross-Modality Inconsistencies:** Text, imagery, spoken dialogue, and video creative reviewed in isolation without holistic brand enforcement.
- **Unverified & Outdated Claims:** Product statements and metrics that contradict current approved facts or lack empirical backing.
- **Visual Brand Drift:** Improper logo placement, unapproved color palette deviations, and missing mandatory disclaimers.
- **Editorial Bottlenecks & Audit Exposure:** Manual review queues with zero cryptographic provenance or immutable audit logging.

BrandShield AI resolves this through a hybrid pipeline combining **deterministic pattern matching**, **multimodal computer vision and speech transcription**, **stateful LangGraph agentic orchestration**, and **PostgreSQL Row-Level Security (RLS)** — anchored by an unbreakable architectural invariant:

> **Inviolable Governance Invariant**:  
> The AI agent analyzes, categorizes risks, extracts claims, and suggests corrections, but **never authorizes final approval**. Publishing decisions strictly require explicit human review and cryptographic sign-off. Creator self-approval is blocked at the database and API layer (`403 Forbidden`).

---

## 2. Production Deployment Status & Endpoints

| Component | Target Platform | Live Public Endpoint | Current Status |
| :--- | :--- | :--- | :--- |
| **Frontend SPA** | Vercel | [https://brandshield-ai-original.vercel.app/](https://brandshield-ai-original.vercel.app/) | Deployed & Active (SPA Client) |
| **Backend API** | Render | [https://brandshield-ai-64k9.onrender.com](https://brandshield-ai-64k9.onrender.com) | Deployed & Operational (`/health` HTTP 200) |
| **Database** | Neon Serverless | `ep-dry-term-aork65r1...neon.tech/neondb` | Synchronized at Migration Revision `0007` |

> [!NOTE]
> **Deployment Status Distinction:**  
> The live cloud endpoints above currently host the verified production baseline deployment with core authentication, guideline management, and initial inspection routes. The complete **CodeNova India Round 3 release** (featuring the unified 5-modality upload pipeline, candidate guideline extraction, and claim verification engine) is verified and tested locally, and will become active on the live URLs upon final repository synchronization and cloud redeployment.
>
> **AI Provider Configuration:**  
> The system is designed with **free-tier safe fallback resilience**. When an external `GEMINI_API_KEY` is present, semantic reasoning and multimodal visual analysis are handled by `gemini-2.5-flash` with a strict client-side 5 RPM rate limit. When an API key is unconfigured or rate-limited, BrandShield AI falls back honestly and deterministically to local regex, dictionary, visual heuristic, and human-review flags without error and without invoking paid third-party fallback APIs.

---

## 3. Unified Multi-Input System (5 Supported Modalities)

BrandShield AI provides a single unified submission workspace accepting content across five distinct media modalities:

1. **Text**: Direct text input and pasted markdown copy for press releases, social captions, newsletters, and ad copy.
2. **Images**: JPEG, PNG, and WebP asset analysis, including high-resolution graphics and direct mobile camera capture (`capture="environment"`). Evaluates logo presence, clear space, brand color palette compliance, and OCR text.
3. **Audio**: MP3 and WAV recording ingestion with client-side audio decoding and spoken-dialogue claim extraction.
4. **Video**: MP4 and WebM visual frame and spoken-content evaluation with timestamped violation tracking.
5. **Documents**: PDF and DOCX multi-page document parsing for corporate guidelines, whitepapers, and brand manuals.

All file uploads are streamed in chunks, protected by a strict **10MB ceiling**, verified with magic-byte content sniffing, processed in ephemeral temporary storage (`/tmp/brandshield_uploads`), and immediately unlinked after analysis to ensure zero persistent media retention.

---

## 4. Key Governance & Intelligence Engines

```mermaid
flowchart TD
    subgraph Input["Unified Multi-Input Workspace"]
        T[Text Copy]
        I[Image / Camera]
        A[Audio File]
        V[Video File]
        D[PDF / DOCX]
    end

    subgraph Preprocessing["Multimodal Preprocessing Service"]
        Val[MIME & Magic-Byte Validator]
        Ext[Text / OCR / Audio Extractor]
        Tmp[Ephemeral /tmp Isolation]
    end

    subgraph Engines["Compliance & Verification Layer"]
        Risk[Multi-Factor Risk Scorer<br/>(Score 0-100, Multipliers)]
        Claim[Claim Verification Engine<br/>(Evidence Citations & Provenance)]
        Visual[Visual Brand Compliance<br/>(Logos, Colors, OCR, Bounding Boxes)]
        Ingest[Intelligent Guideline Auto-Drafting<br/>(Candidate Guidelines Ledger)]
    end

    subgraph Database["Database & Security (Neon PostgreSQL)"]
        RLS[Forced Row-Level Security]
        Audit[Immutable Audit Ledger<br/>(Triggers Block UPDATE/DELETE)]
        Dual[Dual-Role Separation<br/>(neondb_owner vs brandshield_app)]
    end

    subgraph Governance["Human-in-the-Loop Gateway"]
        Console[Reviewer Decision Console]
        Decide{Review Decision}
        Approve[Approved for Publish]
        Revise[Revision Requested]
    end

    Input --> Val --> Tmp --> Ext
    Ext --> Engines
    Engines --> Database
    Engines --> Console
    Console --> Decide
    Decide -->|Reviewer Sign-Off| Approve
    Decide -->|Changes Required| Revise
```

### A. Multi-Factor Risk Assessment Engine (Phase 1, Milestone 1)
- Computes an aggregate risk score (0.0 to 100.0) and assigns an actionable severity tier (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- Applies dynamic channel multipliers (e.g., high-risk external broadcast vs low-risk internal wiki) and target audience sensitivity weighting.
- Enforced at the database layer with PostgreSQL `CHECK` constraints on `compliance_reports`.

### B. Intelligent Rule Ingestion & Auto-Drafting Engine (Phase 1, Milestone 2)
- Parses raw PDF and Word guidelines to extract structured brand rules (directive, approved examples, prohibited examples, severity).
- Stages drafted rules in an isolated `candidate_guidelines` table with an append-only audit ledger (`candidate_guideline_audits`).
- Candidates remain quarantined and are never used as active compliance criteria until explicitly approved by an Organization Admin.

### C. Dynamic Adaptive Rules Engine (Phase 1, Milestone 3)
- Evaluates rule applicability dynamically based on target channel, audience, and media type.
- Ensures rules targeting social media hashtags or print disclaimers do not trigger spurious violations on internal memos.

### D. Claim Verification & Fact-Checking Engine (Phase 1, Milestone 4)
- Extracts factual assertions and verifies them exclusively against active, approved brand knowledge records.
- Categorizes claims into rigorous verdicts: `VERIFIED`, `UNSUPPORTED`, `OUTDATED`, `CONTRADICTORY`, or `NEEDS_HUMAN_REVIEW`.
- Outdated claims require identification of both the superseded record and the newer approved source.
- Preserves full evidence provenance (source document title, quotation, and confidence score).
- Stored in the dedicated `claim_verifications` table with forced RLS.

### E. Visual Brand Compliance Engine (Phase 2, Stage 2C)
- Validates logo usage, positioning, and required clear-space ratios.
- Compares visual color signatures against approved hex palettes (such as `#0F172A` Slate Dark, `#2563EB` Cobalt, `#059669` Emerald).
- Emits normalized bounding box coordinates (`[ymin, xmin, ymax, xmax]`) for visual violations.
- Pinpoints video infractions with millisecond timestamp markers.

### F. Human-in-the-Loop Review & Audit Ledger
- State machine transition gates require explicit human sign-off before content can leave `UNDER_REVIEW` status.
- Reviewer approval utilizes pessimistic database row locking (`with_for_update`) to prevent race conditions.
- Every state transition, edit, and decision writes an entry to `audit_entries`, protected by database triggers that abort any `UPDATE` or `DELETE` operations.

---

## 5. Technology Stack

### Frontend Client
- **Framework:** React 18 with TypeScript 5
- **Build Tool:** Vite 6
- **Styling:** Tailwind CSS 3 with PostCSS and Autoprefixer
- **Icons & Visuals:** Lucide React
- **Architecture:** Hash-based SPA routing, tenant-isolated state, mobile-responsive layout with environment camera bindings

### Backend Engine
- **Runtime:** Python 3.12 / 3.14+
- **API Framework:** FastAPI (Asynchronous ASGI)
- **Data Validation:** Pydantic v2 & Pydantic-Settings
- **Server:** Uvicorn with ASGI proxy headers
- **Document Extractors:** `pypdf` (multi-page PDF) and native XML parsing (`word/document.xml` for DOCX)
- **AI Orchestration:** LangGraph & LangChain-Core

### Database & Security
- **Platform:** Neon Serverless PostgreSQL
- **ORM & Migrations:** SQLAlchemy 2 (asyncpg) with Alembic (Revision `0007`)
- **Isolation:** PostgreSQL Row-Level Security (`ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`)
- **Dual-Role Model:**
  - `neondb_owner`: Administrative migration account for DDL execution.
  - `brandshield_app`: Runtime application role granted least-privilege DML (`SELECT, INSERT, UPDATE, DELETE`) with no DDL or Alembic rights.
- **Authentication:** Salted bcrypt password hashing with constant-time verification; JWT tokens signed with HS256 carrying tenant organization scoping.

---

## 6. Verification & Test Results

The entire BrandShield AI test suite has been executed and verified in the local environment:

```text
================================== Test Summary ==================================
Backend Test Suite (pytest):
  - Total Tests:  340
  - Passed:       340
  - Failed:       0
  - Duration:     3m 17s
  - Coverage:     API endpoints, risk scoring, claim verification, multimodal
                  validation, candidate guidelines, database RLS, and security.

Frontend Test Suite (node --test):
  - Total Tests:  70 (across 8 test suites)
  - Passed:       70
  - Failed:       0
  - Duration:     1.05s
  - Coverage:     Multimodal workspace invariants, camera capture, 10MB bounds,
                  remediation authority, tenant isolation, role permissions.

Production Build Verification:
  - Command:      tsc -b && vite build
  - Status:       Clean compilation (0 errors, 0 warnings)
  - Duration:     7.37s
==================================================================================
```

---

## 7. Local Setup & Execution Guide

### Prerequisites
- **Node.js**: v20+ (Verified on Node v22 / v24)
- **Python**: v3.12+ / v3.14 (Verified with Python 3.14.6)
- **PostgreSQL**: Neon cloud instance or local PostgreSQL 16+

### 1. Repository Setup
```bash
git clone https://github.com/singamalavinay-collab/BrandShield-AI.git
cd BrandShield-AI
```

### 2. Backend Configuration & Startup
```bash
cd backend

# Create and activate Python virtual environment
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install required dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your PostgreSQL database URL, JWT secret, and optional Gemini key

# Run database schema migrations
python -m alembic upgrade head

# Start development API server
uvicorn app.main:app --reload --port 8000
```
Backend API interactive documentation will be accessible at `http://127.0.0.1:8000/docs`.

### 3. Frontend Client Setup & Startup
```bash
cd ../frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```
Open `http://localhost:5173` in your browser.

### 4. Running Automated Tests
```bash
# Run complete backend pytest suite
cd backend
python -m pytest

# Run complete frontend test suite
cd ../frontend
npm test

# Run frontend production build check
npm run build
```

---

## 8. Repository Structure

```text
BrandShield-AI/
├── backend/                              # FastAPI asynchronous backend
│   ├── alembic/                          # Alembic database migrations (0001 - 0007)
│   ├── app/
│   │   ├── api/v1/                       # REST routes (auth, guidelines, submissions, reviews, candidate rules)
│   │   ├── core/                         # Config, security, database engine, bootstrap
│   │   ├── engine/                       # Risk scorer, claim verifier, evaluator, graph
│   │   │   ├── multimodal/               # Ingestion, validation, temp manager, service
│   │   │   └── rules/                    # Deterministic, adaptive, and visual compliance rules
│   │   ├── models/                       # SQLAlchemy models (User, Submission, Report, ClaimVerification, etc.)
│   │   └── schemas/                      # Pydantic validation schemas
│   ├── tests/                            # 340 automated backend unit and integration tests
│   ├── Dockerfile                        # Multi-stage container definition
│   └── requirements.txt                  # Python dependencies
│
├── frontend/                             # React 18 + TypeScript + Vite SPA
│   ├── src/
│   │   ├── components/                   # Navigation, media badges, modal dialogs, layout
│   │   ├── pages/                        # Workspace, Review, Analysis Results, Guidelines, Team
│   │   ├── services/                     # Typed API client with cold-start recovery
│   │   ├── tests/                        # 70 frontend behavioral and invariant tests
│   │   └── types/                        # TypeScript domain interfaces
│   ├── package.json                      # Scripts and dependencies
│   ├── tailwind.config.js                # Tailwind CSS design system configuration
│   └── vite.config.ts                    # Vite build configuration
│
├── docs/                                 # Technical architecture & phase documentation
│   ├── architecture.md                   # System design & database schema specifications
│   ├── development-phases.md             # CodeNova Round 3 roadmap & implementation milestones
│   └── submission-spec.md                # Submission archive protocol
│
├── .gitignore                            # Comprehensive secret, environment, and build shielding
└── README.md                             # Release documentation
```

---

## 9. Security & Confidentiality Safeguards

- **Credential Hygiene:** No real passwords, database connection strings, JWT signing keys, or private judge credentials are committed to version control.
- **Environment Exclusions:** `.env` and `.env.*` files are strictly excluded via `.gitignore`.
- **Media Ephemerality:** Uploaded media streams are written only to ephemeral storage (`/tmp/brandshield_uploads`), strictly bounded to 10MB, and deleted immediately following analysis.
- **Tenant Boundary Defense:** All database queries are bound by PostgreSQL Row-Level Security, preventing cross-tenant information disclosure even under direct SQL injection scenarios.

# BrandShield AI — Submission Package Specification & Verification Protocol

**Target Archive**: `BrandShield-AI-Submission.zip`  
**Event**: CodeNova India 2026 Round 2  
**Current Status**: **SPECIFIED ONLY — NOT GENERATED IN PHASE 1**

---

## 1. Important Phase Policy

> [!IMPORTANT]
> The final submission ZIP (`BrandShield-AI-Submission.zip`) **must not** be generated during Phase 1. It will be constructed only during Phase 5, strictly after full implementation, automated test execution, and pre-delivery verification.

---

## 2. Mandatory Archive Contents

When assembled in Phase 5, the submission ZIP must contain:

1. **Complete Frontend Source Code**:
   - `frontend/src/` (all components, pages, hooks, services, types)
   - `frontend/public/`
   - `frontend/package.json` and package manager lockfile
   - `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.js`
   - `frontend/index.html`
2. **Complete Backend Source Code**:
   - `backend/app/` (all API routers, models, schemas, services, AI orchestration graph)
   - `backend/requirements.txt`
   - `backend/tests/` (complete automated test suite)
3. **Configuration Templates**:
   - `.env.example` templates for frontend and backend (with dummy variable names, zero secrets)
   - `.gitignore`
4. **Documentation**:
   - Root `README.md` with complete setup, architecture, and execution instructions
   - `docs/` folder containing:
     - `architecture.md`
     - `development-phases.md`
     - `submission-spec.md`
5. **Evaluation Reports & Test Artifacts**:
   - Automated test run outputs and verification summaries generated during Phase 5.

---

## 3. Strict Exclusions

The archive must strictly exclude:

| Item | Rationale |
| :--- | :--- |
| `node_modules/` | Heavy dependencies recreated via `npm install` |
| `.venv/`, `venv/`, `__pycache__/` | Python virtual environments and bytecode |
| `.env`, `.env.local` | Sensitive environment files and credentials |
| API keys, passwords, secrets | Zero tolerance for leaked credentials |
| Private DB connection strings | Sensitive infrastructure access |
| `dist/`, `build/`, `.turbo/` | Generated build artifacts recreatable from source |
| `*.tmp`, `*.log`, `Thumbs.db`, `.DS_Store` | OS and temporary files |
| `.git/` | Git internal metadata (archive must represent clean source release) |

---

## 4. Pre-Delivery Verification Checklist (Phase 5 Gate)

Before claiming the archive is ready, the following 6 gates must pass:

- [ ] **Gate 1: Source Completeness** — Verify all required frontend and backend source files, configuration manifests, and documentation are present.
- [ ] **Gate 2: Archive Extractability** — Perform a test extraction to an isolated temporary directory and verify checksums / folder integrity.
- [ ] **Gate 3: Zero-Secret Audit** — Grep and scan the archive contents to confirm zero API keys, private passwords, tokens, or private connection strings exist.
- [ ] **Gate 4: Test Suite Validation** — Confirm all automated tests pass with 100% green status prior to archive creation.
- [ ] **Gate 5: Standalone Execution Verification** — Verify that following the instructions in `README.md` on the extracted project starts the backend and frontend without external hidden dependencies.
- [ ] **Gate 6: Submission Placement** — Place `BrandShield-AI-Submission.zip` in a dedicated `submission/` directory and calculate its SHA-256 hash.

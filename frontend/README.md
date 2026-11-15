# BrandShield AI — Frontend Client

> **CodeNova India 2026 Round 2**  
> *Phase 3A: Frontend Foundation & UI Development*

---

## 1. Overview
The frontend of **BrandShield AI** is an enterprise-grade, responsive single-page web application built with **React**, **TypeScript**, **Vite**, and **Tailwind CSS**. Designed for brand managers, compliance officers, and content creators, it provides an intuitive, high-polish SaaS console for managing brand guidelines, submitting content for verification, analyzing AI-identified violations, and executing human-in-the-loop governance sign-offs.

---

## 2. Technology Stack
- **Framework**: React 18 (`18.3.1`) & TypeScript (`5.7.2`)
- **Build Tool**: Vite (`6.1.0`)
- **Styling**: Tailwind CSS (`3.4.17`) & PostCSS (`8.4.49`)
- **Icons**: Lucide React (`1.16.0`)
- **API Client**: Native `fetch` with AbortController timeout handling and backend `/health` probe

---

## 3. Implemented Pages & Core Modules

1. **Dashboard (`DashboardPage`)**:
   - Executive metrics grid: Active Guidelines, Monitored Submissions, Pending Human Reviews, and Overall Compliance Rate.
   - Real-time backend API connectivity badge with live ping capability to `GET /health`.
   - Recent content submissions table with status pills and direct one-click navigation to Analysis or Review.
   - Immutable audit ledger activity preview showing actor types (`human` vs `system`) and lifecycle transitions.

2. **Brand Guidelines Knowledge Hub (`GuidelinesPage`)**:
   - Filterable guidelines catalogue with category tabs (`Tone of Voice`, `Terminology`, `Formatting`, `Legal & Regulatory`, `Prohibited Claims`, `Trademark Usage`).
   - Severity tags (`Critical`, `High`, `Medium`, `Low`) and search bar filtering by name, clause, or tag.
   - Verified directive cards displaying approved phrasing examples, prohibited phrasing examples, and active status toggles.
   - "Add Brand Rule" slide-over drawer with strict client-side validation.

3. **Content Submission Workspace (`SubmissionPage`)**:
   - Focused drafting workspace for marketing copy, social posts, emails, and press releases.
   - Target channel selector (Twitter/X, LinkedIn, Email Newsletter, Blog Post, Paid Ad, Press Release).
   - Real-time word counter and character counter with Twitter 280-char threshold tracking.
   - Quick preset loader ("Sample with Violations", "Compliant Sample") for immediate end-to-end testing.
   - Form validation enforcing non-empty title (min 3 chars) and content (min 10 chars).

4. **Compliance Inspection Results (`AnalysisResultsPage`)**:
   - Overall compliance verdict banner (Compliant vs Non-Compliant with flagged violation count).
   - Submitted copy inspector with inline highlighted marks corresponding to detected violations.
   - Discrete evidence-backed violation cards with exact flagged text, character spans, and rule explanations.
   - **Grounding Evidence Citations (1:N)**: Exact source document clauses, section references, and confidence scores (e.g. 99%).
   - Direct CTA to inspect AI correction suggestions.

5. **Evidence-Backed Correction Studio (`CorrectionsPage`)**:
   - Side-by-side comparison between original draft containing violations and proposed remediated text.
   - Diff highlights for removed text vs approved suggested phrasing.
   - Rationale explanation card detailing why each recommendation aligns with brand directives.
   - Explicit advisory governance notice: AI suggestions are non-binding proposals; AI cannot independently alter live assets.
   - "Stage Remediated Draft for Human Review" button to carry the clean draft into the Review console.

6. **Human Review & Authorization Console (`ReviewPage`)**:
   - Dedicated Human-in-the-Loop Governance Console enforcing the central architectural invariant: **The AI must never make final approval decisions without human authorization.**
   - Verified reviewer credential card displaying identity ("Sarah Jenkins • Senior Brand Compliance Officer").
   - 4 Human Decision Actions:
     - **Edit & Approve**: Allows the human editor to refine text in an interactive editor and authorize publication.
     - **Approve As-Is**: Signs off on compliant drafts.
     - **Request Revision**: Sends draft back to author (requires mandatory human feedback notes).
     - **Reject**: Formally declines publication (requires mandatory justification).
   - Immutable Audit Ledger preview displaying the exact database audit record generated upon authorization.

---

## 4. Design Direction & Visual System
- **Surfaces**: Clean white cards (`bg-white`) on neutral slate canvas (`bg-slate-50`).
- **Typography**: Dark navy headings and body (`text-slate-900`, `text-slate-800`) with high-contrast Inter font.
- **Accents**: Subtle blue (`bg-blue-600`, `text-blue-600`) and teal (`text-teal-400`, `bg-teal-50`) badges.
- **Elevation**: Refined light borders (`border-slate-200`) and subtle shadows (`shadow-sm`, `shadow-subtle`).
- **Responsive Layout**: Desktop fixed sidebar navigation (256px) + responsive mobile drawer navigation toggle.

---

## 5. Directory Structure
```text
frontend/
├── dist/                       # Production build output
├── public/                     # Static assets
├── src/
│   ├── components/
│   │   ├── common/             # Reusable UI components
│   │   │   ├── AlertBanner.tsx # Governance, warning, and info banners
│   │   │   ├── EmptyState.tsx  # Polished empty state placeholders
│   │   │   └── StatusBadge.tsx # Submission status & severity badge pills
│   │   └── layout/
│   │       ├── Navbar.tsx      # Top bar with backend health & profile
│   │       └── Sidebar.tsx     # Responsive navigation sidebar
│   ├── data/
│   │   └── initialData.ts      # Transparent demonstration datasets
│   ├── pages/
│   │   ├── AnalysisResultsPage.tsx
│   │   ├── CorrectionsPage.tsx
│   │   ├── DashboardPage.tsx
│   │   ├── GuidelinesPage.tsx
│   │   ├── ReviewPage.tsx
│   │   └── SubmissionPage.tsx
│   ├── services/
│   │   └── api.ts              # Backend API health client
│   ├── types/
│   │   └── index.ts            # TypeScript interfaces & domain models
│   ├── App.tsx                 # Root application controller
│   ├── index.css               # Tailwind directives & base styles
│   └── main.tsx                # React DOM entrypoint
├── index.html                  # HTML template
├── package.json                # Dependencies and build scripts
├── postcss.config.js           # PostCSS configuration
├── tailwind.config.js          # Tailwind CSS theme extension
├── tsconfig.json               # TypeScript compiler configuration
└── vite.config.ts              # Vite configuration with API proxy
```

---

## 6. How to Run Locally

### Development Server (with Live Reload)
From the project root:
```powershell
npm run dev --prefix frontend
```
Or from inside the `frontend/` directory:
```powershell
cd frontend
npm run dev
```
Open **http://127.0.0.1:5173/** in your browser.

### Production Build & Preview
To build the optimized static distribution:
```powershell
npm run build --prefix frontend
```
To preview the production build locally:
```powershell
npm run preview --prefix frontend
```
Preview server will be served at **http://127.0.0.1:5173/**.

---

## 7. Current Status
- [x] **Phase 3A: Frontend Foundation & UI Development** (Completed)
  - React + TypeScript + Vite + Tailwind CSS scaffolding complete.
  - All 6 core pages implemented with full navigation and responsive layout.
  - Client-side validation active on all forms and review decision inputs.
  - Production build (`npm run build`) passing with zero errors.
  - Zero modifications to backend database models or migrations.
  - All 35 backend tests verified and passing.

# BrandShield AI — Frontend Client

## Overview
The frontend of **BrandShield AI** is a responsive, modern web application designed for brand managers, compliance officers, and content creators. It provides an intuitive interface for managing brand assets, submitting content for verification, analyzing AI-identified violations, and executing human-in-the-loop governance workflows.

## Technology Stack (Planned)
- **Framework**: React (TypeScript)
- **Build Tool**: Vite
- **Styling**: Tailwind CSS
- **Icons & UI Primitives**: Lucide Icons / Headless UI
- **State & Data Fetching**: React Hooks / TanStack Query (or lightweight API client)

## Core Interface Modules (Planned)
1. **Brand Knowledge Hub**: Manage approved guidelines, facts, terminology dictionaries, and messaging rules.
2. **Content Submission Workspace**: Submit drafted marketing copy, social media posts, ad campaigns, and documents.
3. **Compliance & Verification Dashboard**: Interactive violation view highlighting exact rule breaches, severity scores, and cited evidence.
4. **Correction Studio**: Side-by-side comparison of original content with evidence-backed AI recommendations.
5. **Human-in-the-Loop Governance Console**: Review, edit, approve, reject, or request revisions. Final authorization is strictly human-controlled.
6. **Audit & Version History**: Complete timeline of submissions, reviews, edits, and sign-offs.

## Directory Structure (To Be Scaffolding in Phase 2)
```text
frontend/
├── public/                 # Static assets and icons
├── src/
│   ├── assets/             # Brand logos and illustration assets
│   ├── components/         # Reusable UI components (buttons, modals, badges, cards)
│   │   ├── layout/         # Navigation, header, sidebar
│   │   ├── guidelines/     # Guideline management components
│   │   ├── audit/          # Compliance report & violation views
│   │   └── review/         # Human review, diff viewer, approval controls
│   ├── hooks/              # Custom React hooks
│   ├── pages/              # Routed view pages
│   ├── services/           # Backend API integration clients
│   ├── types/              # TypeScript interfaces and schema contracts
│   ├── App.tsx             # Root application component
│   └── main.tsx            # Application entrypoint
├── index.html              # HTML template
├── package.json            # Node dependencies and scripts
├── tsconfig.json           # TypeScript configuration
├── vite.config.ts          # Vite build configuration
└── tailwind.config.js      # Tailwind CSS configuration
```

## Current Status (Phase 1)
- **Status**: Directory initialized and isolated under project repository root.
- **Implementation**: Ready for Phase 2 scaffolding (Vite + React + TypeScript + Tailwind CSS). No mock or unverified code created in Phase 1.

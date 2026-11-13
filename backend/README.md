# BrandShield AI — Backend Engine

## Overview
The backend of **BrandShield AI** is an asynchronous API service and agentic governance engine built with FastAPI and Python. It coordinates brand knowledge indexing, content compliance analysis, violation detection, evidence-backed correction synthesis, and stateful human approval lifecycles.

## Technology Stack (Planned)
- **Runtime**: Python (3.14 environment verified; FastAPI 0.141.1, Pydantic 2.13.4, Uvicorn 0.52.3)
- **Web Framework**: FastAPI (asynchronous ASGI framework)
- **Data Validation & Schemas**: Pydantic v2
- **Database**: Managed PostgreSQL with `pgvector` extension for high-dimensional vector search
- **Database Client / ORM**: SQLAlchemy 2.0 (async) / asyncpg / psycopg
- **Agent & AI Orchestration**: LangGraph, with abstracted LLM & Embedding providers
- **Testing**: pytest, pytest-asyncio, httpx

## Core Architectural Layers (Planned)
1. **API & Routing Layer**: RESTful endpoints with OpenAPI schema generation, authentication, and CORS.
2. **Brand Knowledge Indexer**: Chunking, vector embedding, and relational indexing of brand rules, tone guidelines, facts, and prohibited terms.
3. **Semantic & Rule Verification Engine**: LangGraph-orchestrated workflow combining semantic vector search with deterministic rule checks.
4. **Evidence & Citation Validator**: Ensures every flagged violation and correction suggestion is linked to an exact clause or guideline source.
5. **Human-in-the-Loop State Machine**: Strict governance transition model (`DRAFT` -> `UNDER_REVIEW` -> `REVISION_REQUESTED` | `APPROVED` | `REJECTED`). Enforces the inviolable rule: **AI never issues final approvals**.
6. **Audit & Version History Engine**: Immutable logging of all content iterations and review decisions.

## Directory Structure (To Be Scaffolding in Phase 2)
```text
backend/
├── app/
│   ├── api/                # API router definitions (v1 endpoints)
│   │   ├── deps.py         # Dependency injection (db session, current user)
│   │   ├── guidelines.py   # Guideline management endpoints
│   │   ├── submissions.py  # Content submission & verification endpoints
│   │   └── reviews.py      # Human approval and review endpoints
│   ├── core/               # Application configuration, security, database session
│   │   ├── config.py       # Pydantic Settings & environment variables
│   │   └── database.py     # Database engine and session factory
│   ├── models/             # SQLAlchemy ORM models (guidelines, submissions, reviews)
│   ├── schemas/            # Pydantic request/response validation schemas
│   ├── services/           # Business logic services
│   │   ├── guideline_svc.py# Guideline processing & embedding
│   │   └── submission_svc.py# Submission processing & status transitions
│   ├── ai/                 # AI & agentic orchestration
│   │   ├── providers/      # LLM and embedding client abstractions
│   │   ├── graph.py        # LangGraph workflow definition
│   │   ├── evaluators.py   # Rule violation checking and scoring
│   │   └── prompts.py      # Prompt templates for structured outputs
│   └── main.py             # FastAPI entrypoint application
├── tests/                  # Automated unit and integration tests
├── requirements.txt        # Backend dependencies
└── README.md               # Backend documentation
```

## Current Status (Phase 1)
- **Status**: Directory initialized and isolated under project repository root.
- **Environment Verified**: Python 3.14.6, pip 26.2.2.
- **Implementation**: Ready for Phase 2 backend scaffolding. No mock or unverified code created in Phase 1.

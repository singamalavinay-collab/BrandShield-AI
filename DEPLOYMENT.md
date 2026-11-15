# BrandShield AI — Production Deployment & Operations Guide

This guide documents the procedures for configuring, hardening, migrating, and deploying **BrandShield AI** to production environments.

---

## 1. System Architecture

BrandShield AI follows an enterprise-grade multi-tier architecture:

```
                      Internet / Client Browsers
                                  │
                                  ▼
                   [ Nginx Reverse Proxy / TLS ]
                     (Port 80 / 443 — HTTPS)
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                               ▼
       [ Frontend SPA (React) ]        [ Backend API (FastAPI) ]
       Static Assets / Vite Build      Uvicorn Workers (Port 8000)
                                                  │
                                                  ▼
                                       [ PostgreSQL Database ]
                                        (Port 5432 / asyncpg)
```

---

## 2. Pre-Requisites & Required User Configuration

To deploy BrandShield AI publicly, provide the following operational values:

| Configuration Key | Required For | Description / Example |
| :--- | :--- | :--- |
| `POSTGRES_USER` | Database | PostgreSQL username (e.g., `brandshield_admin`) |
| `POSTGRES_PASSWORD` | Database | High-entropy password (min 16 chars) |
| `POSTGRES_HOST` | Database | Database host address (e.g., `db.internal.brandshield.ai`) |
| `POSTGRES_DB` | Database | Target database name (`brandshield_ai`) |
| `JWT_SECRET_KEY` | Security | 256-bit cryptographically secure secret (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| `BACKEND_CORS_ORIGINS` | Security | Comma-separated HTTPS domains (e.g., `https://app.brandshield.ai,https://brandshield.ai`) |
| `GEMINI_API_KEY` | AI Evaluator | (Optional) Google Gemini API key for semantic compliance evaluation |

---

## 3. Database Migration from SQLite to PostgreSQL

The development database is SQLite (`backend/brandshield_ai.db`). For multi-node concurrency and high availability in production, migrate existing records to PostgreSQL:

### Step 3.1: Create SQLite Snapshot
```bash
# Always backup existing SQLite records prior to migration
cp backend/brandshield_ai.db backend/brandshield_ai.db.backup
```

### Step 3.2: Verify SQLite Source Data (Dry-Run)
```bash
python backend/scripts/migrate_sqlite_to_postgres.py --dry-run
```

### Step 3.3: Execute Live Migration
```bash
# Provide the target PostgreSQL connection string:
python backend/scripts/migrate_sqlite_to_postgres.py \
  --source-db backend/brandshield_ai.db \
  --target-url "postgresql://brandshield:SecurePassword@db-host:5432/brandshield_ai"
```

### Step 3.4: Verify PostgreSQL Target Records
Verify row counts on the PostgreSQL target:
```sql
SELECT 'organizations' as tbl, count(*) FROM organizations UNION ALL
SELECT 'users', count(*) FROM users UNION ALL
SELECT 'brand_guidelines', count(*) FROM brand_guidelines UNION ALL
SELECT 'content_submissions', count(*) FROM content_submissions UNION ALL
SELECT 'compliance_reports', count(*) FROM compliance_reports UNION ALL
SELECT 'audit_entries', count(*) FROM audit_entries;
```

---

## 4. Deployment Option 1: Docker Compose (Recommended)

Docker Compose provides a single-command, reproducible production deployment.

### Step 4.1: Clone and Configure Environment
```bash
cd /opt/brandshield-ai

# Copy and edit production environment variables
cp backend/.env.example backend/.env
# Edit backend/.env with your production secrets
nano backend/.env
```

### Step 4.2: Build and Launch Containers
```bash
docker compose up -d --build
```

### Step 4.3: Verify Container Health
```bash
docker compose ps
docker compose logs -f backend
```

---

## 5. Deployment Option 2: Linux VM (Systemd + Nginx + PostgreSQL)

For deployment directly on an Ubuntu 24.04 LTS instance:

### Step 5.1: Install Dependencies
```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv postgresql nginx certbot python3-certbot-nginx
```

### Step 5.2: Configure Systemd Service (`/etc/systemd/system/brandshield-backend.service`)
```ini
[Unit]
Description=BrandShield AI FastAPI Backend
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/brandshield/backend
EnvironmentFile=/var/www/brandshield/backend/.env
ExecStart=/var/www/brandshield/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4

Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now brandshield-backend
```

### Step 5.3: Deploy Frontend Build
```bash
cd /var/www/brandshield/frontend
npm ci
npm run build
sudo cp -r dist/* /var/www/html/brandshield/
```

### Step 5.4: Obtain SSL/TLS Certificates
```bash
sudo certbot --nginx -d app.brandshield.ai
```

---

## 6. Security Hardening Checklist

- [x] **No Default Secrets**: `JWT_SECRET_KEY` rejected if set to dev default when `ENVIRONMENT=production`.
- [x] **CORS Guard**: Wildcards (`*`) and loopback origins (`localhost`, `127.0.0.1`) strictly rejected in production.
- [x] **OWASP Security Headers**: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security`.
- [x] **Tenant Scoping**: All database operations bound by `organization_id`.
- [x] **Audit Ledger Immutability**: Protected by database triggers preventing `UPDATE` and `DELETE`.
- [x] **Non-Root Execution**: Backend container runs under dedicated unprivileged user (`appuser`, UID 10001).

---

## 7. Rollback Procedure

If a deployment issue occurs:

1. **Service Rollback**:
   ```bash
   docker compose down
   # Switch to previous stable commit / image tag
   docker compose up -d
   ```
2. **Database Rollback**:
   ```bash
   # Revert latest migration step
   cd backend
   alembic downgrade -1
   ```
3. **Emergency SQLite Fallback**:
   If the PostgreSQL target suffers an outage, restore the verified SQLite snapshot:
   ```bash
   cp backend/brandshield_ai.db.backup backend/brandshield_ai.db
   # Update DATABASE_URL=sqlite+aiosqlite:///brandshield_ai.db in .env
   ```

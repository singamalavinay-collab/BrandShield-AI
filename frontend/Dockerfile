# ==============================================================================
# BrandShield AI — Production Frontend Dockerfile
# Multi-stage secure build with Nginx SPA server
# ==============================================================================

# --- Stage 1: Build Stage ---
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies cleanly using lockfile
COPY package*.json ./
RUN npm ci

# Copy frontend source code and configuration
COPY . .

# Build production distribution assets
RUN npm run build

# --- Stage 2: Production Nginx Server ---
FROM nginx:1.27-alpine AS production

# Remove default nginx welcome page
RUN rm -rf /usr/share/nginx/html/*

# Copy production build artifacts from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy optimized Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Health check against Nginx root
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1/ || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

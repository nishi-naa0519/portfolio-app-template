# Stage 1: build the frontend
FROM node:24-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: run the backend, serving the built frontend as static files
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    FRONTEND_DIST_DIR=/app/frontend-dist \
    PORT=8080

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY --from=frontend-build /frontend/dist ./frontend-dist

RUN useradd --create-home appuser
USER appuser

EXPOSE 8080
# Cloud Run already writes a request log for every request, so uvicorn's access log
# would only double the Cloud Logging volume.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]

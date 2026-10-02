FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY edgeguard ./edgeguard
COPY scripts ./scripts
COPY --from=frontend /build/dist ./frontend/dist
RUN useradd --create-home edgeguard && mkdir -p /app/data && chown edgeguard:edgeguard /app/data
USER edgeguard
ENV PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
CMD ["uvicorn","edgeguard.api:create_app","--factory","--host","0.0.0.0","--port","8000","--workers","1"]

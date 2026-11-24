# Single container: builds the React frontend, bakes in synthetic demo documents, serves everything with FastAPI.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt faker reportlab numpy
COPY backend/ backend/
COPY tools/ tools/
COPY deploy/start.sh deploy/start.sh
COPY --from=web /web/dist frontend-dist
# Demo documents are generated at build time (deterministic seed); nothing here is real patient data.
RUN python tools/synth/generate.py --count 60 --seed 42 --extra-labs 5 --out tools/synth/output_demo --clean \
    && useradd -m app && mkdir -p uploads && chown -R app /app
USER app
ENV FRONTEND_DIST=/app/frontend-dist UPLOAD_DIR=/app/uploads COOKIE_SECURE=true
EXPOSE 10000
CMD ["sh", "deploy/start.sh"]

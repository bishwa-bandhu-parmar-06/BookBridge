# BookBridge API (FastAPI). Works on Render, Hugging Face Spaces, Koyeb, Railway, Cloud Run...
#   docker build -t bookbridge-api backend
#   docker run -p 7860:7860 -e GEMINI_API_KEY=... -e FRONTEND_ORIGIN=http://localhost:3000 bookbridge-api
FROM python:3.11-slim-bookworm

# Pango + HarfBuzz are what WeasyPrint needs to make PDFs; fontconfig for its font lookup.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fontconfig fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Behind the hosting platform's proxy: read the real client IP for the upload rate limit.
    TRUST_PROXY_HEADERS=true \
    SESSIONS_DIR=/tmp/bookbridge-sessions \
    PORT=7860

# Run as a normal user (uid 1000, which Hugging Face Spaces requires).
RUN useradd --create-home --uid 1000 app
WORKDIR /home/app/backend

COPY requirements-deploy.txt .
RUN pip install -r requirements-deploy.txt

COPY --chown=app:app app ./app
USER app

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"

# ONE worker on purpose: translation jobs and session locks live in this process's memory.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]

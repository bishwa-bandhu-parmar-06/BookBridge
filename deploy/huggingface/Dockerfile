# Hugging Face Space for the BookBridge API. Upload this file and README.md (next to it) to a
# new Docker Space. It downloads the code from GitHub, so to update the Space after you push:
# Space → Settings → "Factory rebuild".
FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fontconfig fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TRUST_PROXY_HEADERS=true \
    SESSIONS_DIR=/tmp/bookbridge-sessions \
    PORT=7860

# Change this if your GitHub repository has another address.
ARG REPO=https://github.com/bishwa-bandhu-parmar-06/BookBridge.git
ARG BRANCH=main

RUN useradd --create-home --uid 1000 app
WORKDIR /home/app

RUN git clone --depth 1 --branch "$BRANCH" "$REPO" src \
 && pip install -r src/backend/requirements-deploy.txt \
 && mv src/backend backend && rm -rf src \
 && chown -R app:app backend

USER app
WORKDIR /home/app/backend
EXPOSE 7860

# ONE worker on purpose: translation jobs and session locks live in this process's memory.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]

# espero's recorder in a container: the Hyperliquid collector and the daily job, the same code
# launchd runs on the maintainer's Mac. Public data only: no key is copied in (.dockerignore).
#
#   docker compose up -d          # both services (docker-compose.yml)
#   docker compose logs -f        # what they print
#
# See docs/RUNBOOK.md, "Running it in Docker".
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY espero ./espero
RUN pip install -e ".[chart]"

COPY scripts ./scripts
COPY research ./research

# data/ and state/ are volumes; the committed frozen data comes with the bind mount of ./data
VOLUME ["/app/data", "/app/state"]
CMD ["espero", "--help"]

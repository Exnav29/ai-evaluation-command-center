FROM docker.io/library/node:22-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv git sqlite3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/aecc-venv \
 && /opt/aecc-venv/bin/pip install --no-cache-dir \
      "SQLAlchemy>=2,<3" \
      "alembic>=1.13,<2" \
      "pytest>=8,<9" \
      "fastapi>=0.116,<1" \
      "jinja2>=3.1,<4" \
      "httpx>=0.27,<1" \
      "uvicorn>=0.30,<1" \
      "python-multipart>=0.0.9,<1"

ENV PATH="/opt/aecc-venv/bin:/opt/opencode/bin:${PATH}"

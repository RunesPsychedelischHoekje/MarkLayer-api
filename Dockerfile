FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

# Install deps first so Docker caches this layer between code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
# Watermark models (64 MB, checksum-pinned) and the current C2PA trust lists.
# Redeploy now and then to pick up signers newly added to the trust lists.
RUN python scripts/fetch_assets.py

# Hosts like Render/Railway inject $PORT. --proxy-headers trusts X-Forwarded-* from the host's load balancer.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

# The Railway image for server/ (docs/PROPOSAL.md §5.1). Built by Railway from railway.json;
# deploys go out with `railway up` from a clean main (ops.local.txt). Only the server and the
# one renderer module it reuses are copied: nothing from out/, queue/ or the worker.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY lib/week.py lib/week.py
COPY server/ server/

# --no-access-log: access lines record paths, and /u/<token> and /s/<id> are credentials.
# DB_PATH points at the volume (e.g. /data/server.db); PORT is set by Railway.
CMD ["sh", "-c", "exec uvicorn server.app:create_app --factory --host 0.0.0.0 --port \"${PORT:-8000}\" --no-access-log"]

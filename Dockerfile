# Managed cloud builds may not pull from Docker Hub, and a
# `# syntax=` directive would make BuildKit fetch the docker/dockerfile frontend
# from Docker Hub (401). So: no syntax directive, and base from a
# provider-hosted image (which also ships `uv`).
FROM agentkit-prod-public-cn-beijing.cr.volces.com/base/py-simple:python3.12-bookworm-slim-latest

ENV UV_SYSTEM_PYTHON=1 UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt ./
RUN uv pip install -r requirements.txt

COPY . .

# The runtime probes :8000 for readiness — the server must listen here.
EXPOSE 8000
CMD ["python", "main.py"]

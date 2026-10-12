# syntax=docker/dockerfile:1.7
# ---- build: install dependencies into a virtualenv -------------------------------------------
FROM python:3.13-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---- runtime: small image, non-root user ------------------------------------------------------
FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/venv/bin:$PATH"
RUN useradd --create-home --uid 10001 docpilot
WORKDIR /app
COPY --from=build /venv /venv
COPY app ./app
COPY scripts ./scripts
USER docpilot
EXPOSE 8000 9100
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
# One process per container (scale with replicas so Prometheus metrics stay per-process).
# Same image runs the API (default), the worker (`python -m app.worker`) or schema setup (`python -m app.migrate`).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

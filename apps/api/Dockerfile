FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system regimpact && adduser --system --ingroup regimpact regimpact

COPY pyproject.toml ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir .
RUN python -c "import regimpact.main; import regimpact.tasks"
RUN mkdir -p /data/objects && chown -R regimpact:regimpact /data/objects

USER regimpact
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "regimpact.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

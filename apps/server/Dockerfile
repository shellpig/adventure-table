FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/apps/server

COPY apps/server/pyproject.toml ./
COPY apps/server/app ./app
RUN pip install --no-cache-dir .

COPY apps/server/alembic.ini ./
COPY apps/server/alembic ./alembic
COPY data/srd5.1 /app/data/srd5.1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

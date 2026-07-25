FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system bridge && useradd --system --gid bridge --home /app bridge

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic

RUN pip install --upgrade pip && pip install .

USER bridge

EXPOSE 8080

CMD ["sh", "-c", "alembic upgrade head && uvicorn bridge.main:app --host 0.0.0.0 --port 8080"]

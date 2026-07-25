FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin appuser

# 依赖层先行：只有依赖清单或 vendor 变化才会重装依赖，源码改动不再击穿缓存。
COPY pyproject.toml requirements.txt ./
COPY vendor ./vendor
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app ./app
COPY finance_god ./finance_god
COPY scripts ./scripts
COPY server.py ./
COPY alembic.ini ./
COPY alembic ./alembic

# 依赖已在上层满足，仅注册可编辑包本体。
RUN pip install --no-deps -e .
RUN mkdir -p /app/data /app/artifacts/knowledge \
    && chown -R appuser:appuser /app/data /app/artifacts

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

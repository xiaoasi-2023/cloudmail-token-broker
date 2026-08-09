FROM python:3.13-slim

LABEL org.opencontainers.image.title="CloudMail Token Broker" \
    org.opencontainers.image.description="Centralized CloudMail public token broker" \
    org.opencontainers.image.source="https://github.com/xiaoasi-2023/cloudmail-token-broker"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir . \
    && addgroup --system --gid 10001 broker \
    && adduser --system --uid 10001 --ingroup broker --no-create-home broker

USER 10001:10001

EXPOSE 8080

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]

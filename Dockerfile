FROM node:22-alpine AS admin-build

WORKDIR /src/admin-web

COPY admin-web/package.json admin-web/package-lock.json ./
RUN npm ci

COPY admin-web ./
RUN npm run build

FROM python:3.13-slim

LABEL org.opencontainers.image.title="Xiaoasi Mail Gateway" \
    org.opencontainers.image.description="Multi-instance CloudMail mailbox gateway and admin console" \
    org.opencontainers.image.source="https://github.com/xiaoasi-2023/cloudmail-token-broker"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ADMIN_STATIC_DIR=/app/admin

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
COPY --from=admin-build /src/admin-web/dist ./admin
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && pip install --no-cache-dir . \
    && addgroup --system --gid 10001 broker \
    && adduser --system --uid 10001 --ingroup broker --no-create-home broker

EXPOSE 8080 8110

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]

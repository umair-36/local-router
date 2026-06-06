FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOCAL_ROUTER_CONFIG=/etc/local-router/config.yaml

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY local_router ./local_router
COPY models ./models
COPY config/config.docker.yaml /etc/local-router/config.yaml

RUN pip install --no-cache-dir . \
    && mkdir -p /var/lib/local-router /var/log/local-router

EXPOSE 8080
ENTRYPOINT ["local-router"]
CMD ["serve", "--config", "/etc/local-router/config.yaml", "--profile", "opencode"]

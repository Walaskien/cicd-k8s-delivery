FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/Walaskien/cicd-k8s-delivery"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/server.py .

# The version goes in after the dependency layer, so a new commit
# does not re-run pip.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

# Numeric uid: the kubelet can only check runAsNonRoot against a number.
RUN useradd --system --uid 10001 --no-create-home app
USER 10001

EXPOSE 8000

# One worker on purpose: prometheus_client keeps counters per process, so
# several workers would each answer /metrics with their own partial numbers.
# /dev/shm because gunicorn wants a writable tmp dir and the pod root fs is
# read-only.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", \
     "--worker-tmp-dir", "/dev/shm", "--access-logfile", "-", "server:create_app()"]

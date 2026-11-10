import os
import time

from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# Only here so the rollback demo has a way to ship a bad release on purpose.
FAULTS = ("crash-on-start", "unhealthy", "broken-endpoint")

REQUESTS = Counter(
    "http_requests_total", "Requests handled", ["method", "route", "status"]
)
LATENCY = Histogram("http_request_duration_seconds", "Request duration", ["route"])


def create_app():
    fault = os.environ.get("APP_FAULT", "")
    if fault and fault not in FAULTS:
        # a typo in values.yaml should stop the rollout, not be ignored
        raise ValueError(f"unknown APP_FAULT {fault!r}")
    if fault == "crash-on-start":
        raise RuntimeError("APP_FAULT=crash-on-start")

    app = Flask(__name__)
    version = os.environ.get("APP_VERSION", "dev")
    greeting = os.environ.get("GREETING", "hello")

    @app.before_request
    def start_timer():
        g.started = time.perf_counter()

    @app.after_request
    def record_metrics(resp):
        # rule, not the raw path: random 404 urls must not create new series
        route = request.url_rule.rule if request.url_rule else "unmatched"
        REQUESTS.labels(request.method, route, resp.status_code).inc()
        LATENCY.labels(route).observe(time.perf_counter() - g.started)
        return resp

    @app.get("/")
    def index():
        if fault == "broken-endpoint":
            return jsonify(error="simulated failure"), 500
        return jsonify(service="greeter", version=version, message=greeting)

    @app.get("/health")
    def health():
        if fault == "unhealthy":
            return jsonify(status="failing"), 503
        return jsonify(status="ok")

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    return app

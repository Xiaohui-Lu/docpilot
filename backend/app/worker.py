"""Standalone worker process: ``python -m app.worker``. Scale replicas horizontally in Kubernetes."""

import os
import signal

from prometheus_client import start_http_server

from app.config import get_settings
from app.db import init_db
from app.observability import configure_logging
from app.services.jobs import Worker


def main() -> None:
    configure_logging()
    if get_settings().auto_create_schema:
        init_db()
    start_http_server(int(os.environ.get("DOCPILOT_WORKER_METRICS_PORT", "9100")))
    worker = Worker()
    signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    signal.signal(signal.SIGINT, lambda *_: worker.stop())
    worker.run_forever()


if __name__ == "__main__":
    main()

"""One-shot schema setup: ``python -m app.migrate`` (run before API/worker replicas start)."""

from app.db import init_db
from app.observability import configure_logging


def main() -> None:
    configure_logging()
    init_db()
    print("schema ready")


if __name__ == "__main__":
    main()

"""JSONL invocation logging for tool calls and sub-agent runs.

One JSON object per line: {"event", "name", "input", "output", "latency_ms", "error"}.
Used to debug sub-agent routing and to back the portfolio writeup described
in the spec's non-functional requirements.
"""

import functools
import json
import time
from datetime import datetime, timezone

from .config import LOG_PATH


def _write_event(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record["timestamp"] = datetime.now(timezone.utc).isoformat()
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def log_call(event: str):
    """Decorator that logs one JSONL record per call of the wrapped function."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            record = {"event": event, "name": fn.__name__, "input": kwargs or args}
            try:
                result = fn(*args, **kwargs)
                record["output"] = result
                return result
            except Exception as exc:  # noqa: BLE001 - log then re-raise
                record["error"] = str(exc)
                raise
            finally:
                record["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
                _write_event(record)

        return wrapper

    return decorator

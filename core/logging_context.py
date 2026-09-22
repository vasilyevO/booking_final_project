from __future__ import annotations

import contextvars
import logging
import uuid

# a ContextVar rather than threading.local: in async code a single thread
# serves several coroutines, and a thread-local would leak between them.
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def get_request_id() -> str:
    """
    The current request's identifier, or "-" outside a request
    (management command, shell, test).
    """
    return _request_id.get()


def set_request_id(value: str):
    """
    Returns a token for reset() — always call it in finally, otherwise the
    value leaks into the next request handled by the same worker.
    """
    return _request_id.set(value)


def reset_request_id(token) -> None:
    _request_id.reset(token)


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class RequestIdFilter(logging.Filter):
    """
    Injects request_id into every log record. The filter is attached to the
    handler rather than a logger: that way it applies to every record,
    including those from Django and third-party libraries. Otherwise a
    format containing %(request_id)s would break on a foreign record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True
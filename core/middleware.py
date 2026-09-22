from __future__ import annotations

import logging
import time

from django.conf import settings
from django.db import connection

from .logging_context import get_request_id, new_request_id, reset_request_id, set_request_id

logger = logging.getLogger("core.request")
query_logger = logging.getLogger("core.queries")

# static and media are not logged — they would drown the useful lines
SKIP_PREFIXES = ("/static/", "/media/", "/favicon.ico")


class RequestLogMiddleware:
    """
    Assigns an identifier to the request and writes one line when it ends.
    Placed FIRST after SecurityMiddleware so every inner middleware has the
    id. request.user is still available because the line is written on the
    way out, after AuthenticationMiddleware has run.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(SKIP_PREFIXES):
            return self.get_response(request)

        # honour a header from a proxy or the frontend — that way the chain
        # is traceable across several services.
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        token = set_request_id(request_id)
        started = time.perf_counter()

        try:
            response = self.get_response(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            # exception() logs the traceback; Django still builds the 500
            logger.exception(
                "%s %s failed after %.0fms", request.method, request.path, duration_ms
            )
            reset_request_id(token)
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        user = getattr(request, "user", None)
        actor = user.email if user is not None and user.is_authenticated else "anon"

        # the request body is NOT logged: registration carries a password and
        # so does /auth/token/. Once in the log it stays there in clear text,
        # and logs are protected less well than the database. The
        # Authorization header is omitted for the same reason.
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            level,
            "%s %s -> %s %.0fms user=%s",
            request.method,
            request.get_full_path(),
            response.status_code,
            duration_ms,
            actor,
        )

        # return the id to the client — the user can quote it when reporting
        response["X-Request-ID"] = request_id
        reset_request_id(token)
        return response


class QueryCountMiddleware:
    """
    Warns when a single HTTP request issued too many database queries — an
    automatic N+1 detector. Works ONLY with DEBUG=True: connection.queries
    is populated by the debug cursor alone.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.threshold = getattr(settings, "QUERY_COUNT_WARNING", 20)

    def __call__(self, request):
        response = self.get_response(request)

        if not settings.DEBUG or request.path.startswith(SKIP_PREFIXES):
            return response

        # Django resets connection.queries on the request_started signal, so
        # the list length reflects this request only.
        queries = connection.queries
        total = len(queries)
        if total <= self.threshold:
            return response

        spent_ms = sum(float(q["time"]) for q in queries) * 1000
        query_logger.warning(
            "%s %s issued %s queries in %.0fms — possible N+1",
            request.method,
            request.path,
            total,
            spent_ms,
        )
        return response
import logging
import time

from fastapi import Request
from rich.markup import escape as rich_escape

logger = logging.getLogger("api.access")

_METHOD_COLORS = {
    "GET": "cyan",
    "POST": "green",
    "PUT": "yellow",
    "PATCH": "yellow",
    "DELETE": "red",
}


def _status_color(status: int) -> str:
    if status < 300:
        return "green"
    if status < 500:
        return "yellow"
    return "red"


async def logging_middleware(request: Request, call_next):
    url = request.url.path
    if request.query_params:
        url = f"{url}?{request.query_params}"

    client_host = request.client.host if request.client else "unknown"
    start = time.perf_counter()

    response = await call_next(request)

    elapsed = time.perf_counter() - start
    status = response.status_code
    method = request.method
    method_color = _METHOD_COLORS.get(method, "white")

    logger.info(
        "[%s]%s[/] %s [[dim]%s[/]] [%s]%s[/] — %dms",
        method_color,
        method,
        rich_escape(url),
        rich_escape(client_host),
        _status_color(status),
        status,
        int(elapsed * 1000),
    )
    return response
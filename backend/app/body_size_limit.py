from fastapi import HTTPException, status
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The largest valid contact request is about 22 KB (5000 four-byte characters plus the
# other fields), so this leaves room for JSON escaping. Cloud Run itself accepts 32 MiB.
MAX_REQUEST_BODY_BYTES = 32 * 1024

BODY_TOO_LARGE_DETAIL = "Request body is too large."


class BodySizeLimitMiddleware:
    """Reject request bodies larger than ``max_bytes`` with 413.

    Content-Length is checked before the app runs. Bodies without it (chunked) are
    counted while being read, so an oversized body is never buffered in full.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None and content_length.isdigit():
            if int(content_length) > self.max_bytes:
                response = JSONResponse(
                    {"detail": BODY_TOO_LARGE_DETAIL},
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                )
                await response(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI re-raises HTTPException from body reading, so this becomes
                    # a normal 413 response instead of a 400 parse error.
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=BODY_TOO_LARGE_DETAIL,
                    )
            return message

        await self.app(scope, limited_receive, send)

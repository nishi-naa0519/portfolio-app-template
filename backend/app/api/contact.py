import json
import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, Response

from app.models.contact import ContactRequest, ContactResponse, ErrorResponse
from app.services.client_ip import get_client_ip
from app.services.contact import ContactServiceProvider, ContactServiceUnavailable
from app.services.rate_limit import RateLimitExceeded

router = APIRouter()
logger = logging.getLogger(__name__)

RATE_LIMITED_DETAIL = "Too many requests. Please try again later."
UNAVAILABLE_DETAIL = "The contact form is temporarily unavailable. Please try again later."


@router.post(
    "/contact",
    response_model=ContactResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
)
def post_contact(contact: ContactRequest, request: Request) -> ContactResponse | Response:
    if contact.website:
        # Respond as if accepted so bots cannot tell they were filtered out.
        logger.info(json.dumps({"event": "contact_honeypot_triggered"}))
        return ContactResponse(status="accepted")

    provider: ContactServiceProvider = request.app.state.contact_service_provider
    try:
        service = provider.get()
        contact_id = service.submit(contact, get_client_ip(request, service.trust_x_forwarded_for))
    except RateLimitExceeded as exc:
        logger.info(json.dumps({"event": "contact_rate_limited", "scopes": exc.scopes}))
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": RATE_LIMITED_DETAIL},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    except ContactServiceUnavailable:
        # The cause was already logged with a stack trace when the build failed.
        logger.warning(json.dumps({"event": "contact_unavailable"}))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": UNAVAILABLE_DETAIL},
        )
    except Exception:
        # Details stay in the server log; the client only gets a generic message.
        logger.exception(json.dumps({"event": "contact_failed"}))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": UNAVAILABLE_DETAIL},
        )

    # Only the ID is logged; the inquiry itself is kept out of Cloud Logging.
    logger.info(json.dumps({"event": "contact_saved", "id": contact_id}))
    return ContactResponse(status="accepted")

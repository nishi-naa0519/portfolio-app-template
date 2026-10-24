import json
import logging

from fastapi import APIRouter, status

from app.models.contact import ContactRequest, ContactResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/contact",
    response_model=ContactResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_contact(contact: ContactRequest) -> ContactResponse:
    if contact.website:
        # Respond as if accepted so bots cannot tell they were filtered out.
        logger.info(json.dumps({"event": "contact_honeypot_triggered"}))
        return ContactResponse(status="accepted")

    # Temporary: until persistence is implemented, received inquiries are only logged.
    # Only the submitted fields are logged; request headers and client IP are not.
    logger.info(
        json.dumps(
            {
                "event": "contact_received",
                "name": contact.name,
                "email": contact.email,
                "message": contact.message,
            },
            ensure_ascii=False,
        )
    )
    return ContactResponse(status="accepted")

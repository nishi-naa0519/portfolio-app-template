from starlette.requests import Request

UNKNOWN_CLIENT_IP = "unknown"


def get_client_ip(request: Request, trust_x_forwarded_for: bool) -> str:
    if trust_x_forwarded_for:
        # Clients can send their own X-Forwarded-For; the trusted front end appends the
        # address it actually received the request from, so only the last entry is used.
        forwarded = ",".join(request.headers.getlist("x-forwarded-for"))
        last = forwarded.rsplit(",", 1)[-1].strip()
        if last:
            return last
    if request.client is not None and request.client.host:
        return request.client.host
    return UNKNOWN_CLIENT_IP

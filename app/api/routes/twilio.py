from __future__ import annotations

import logging
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request, Response, status

from app.config import get_settings


logger = logging.getLogger(__name__)

router = APIRouter(tags=["twilio"])
TARGET_SIP_HOST = "5thazkme65i.sip.livekit.cloud"


def _parse_livekit_sip_target(livekit_url: str) -> tuple[str, str, str]:
    normalized_url = livekit_url.strip()
    if not normalized_url:
        raise RuntimeError("LIVEKIT_URL is not configured")

    parse_candidate = normalized_url if "://" in normalized_url else f"sip://{normalized_url}"
    parsed_url = urlparse(parse_candidate)

    host = parsed_url.netloc or parsed_url.path.lstrip("/")
    if "@" in host:
        host = host.split("@", 1)[1]

    username = parsed_url.username or ""
    password = parsed_url.password or ""
    return host, username, password


def _build_twiml_response(*, sip_uri: str, username: str = "", password: str = "") -> str:
    escaped_uri = escape(sip_uri)
    if username or password:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            "<Dial>"
            f'<Sip username="{escape(username)}" password="{escape(password)}">{escaped_uri}</Sip>'
            "</Dial>"
            "</Response>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Dial>"
        f"<Sip>{escaped_uri}</Sip>"
        "</Dial>"
        "</Response>"
    )


@router.get("/incoming-call")
async def incoming_call_healthcheck() -> Response:
    return Response(status_code=status.HTTP_200_OK, content="")


@router.post("/incoming-call")
async def incoming_call_webhook(request: Request) -> Response:
    settings = get_settings()
    form = await request.form()

    call_sid = str(form.get("CallSid", "")).strip()
    from_number = str(form.get("From", "")).strip()
    to_number = str(form.get("To", "")).strip()
    _, sip_username, sip_password = _parse_livekit_sip_target(settings.livekit_url)

    if not call_sid:
        raise RuntimeError("Twilio inbound webhook did not include a CallSid")
    if not to_number:
        raise RuntimeError("Twilio inbound webhook did not include a destination number")

    normalized_to_number = to_number.lstrip("+")
    sip_uri = f"sip:+{normalized_to_number}@{TARGET_SIP_HOST};room=call-{call_sid}"
    logger.info(
        "Returning TwiML to connect Twilio caller to LiveKit SIP",
        extra={
            "call_sid": call_sid,
            "from_number": from_number,
            "to_number": to_number,
            "sip_uri": sip_uri,
        },
    )

    return Response(
        content=_build_twiml_response(
            sip_uri=sip_uri,
            username=sip_username,
            password=sip_password,
        ),
        media_type="application/xml",
        status_code=status.HTTP_200_OK,
    )

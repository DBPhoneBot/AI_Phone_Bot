import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, status
from fastapi.responses import JSONResponse

from app.services.casedb import CaseDBClient
from app.services.ringcentral import RingCentralClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ringcentral"])


async def safe_log_event(
    casedb_client: CaseDBClient,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    try:
        await casedb_client.log_event(event_type=event_type, payload=payload)
    except Exception:
        logger.exception(
            "Failed to write CaseDB event",
            extra={"event_type": event_type},
        )


async def handle_incoming_call(
    call_session_id: str,
    caller_phone_number: str,
    payload: dict[str, Any],
) -> None:
    """Background call handler stub for downstream telephony processing."""
    casedb_client = CaseDBClient()

    try:
        # Log the validated inbound call so later modules can continue processing
        # without delaying the webhook acknowledgement.
        await safe_log_event(
            casedb_client,
            event_type="ringcentral.incoming_call.accepted",
            payload={
                "call_session_id": call_session_id,
                "caller_phone_number": caller_phone_number,
                "payload": payload,
            },
        )
    except Exception:
        logger.exception(
            "Failed while processing inbound RingCentral call in background",
            extra={
                "call_session_id": call_session_id,
                "caller_phone_number": caller_phone_number,
            },
        )


@router.post("/incoming-call")
async def incoming_call_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Receive an inbound RingCentral call webhook, validate it, return 200 quickly,
    and hand off the actual call processing to a background handler.
    """
    ringcentral_client = RingCentralClient()
    casedb_client = CaseDBClient()

    try:
        # Parse the webhook JSON body sent by RingCentral.
        payload = await request.json()

        # Read the RingCentral validation header used to authorize webhook delivery.
        validation_token = request.headers.get("Validation-Token", "")

        # Validate the incoming request before doing any downstream processing.
        is_valid = await ringcentral_client.validate_incoming_call_webhook(
            payload=payload,
            validation_token=validation_token,
        )
        if not is_valid:
            logger.warning("Rejected inbound RingCentral webhook due to failed validation")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"ok": False, "error": "invalid-webhook"},
            )

        # Extract the call session ID and caller phone number from the webhook body.
        call_session_id = ringcentral_client.extract_call_session_id(payload)
        caller_phone_number = ringcentral_client.extract_caller_phone_number(payload)

        # Log receipt of the webhook immediately for audit visibility.
        await safe_log_event(
            casedb_client,
            event_type="ringcentral.incoming_call.received",
            payload={
                "call_session_id": call_session_id,
                "caller_phone_number": caller_phone_number,
            },
        )

        # Hand off the actual call orchestration to a background task so the webhook
        # can be acknowledged with a fast 200 response.
        background_tasks.add_task(
            handle_incoming_call,
            call_session_id,
            caller_phone_number,
            payload,
        )

        # Acknowledge the webhook immediately so RingCentral does not retry it.
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "ok": True,
                "received": True,
                "call_session_id": call_session_id,
            },
        )

    except Exception as exc:
        logger.exception("Unhandled error while receiving RingCentral inbound call webhook")
        await safe_log_event(
            casedb_client,
            event_type="ringcentral.incoming_call.error",
            payload={"error": str(exc)},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"ok": False, "error": "incoming-call-handler-failed"},
        )

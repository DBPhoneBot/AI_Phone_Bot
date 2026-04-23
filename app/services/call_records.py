from __future__ import annotations

from datetime import datetime
from typing import Any


def build_call_metadata(
    *,
    caller_phone_number: str,
    call_type: str | None,
    call_start_time: datetime,
    call_end_time: datetime | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "caller_phone_number": caller_phone_number,
        "call_type": call_type,
        "call_start_time": call_start_time.isoformat(),
        "call_end_time": call_end_time.isoformat() if call_end_time is not None else None,
    }
    if extra:
        metadata.update(extra)
    return metadata


def normalize_completed_call_log(
    call_log: dict[str, Any],
    *,
    caller_phone_number: str,
    transcript_history: list[str],
) -> dict[str, Any]:
    normalized = dict(call_log)
    call_type = str(normalized.get("call_type", "")).strip().upper()
    caller_name = str(normalized.get("caller_name") or normalized.get("name") or "").strip()
    resolved_phone_number = str(
        normalized.get("caller_phone_number")
        or normalized.get("phone")
        or caller_phone_number
        or ""
    ).strip()

    if call_type == "NEW_CLIENT":
        description = str(normalized.get("description") or normalized.get("incident_description") or "").strip()
        summary = str(normalized.get("summary") or description or "New client intake completed.").strip()
        message_for_staff = str(
            normalized.get("message_for_staff")
            or f"New client intake for {caller_name or 'unknown caller'} regarding {description or 'an unspecified incident'}."
        ).strip()
        next_action = str(
            normalized.get("next_action")
            or (
                "Provide urgent same-day attorney follow-up."
                if normalized.get("escalate")
                else "Provide attorney follow-up within one business day."
            )
        ).strip()
        follow_up_required = normalized.get("follow_up_required", True)
    elif call_type == "EXISTING_CLIENT":
        reason = str(normalized.get("reason") or "").strip()
        description = str(normalized.get("description") or reason).strip()
        summary = str(normalized.get("summary") or reason or "Existing client call recorded.").strip()
        message_for_staff = str(
            normalized.get("message_for_staff")
            or f"Existing client update request from {caller_name or 'unknown caller'}: {reason or 'no reason provided'}."
        ).strip()
        next_action = str(
            normalized.get("next_action") or "Route message to the responsible attorney or case team."
        ).strip()
        follow_up_required = normalized.get("follow_up_required", True)
    elif call_type == "VOICEMAIL":
        description = str(
            normalized.get("description")
            or normalized.get("incident_description")
            or normalized.get("notes")
            or ""
        ).strip()
        summary = str(normalized.get("summary") or description or "Voicemail received.").strip()
        message_for_staff = str(
            normalized.get("message_for_staff") or f"Voicemail received from {caller_name or 'unknown caller'}."
        ).strip()
        next_action = str(
            normalized.get("next_action") or "Review voicemail details and return the call if needed."
        ).strip()
        follow_up_required = normalized.get("follow_up_required", True)
    else:
        reason = str(normalized.get("reason") or "").strip()
        description = str(normalized.get("description") or reason).strip()
        summary = str(normalized.get("summary") or reason or "Professional or other inbound call recorded.").strip()
        message_for_staff = str(
            normalized.get("message_for_staff")
            or f"Professional/other call from {caller_name or 'unknown caller'}."
        ).strip()
        next_action = str(normalized.get("next_action") or "Route the message to the intended recipient.").strip()
        follow_up_required = normalized.get("follow_up_required", True)

    normalized.update(
        {
            "call_complete": True,
            "call_type": call_type,
            "caller_name": caller_name,
            "caller_phone_number": resolved_phone_number,
            "summary": summary,
            "description": description,
            "message_for_staff": message_for_staff,
            "next_action": next_action,
            "follow_up_required": bool(follow_up_required),
            "transcript_history": transcript_history,
        }
    )
    return normalized

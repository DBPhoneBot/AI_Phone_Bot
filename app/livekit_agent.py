from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any
import json
import tempfile

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    cli,
    metrics,
)
from livekit.agents.beta import EndCallTool
from livekit.plugins import google, silero

from app.config import apply_runtime_environment, get_settings
from app.services.call_records import build_call_metadata, normalize_completed_call_log
from app.services.casedb import CaseDBClient
from app.services.conversation import ConversationLogExtractor, load_voice_agent_instructions


load_dotenv()

logger = logging.getLogger("ashley-livekit-agent")
ROOM_PREFIX = "call-"
settings = apply_runtime_environment(get_settings())
LIVEKIT_URL = "wss://casedb-call-connector-0xngbkk5.livekit.cloud"
LIVEKIT_API_KEY = "APIjGPEhPshyZdD"
LIVEKIT_API_SECRET = "FU7YhrySr9PYjWsu19jiEvTtdbrmkgCVdeikJpqaScW"


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [_extract_text_content(item) for item in content]
        return " ".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        if "text" in content and isinstance(content["text"], str):
            return content["text"].strip()
        if "content" in content:
            return _extract_text_content(content["content"])
    return ""


def _serialize_chat_history(history: Any) -> list[dict[str, str]]:
    serialized: list[dict[str, str]] = []
    items = getattr(history, "items", history)
    for item in items or []:
        item_type = getattr(item, "type", None)
        if item_type is None and isinstance(item, dict):
            item_type = item.get("type")
        if item_type != "message":
            continue

        role = getattr(item, "role", None)
        if role is None and isinstance(item, dict):
            role = item.get("role")

        text_content = getattr(item, "text_content", None)
        if text_content is None and isinstance(item, dict):
            text_content = item.get("text_content")
        if text_content is None:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content")
            text_content = _extract_text_content(content)

        normalized_text = str(text_content or "").strip()
        if normalized_text:
            serialized.append({"role": str(role or ""), "text": normalized_text})

    return serialized


def _transcript_history_from_messages(messages: list[dict[str, str]]) -> list[str]:
    return [
        f"{message['role'].upper()}: {message['text']}"
        for message in messages
        if message.get("text")
    ]


def _update_call_context_from_participant(
    participant: rtc.RemoteParticipant,
    call_context: dict[str, str],
) -> None:
    if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        return

    attributes = participant.attributes
    call_context["caller_phone_number"] = attributes.get("sip.phoneNumber", call_context.get("caller_phone_number", ""))
    call_context["twilio_call_sid"] = attributes.get("sip.twilio.callSid", call_context.get("twilio_call_sid", ""))
    call_context["sip_call_id"] = attributes.get("sip.callID", call_context.get("sip_call_id", ""))
    call_context["trunk_phone_number"] = attributes.get(
        "sip.trunkPhoneNumber",
        call_context.get("trunk_phone_number", ""),
    )


class AshleyVoiceAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=load_voice_agent_instructions(),
            tools=[EndCallTool()],
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions=(
                "Start the call now. Thank the caller for contacting Daly & Black, "
                "state that you are an AI assistant helping the intake team, and ask for the caller's full name."
            )
        )


server = AgentServer(
    ws_url=LIVEKIT_URL,
    api_key=LIVEKIT_API_KEY,
    api_secret=LIVEKIT_API_SECRET,
)


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="ashley")
async def entrypoint(ctx: JobContext) -> None:
    print("ASHLEY GEMINI AGENT STARTING")
    if not (ctx.room.name.startswith("call-") or ctx.room.name.startswith("call-_")):
        logger.info(
            "Skipping LiveKit room because it does not match the configured call dispatch prefix",
            extra={"room": ctx.room.name, "expected_prefix": "call- or call-_"},
        )
        return

    call_started_at = datetime.now(timezone.utc)
    call_context: dict[str, str] = {
        "caller_phone_number": "",
        "twilio_call_sid": "",
        "sip_call_id": "",
        "trunk_phone_number": "",
    }

    for participant in ctx.room.remote_participants.values():
        _update_call_context_from_participant(participant, call_context)

    @ctx.room.on("participant_connected")
    def _on_participant_connected(participant: rtc.RemoteParticipant) -> None:
        _update_call_context_from_participant(participant, call_context)

    ctx.log_context_fields = {
        "room": ctx.room.name,
        "caller_phone_number": call_context["caller_phone_number"],
        "twilio_call_sid": call_context["twilio_call_sid"],
    }

    casedb_client = CaseDBClient()
    call_log_extractor = ConversationLogExtractor()
<<<<<<< HEAD
    google_credentials_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
    print(
        "GOOGLE_APPLICATION_CREDENTIALS_JSON found:",
        bool(google_credentials_json),
    )
    print(
        "GOOGLE_APPLICATION_CREDENTIALS_JSON length:",
        len(google_credentials_json),
    )
    print(
        "GOOGLE_APPLICATION_CREDENTIALS_JSON first 100 chars:",
        google_credentials_json[:100],
    )

    google_credentials_file = ""
    if google_credentials_json:
        credentials_payload = google_credentials_json
        try:
            credentials_payload = json.dumps(json.loads(google_credentials_json))
        except json.JSONDecodeError:
            print("GOOGLE_APPLICATION_CREDENTIALS_JSON could not be parsed as JSON; writing raw value to temp file")

        temp_credentials_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix="google-creds-",
            delete=False,
        )
        with temp_credentials_file as handle:
            handle.write(credentials_payload)
            google_credentials_file = handle.name
        print("Google credentials temp file path:", google_credentials_file)
    else:
=======

    # Handle Google credentials - support both file path and JSON content
    google_credentials_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
    google_credentials_file = None

    if google_credentials_json:
        # Write JSON content to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(google_credentials_json)
            google_credentials_file = f.name
    else:
        # Fall back to file path
>>>>>>> 8c06c6ad727b44fa9e3fb703ac6fdc6c8fa041e1
        google_credentials_file = (
            settings.google_application_credentils.strip()
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        )

    google_stt_kwargs: dict[str, Any] = {
        "languages": settings.google_stt_language_code,
        "spoken_punctuation": False,
    }
    google_tts_kwargs: dict[str, Any] = {
        "voice_name": settings.google_tts_voice,
        "model_name": "gemini-2.5-flash-tts",
    }
    if google_credentials_file:
        google_stt_kwargs["credentials_file"] = google_credentials_file
        google_tts_kwargs["credentials_file"] = google_credentials_file

    
    session = AgentSession(
        stt=google.STT(**google_stt_kwargs),
        llm=google.LLM(
            model=settings.gemini_conversation_model,
            api_key=settings.google_api_key,
            temperature=0.4,
        ),
        tts=google.TTS(**google_tts_kwargs),
        vad=ctx.proc.userdata["vad"],
<<<<<<< HEAD
=======
        #turn_detection=MultilingualModel(),
>>>>>>> 8c06c6ad727b44fa9e3fb703ac6fdc6c8fa041e1
        preemptive_generation=True,
        tts_text_transforms=["filter_emoji", "filter_markdown"],
    )

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        metrics.log_metrics(ev.metrics)

    async def finalize_call() -> None:
        history_messages = _serialize_chat_history(session.history)
        transcript_history = _transcript_history_from_messages(history_messages)
        call_ended_at = datetime.now(timezone.utc)

        if not history_messages:
            logger.warning("Ashley call ended without transcript history", extra={"room": ctx.room.name})
            return

        try:
            extracted_call_log = await call_log_extractor.extract_call_log(
                conversation_history=history_messages,
                caller_phone_number=call_context["caller_phone_number"],
            )
            normalized_call_log = normalize_completed_call_log(
                extracted_call_log,
                caller_phone_number=call_context["caller_phone_number"],
                transcript_history=transcript_history,
            )
        except Exception as exc:
            logger.exception("Failed to build structured Ashley call log")
            normalized_call_log = normalize_completed_call_log(
                {
                    "call_type": "VOICEMAIL",
                    "summary": "Call ended before a structured intake log could be extracted.",
                    "description": "Post-call extraction failed.",
                    "message_for_staff": f"Review transcript manually. Extraction error: {exc}",
                    "notes": "Automatic post-call extraction failed.",
                    "escalate": False,
                },
                caller_phone_number=call_context["caller_phone_number"],
                transcript_history=transcript_history,
            )

        call_metadata = build_call_metadata(
            caller_phone_number=normalized_call_log.get(
                "caller_phone_number",
                call_context["caller_phone_number"],
            ),
            call_type=normalized_call_log.get("call_type"),
            call_start_time=call_started_at,
            call_end_time=call_ended_at,
            extra={
                "room_name": ctx.room.name,
                "twilio_call_sid": call_context["twilio_call_sid"],
                "livekit_sip_call_id": call_context["sip_call_id"],
                "trunk_phone_number": call_context["trunk_phone_number"],
            },
        )

        result = await casedb_client.submit_completed_call_record_async(
            call_log=normalized_call_log,
            call_metadata=call_metadata,
        )
        if not result.get("ok"):
            logger.warning(
                "CaseDB logging did not complete successfully for Ashley call",
                extra={"room": ctx.room.name, "result": result},
            )

    ctx.add_shutdown_callback(finalize_call)

    await session.start(
        agent=AshleyVoiceAgent(),
        room=ctx.room,
    )


if __name__ == "__main__":
    cli.run_app(server)

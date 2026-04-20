from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import google.generativeai as genai
from dotenv import load_dotenv

from app.config import get_settings


load_dotenv()

logger = logging.getLogger(__name__)

CALL_TYPES = {"NEW_CLIENT", "EXISTING_CLIENT", "OTHER"}
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parents[2] / "ashley_system_prompt.txt"


def load_system_prompt(prompt_path: Path = SYSTEM_PROMPT_PATH) -> str:
    try:
        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(f"System prompt file not found: {prompt_path}") from exc

    if not prompt_text:
        raise RuntimeError(f"System prompt file is empty: {prompt_path}")

    return prompt_text


@dataclass(slots=True)
class CallMetadata:
    caller_phone_number: str
    call_start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    call_type: str | None = None
    call_end_time: datetime | None = None


@dataclass(slots=True)
class ConversationTurnResult:
    response_text: str
    call_complete: bool = False
    call_log: dict[str, Any] | None = None


class ConversationManager:
    """
    Maintain the state and flow of a single phone call for the lifetime of the call.
    """

    def __init__(
        self,
        caller_phone_number: str,
        *,
        system_prompt: str | None = None,
    ) -> None:
        self.settings = get_settings()
        self._api_key = self.settings.gemini_api_key.strip()
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        genai.configure(api_key=self._api_key)
        resolved_system_prompt = system_prompt or load_system_prompt()

        self._model = genai.GenerativeModel(
            model_name=self.settings.gemini_conversation_model,
            system_instruction=resolved_system_prompt,
            generation_config=genai.GenerationConfig(temperature=0.4),
        )
        self.system_prompt = resolved_system_prompt
        self.history: list[dict[str, Any]] = []
        self.call_active = True
        self.metadata = CallMetadata(caller_phone_number=caller_phone_number)
        self.final_call_log: dict[str, Any] | None = None

    async def handle_caller_input(self, transcript: str) -> ConversationTurnResult:
        self.add_caller_input(transcript)

        response = await self._generate_model_response()
        response_text = self._extract_response_text(response)
        if not response_text:
            raise RuntimeError("Gemini returned an empty response")

        call_log = self._extract_call_log(response_text)
        if call_log is not None:
            self._append_message(role="model", text=json.dumps(call_log, ensure_ascii=True))
            self._apply_call_log(call_log)
            return ConversationTurnResult(
                response_text=json.dumps(call_log, ensure_ascii=True),
                call_complete=True,
                call_log=call_log,
            )

        self._append_message(role="model", text=response_text)
        return ConversationTurnResult(response_text=response_text)

    def add_caller_input(self, transcript: str) -> None:
        if not self.call_active:
            raise RuntimeError("Cannot append caller input because the call is no longer active")

        normalized_transcript = self._normalize_text(transcript)
        if not normalized_transcript:
            raise ValueError("Transcript must not be empty")

        logger.info("Appending caller transcript to conversation history")
        self._append_message(role="user", text=normalized_transcript)

    def set_call_type(self, call_type: str) -> None:
        normalized_call_type = call_type.strip().upper()
        if normalized_call_type not in CALL_TYPES:
            raise ValueError(f"Unsupported call type: {call_type}")

        self.metadata.call_type = normalized_call_type

    def end_call(self) -> None:
        self.call_active = False
        if self.metadata.call_end_time is None:
            self.metadata.call_end_time = datetime.now(timezone.utc)

    def cleanup(self) -> None:
        self.end_call()

    async def _generate_model_response(self) -> Any:
        try:
            logger.info(
                "Sending conversation history to Gemini",
                extra={"message_count": len(self.history)},
            )
            return await self._model.generate_content_async(self.history)
        except Exception as exc:
            logger.exception("Gemini conversation request failed")
            raise RuntimeError(f"Gemini conversation request failed: {exc}") from exc

    def _append_message(self, role: str, text: str) -> None:
        self.history.append(
            {
                "role": role,
                "parts": [{"text": text}],
            }
        )

    def _apply_call_log(self, call_log: dict[str, Any]) -> None:
        self.final_call_log = call_log

        parsed_call_type = str(call_log.get("call_type", "")).strip().upper()
        if parsed_call_type in CALL_TYPES:
            self.metadata.call_type = parsed_call_type

        caller_phone_number = str(call_log.get("caller_phone_number", "")).strip()
        if caller_phone_number:
            self.metadata.caller_phone_number = caller_phone_number

        self.end_call()
        logger.info(
            "Conversation marked complete from structured call log",
            extra={"call_type": self.metadata.call_type},
        )

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        response_text = getattr(response, "text", "")
        if isinstance(response_text, str) and response_text.strip():
            return response_text.strip()

        text_parts: list[str] = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            if content is None and isinstance(candidate, dict):
                content = candidate.get("content")

            parts = getattr(content, "parts", None)
            if parts is None and isinstance(content, dict):
                parts = content.get("parts", [])

            for part in parts or []:
                part_text = getattr(part, "text", None)
                if part_text is None and isinstance(part, dict):
                    part_text = part.get("text")
                if part_text:
                    text_parts.append(str(part_text).strip())

        return "\n".join(part for part in text_parts if part).strip()

    @staticmethod
    def _extract_call_log(response_text: str) -> dict[str, Any] | None:
        candidate_texts = [response_text.strip()]

        fenced_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, flags=re.DOTALL)
        if fenced_match:
            candidate_texts.append(fenced_match.group(1).strip())

        brace_match = re.search(r"(\{.*\})", response_text, flags=re.DOTALL)
        if brace_match:
            candidate_texts.append(brace_match.group(1).strip())

        for candidate_text in candidate_texts:
            try:
                parsed = json.loads(candidate_text)
            except json.JSONDecodeError:
                continue

            if not isinstance(parsed, dict):
                continue

            if parsed.get("call_complete") is True:
                return parsed

        return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

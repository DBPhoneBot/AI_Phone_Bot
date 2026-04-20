from __future__ import annotations

import audioop
import asyncio
import base64
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx


logger = logging.getLogger(__name__)

GEMINI_TTS_MODEL = "gemini-3.1-flash-tts-preview"
GEMINI_TTS_STREAM_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_TTS_MODEL}:streamGenerateContent?alt=sse"
)
DEFAULT_VOICE = "Sulafat"
RINGCENTRAL_CHUNK_SIZE = 160
PCM_INPUT_SAMPLE_RATE = 24000
PCM_SAMPLE_WIDTH = 2
PCM_CHANNELS = 1
RINGCENTRAL_SAMPLE_RATE = 8000

CALLER_TYPES = {"NEW_CLIENT", "EXISTING_CLIENT", "OTHER"}
URGENT_KEYWORDS = (
    "urgent",
    "immediately",
    "right away",
    "asap",
    "emergency",
    "severe",
    "serious",
    "critical",
    "bleeding",
    "hospital",
    "ambulance",
    "danger",
    "cannot wait",
    "time sensitive",
)
INJURY_KEYWORDS = (
    "injury",
    "injured",
    "hurt",
    "pain",
    "accident",
    "crash",
    "collision",
    "incident",
    "hospital",
)
DISTRESS_KEYWORDS = (
    "sorry",
    "difficult",
    "hard",
    "upsetting",
    "overwhelmed",
    "scared",
    "worried",
    "afraid",
    "traumatic",
    "hear you're going through this",
    "take your time",
)
CONTACT_DETAIL_KEYWORDS = (
    "phone number",
    "best number",
    "email address",
    "email",
    "contact information",
    "contact details",
    "date of birth",
    "address",
    "spell your",
    "confirm your",
    "best email",
)
CLOSING_KEYWORDS = (
    "attorney",
    "follow-up",
    "follow up",
    "reach out",
    "contact you",
    "call back",
    "thank you for calling",
    "daly and black",
)
MESSAGE_ROUTING_KEYWORDS = (
    "message",
    "pass that along",
    "right person",
    "gets this message",
    "team member",
)


class GeminiTTSClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        self.voice_name = os.getenv("GOOGLE_TTS_VOICE", DEFAULT_VOICE).strip() or DEFAULT_VOICE
        self.timeout_seconds = float(os.getenv("HTTP_TIMEOUT_SECONDS", "30") or "30")

    async def stream_speech(self, text: str, caller_type: str) -> AsyncIterator[bytes]:
        normalized_caller_type = caller_type.strip().upper()
        if normalized_caller_type not in CALLER_TYPES:
            raise ValueError(f"Unsupported caller_type: {caller_type}")

        clean_text = self._normalize_text(text)
        if not clean_text:
            return

        tagged_text = self._annotate_text(clean_text, normalized_caller_type)

        if not self.api_key:
            self._fallback_to_console(clean_text, "GOOGLE_API_KEY is not configured")
            return

        logger.info(
            "Starting Gemini TTS stream",
            extra={
                "caller_type": normalized_caller_type,
                "voice_name": self.voice_name,
                "tagged_text": tagged_text,
            },
        )

        converter = _RingCentralAudioConverter()

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream(
                    "POST",
                    GEMINI_TTS_STREAM_URL,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.api_key,
                    },
                    json=self._build_request_body(tagged_text),
                ) as response:
                    response.raise_for_status()

                    async for event in _iter_sse_json(response):
                        error_message = _extract_error_message(event)
                        if error_message:
                            raise RuntimeError(error_message)

                        for pcm_chunk in _extract_pcm_audio_chunks(event):
                            for ringcentral_chunk in converter.feed(pcm_chunk):
                                yield ringcentral_chunk

            for remaining_chunk in converter.flush():
                yield remaining_chunk

        except Exception as exc:
            logger.exception("Gemini TTS stream failed")
            self._fallback_to_console(clean_text, f"Gemini TTS failed: {exc}")

    async def stream_to_ringcentral(
        self,
        text: str,
        caller_type: str,
        send_chunk: Callable[[bytes], Awaitable[None]],
    ) -> None:
        async for chunk in self.stream_speech(text=text, caller_type=caller_type):
            await send_chunk(chunk)

    async def synthesize_speech(self, text: str, caller_type: str = "OTHER") -> bytes:
        audio_chunks = []
        async for chunk in self.stream_speech(text=text, caller_type=caller_type):
            audio_chunks.append(chunk)
        return b"".join(audio_chunks)

    def _build_request_body(self, tagged_text: str) -> dict[str, Any]:
        # Voice style can be further refined with Gemini style-prompt instructions if needed.
        prompt = (
            "Read the following exactly as written. Audio tags like [warmth], [care], "
            "[soft], [neutral], [positive], [hope], [short pause], [long pause], "
            "<vocal_tag: compassionate>, and <vocal_tag: professional> are performance "
            "instructions only and must never be spoken aloud.\n\n"
            f"{tagged_text}"
        )
        return {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "You are Ashley, the warm and professional voice of Daly and Black. "
                            "Use the Gemini 3.1 Flash TTS model to read the provided text naturally "
                            "while obeying embedded audio tags.\n\n"
                            "Audio tag rules:\n"
                            "- Tags are instructions only and are never spoken aloud.\n"
                            "- Follow the tag pattern of tag + spoken text + optional tag + spoken text + pause.\n"
                            "- Never place two tags directly next to each other without spoken text between them.\n"
                            "- Use the minimum number of tags needed.\n"
                            "- [warmth], [care], [soft], [neutral], [positive], [hope], [short pause], and [long pause] "
                            "control tone and pacing.\n"
                            "- Use <vocal_tag: compassionate> for injuries, pain, accidents, or emotionally difficult news.\n"
                            "- Use <vocal_tag: professional> when asking for or confirming contact details such as phone number, "
                            "email, address, or other intake information.\n"
                            "- If both kinds of guidance appear in one response, preserve all tags and interpret them naturally."
                        )
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": self.voice_name,
                        }
                    }
                },
            },
        }

    def _annotate_text(self, text: str, caller_type: str) -> str:
        if self._is_urgent(text):
            return self._apply_urgent_tags(text)

        if caller_type == "NEW_CLIENT":
            return self._tag_new_client_text(text)
        if caller_type == "EXISTING_CLIENT":
            return self._tag_existing_client_text(text)
        return self._tag_other_text(text)

    def _tag_new_client_text(self, text: str) -> str:
        sentences = _split_sentences(text)
        if not sentences:
            return text

        if self._is_distressed(text):
            sentences[0] = f"[soft] {sentences[0]}"
            if len(sentences) > 1:
                sentences[0] = f"{sentences[0]} [short pause]"
                if not sentences[1].startswith("["):
                    sentences[1] = f"[warmth] {sentences[1]}"
            else:
                sentences[0] = f"{sentences[0]} [short pause] I'm here and I'm listening."
        else:
            sentences[0] = f"[warmth] {sentences[0]}"

        care_index = self._first_sentence_index_with_keywords(sentences, INJURY_KEYWORDS)
        if care_index is not None and "[care]" not in sentences[care_index]:
            if sentences[care_index].startswith("["):
                sentences[care_index] = (
                    f"{sentences[care_index]} Please know [care] we are taking this seriously."
                )
            else:
                sentences[care_index] = f"[care] {sentences[care_index]}"

        if self._is_closing(text):
            last_index = len(sentences) - 1
            if "[hope]" not in sentences[last_index]:
                if sentences[last_index].startswith("["):
                    sentences[last_index] = (
                        f"{sentences[last_index]} We will stay with you, and [hope] someone will follow up with you soon."
                    )
                else:
                    sentences[last_index] = f"[hope] {sentences[last_index]}"

        return self._apply_vocal_tags(" ".join(sentences))

    def _tag_existing_client_text(self, text: str) -> str:
        sentences = _split_sentences(text)
        if not sentences:
            return text

        sentences[0] = f"[warmth] {sentences[0]}"

        routing_index = self._first_sentence_index_with_keywords(sentences, MESSAGE_ROUTING_KEYWORDS)
        if routing_index is not None and "[care]" not in sentences[routing_index]:
            if routing_index == 0:
                sentences[routing_index] = (
                    f"{sentences[routing_index]} Please know [care] it will reach the right person."
                )
            else:
                sentences[routing_index] = f"[care] {sentences[routing_index]}"
        elif len(sentences) > 1 and "[neutral]" not in sentences[1]:
            sentences[1] = f"[neutral] {sentences[1]}"

        return self._apply_vocal_tags(" ".join(sentences))

    def _tag_other_text(self, text: str) -> str:
        sentences = _split_sentences(text)
        if not sentences:
            return text

        sentences[0] = f"[neutral] {sentences[0]}"
        if len(sentences) > 1:
            for index in range(1, len(sentences) - 1):
                if not sentences[index].startswith("["):
                    sentences[index] = f"[neutral] {sentences[index]}"
            sentences[-1] = f"[positive] {sentences[-1]}"

        return self._apply_vocal_tags(" ".join(sentences))

    def _apply_urgent_tags(self, text: str) -> str:
        sentences = _split_sentences(text)
        if not sentences:
            return f"[soft] {text} [long pause]"

        sentences[0] = f"[soft] {sentences[0]}"

        if len(sentences) > 1:
            care_index = 1
            sentences[care_index] = f"[care] {sentences[care_index]}"
        elif "[care]" not in sentences[0]:
            sentences[0] = f"{sentences[0]} Please know [care] we are taking this seriously."

        sentences[-1] = f"{sentences[-1]} [long pause]"
        return self._apply_vocal_tags(" ".join(sentences))

    def _apply_vocal_tags(self, text: str) -> str:
        updated = text

        if self._mentions_injury_context(updated) and "<vocal_tag: compassionate>" not in updated:
            updated = self._prefix_or_inject_tag(updated, "<vocal_tag: compassionate>")

        if self._asks_for_contact_details(updated) and "<vocal_tag: professional>" not in updated:
            updated = self._prefix_or_inject_tag(updated, "<vocal_tag: professional>")

        return updated

    @staticmethod
    def _prefix_or_inject_tag(text: str, tag: str) -> str:
        stripped = text.strip()
        if not stripped:
            return text

        if stripped.startswith("[") or stripped.startswith("<"):
            return f"{stripped} Please continue {tag} as we confirm the details."

        return f"{tag} {stripped}"

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    @staticmethod
    def _first_sentence_index_with_keywords(
        sentences: list[str],
        keywords: tuple[str, ...],
    ) -> int | None:
        for index, sentence in enumerate(sentences):
            lowered = sentence.lower()
            if any(keyword in lowered for keyword in keywords):
                return index
        return None

    @staticmethod
    def _is_urgent(text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in URGENT_KEYWORDS)

    @staticmethod
    def _is_distressed(text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in DISTRESS_KEYWORDS)

    @staticmethod
    def _is_closing(text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in CLOSING_KEYWORDS)

    @staticmethod
    def _mentions_injury_context(text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in INJURY_KEYWORDS + DISTRESS_KEYWORDS)

    @staticmethod
    def _asks_for_contact_details(text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in CONTACT_DETAIL_KEYWORDS)

    @staticmethod
    def _fallback_to_console(text: str, reason: str) -> None:
        logger.warning("Falling back to console output for TTS", extra={"reason": reason})
        print(f"[Gemini TTS fallback] {text}")


class _RingCentralAudioConverter:
    def __init__(self) -> None:
        self._resample_state: Any = None
        self._pcm_remainder = b""
        self._mulaw_buffer = bytearray()

    def feed(self, pcm_chunk: bytes) -> list[bytes]:
        if not pcm_chunk:
            return []

        pcm_input = self._pcm_remainder + pcm_chunk
        even_length = len(pcm_input) - (len(pcm_input) % PCM_SAMPLE_WIDTH)
        processable = pcm_input[:even_length]
        self._pcm_remainder = pcm_input[even_length:]

        if not processable:
            return []

        resampled, self._resample_state = audioop.ratecv(
            processable,
            PCM_SAMPLE_WIDTH,
            PCM_CHANNELS,
            PCM_INPUT_SAMPLE_RATE,
            RINGCENTRAL_SAMPLE_RATE,
            self._resample_state,
        )
        self._mulaw_buffer.extend(audioop.lin2ulaw(resampled, PCM_SAMPLE_WIDTH))
        return self._drain_ready_chunks()

    def flush(self) -> list[bytes]:
        if self._pcm_remainder:
            padded = self._pcm_remainder + b"\x00" * (PCM_SAMPLE_WIDTH - len(self._pcm_remainder))
            self._pcm_remainder = b""
            self.feed(padded)

        if not self._mulaw_buffer:
            return []

        chunk = bytes(self._mulaw_buffer)
        self._mulaw_buffer.clear()
        return [chunk]

    def _drain_ready_chunks(self) -> list[bytes]:
        chunks = []
        while len(self._mulaw_buffer) >= RINGCENTRAL_CHUNK_SIZE:
            chunk = bytes(self._mulaw_buffer[:RINGCENTRAL_CHUNK_SIZE])
            del self._mulaw_buffer[:RINGCENTRAL_CHUNK_SIZE]
            chunks.append(chunk)
        return chunks


async def _iter_sse_json(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    event_lines: list[str] = []

    async for raw_line in response.aiter_lines():
        line = raw_line.strip()

        if not line:
            if event_lines:
                payload = "\n".join(event_lines)
                event_lines.clear()
                if payload == "[DONE]":
                    return
                yield json.loads(payload)
            continue

        if line.startswith(":"):
            continue

        if line.startswith("data:"):
            event_lines.append(line[5:].strip())

    if event_lines:
        payload = "\n".join(event_lines)
        if payload != "[DONE]":
            yield json.loads(payload)


def _extract_error_message(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        return str(error.get("message", "")).strip()
    return ""


def _extract_pcm_audio_chunks(event: dict[str, Any]) -> list[bytes]:
    chunks: list[bytes] = []

    for candidate in event.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            inline_data = part.get("inlineData") or part.get("inline_data") or {}
            data = inline_data.get("data")
            if not data:
                continue

            try:
                chunks.append(base64.b64decode(data))
            except Exception:
                logger.exception("Failed to decode Gemini TTS audio chunk")

    return chunks


def _split_sentences(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]

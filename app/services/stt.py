from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from google.api_core import exceptions as google_exceptions
from google.cloud import speech_v1 as speech
from google.oauth2 import service_account
from google.protobuf.duration_pb2 import Duration


logger = logging.getLogger(__name__)

_STREAM_SENTINEL = object()


@dataclass(slots=True)
class FinalTranscript:
    text: str
    confidence: float
    language_code: str
    result_end_offset_seconds: float


@dataclass(slots=True)
class SpeechStreamEvent:
    event_type: str
    transcript: str = ""
    confidence: float = 0.0
    stability: float = 0.0
    language_code: str = ""
    offset_seconds: float = 0.0
    error_message: str = ""


class StreamingTranscriptionSession:
    """Bidirectional Google STT stream wrapper for phone-call audio."""

    def __init__(
        self,
        speech_client: speech.SpeechClient,
        language_code: str,
        loop: asyncio.AbstractEventLoop,
        *,
        interim_results: bool = True,
        speech_start_timeout_seconds: float | None = None,
        speech_end_timeout_seconds: float | None = None,
    ) -> None:
        self._speech_client = speech_client
        self._language_code = language_code
        self._loop = loop
        self._interim_results = interim_results
        self._speech_start_timeout_seconds = speech_start_timeout_seconds
        self._speech_end_timeout_seconds = speech_end_timeout_seconds

        self._audio_queue: queue.Queue[bytes | object] = queue.Queue()
        self._event_queue: asyncio.Queue[SpeechStreamEvent | None] = asyncio.Queue()
        self._final_queue: asyncio.Queue[FinalTranscript | None] = asyncio.Queue()
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()

        self.caller_is_speaking = False
        self.interrupt_event = asyncio.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._run_streaming_loop,
            name="google-stt-stream",
            daemon=True,
        )
        self._thread.start()

    def push_audio(self, audio_chunk: bytes) -> None:
        if self._stop_requested.is_set():
            logger.debug("Ignoring audio chunk because STT stream is closing")
            return

        if not audio_chunk:
            return

        self._audio_queue.put(audio_chunk)

    def finish_input(self) -> None:
        self._audio_queue.put(_STREAM_SENTINEL)

    async def aclose(self) -> None:
        self._stop_requested.set()
        self.finish_input()

        if self._thread and self._thread.is_alive():
            await asyncio.to_thread(self._thread.join, 5)

    def acknowledge_interrupt(self) -> None:
        self._loop.call_soon_threadsafe(self.interrupt_event.clear)

    async def iter_events(self) -> AsyncIterator[SpeechStreamEvent]:
        while True:
            event = await self._event_queue.get()
            if event is None:
                break
            yield event

    async def iter_final_transcripts(self) -> AsyncIterator[FinalTranscript]:
        while True:
            transcript = await self._final_queue.get()
            if transcript is None:
                break
            yield transcript

    def _run_streaming_loop(self) -> None:
        logger.info("Starting Google streaming transcription session")

        try:
            responses = self._speech_client.streaming_recognize(
                requests=self._request_stream(),
            )
            for response in responses:
                if self._stop_requested.is_set():
                    break
                self._handle_response(response)
        except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as exc:
            logger.exception("Google STT streaming call failed")
            self._publish_event(
                SpeechStreamEvent(
                    event_type="error",
                    error_message=str(exc),
                )
            )
        except Exception as exc:
            logger.exception("Unexpected error in Google STT streaming session")
            self._publish_event(
                SpeechStreamEvent(
                    event_type="error",
                    error_message=str(exc),
                )
            )
        finally:
            with self._state_lock:
                self.caller_is_speaking = False
            self._loop.call_soon_threadsafe(self.interrupt_event.clear)
            self._publish_event(SpeechStreamEvent(event_type="closed"))
            self._loop.call_soon_threadsafe(self._event_queue.put_nowait, None)
            self._loop.call_soon_threadsafe(self._final_queue.put_nowait, None)
            logger.info("Google streaming transcription session closed")

    def _request_stream(self):
        yield speech.StreamingRecognizeRequest(
            streaming_config=self._build_streaming_config(),
        )

        while not self._stop_requested.is_set():
            try:
                item = self._audio_queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if item is _STREAM_SENTINEL:
                break

            yield speech.StreamingRecognizeRequest(audio_content=item)

    def _build_streaming_config(self) -> speech.StreamingRecognitionConfig:
        config_kwargs: dict[str, Any] = {
            "config": _build_recognition_config(self._language_code),
            "interim_results": self._interim_results,
            "enable_voice_activity_events": True,
        }

        voice_activity_timeout = _build_voice_activity_timeout(
            speech_start_timeout_seconds=self._speech_start_timeout_seconds,
            speech_end_timeout_seconds=self._speech_end_timeout_seconds,
        )
        if voice_activity_timeout is not None:
            config_kwargs["voice_activity_timeout"] = voice_activity_timeout

        return speech.StreamingRecognitionConfig(**config_kwargs)

    def _handle_response(self, response: speech.StreamingRecognizeResponse) -> None:
        if response.error.message:
            logger.error("Google STT stream returned an error: %s", response.error.message)
            self._publish_event(
                SpeechStreamEvent(
                    event_type="error",
                    error_message=response.error.message,
                )
            )
            return

        self._handle_speech_event(response)

        for result in response.results:
            if not result.alternatives:
                continue

            alternative = result.alternatives[0]
            transcript_text = alternative.transcript.strip()
            if not transcript_text:
                continue

            offset_seconds = _duration_to_seconds(result.result_end_time)
            language_code = result.language_code or self._language_code

            if result.is_final:
                logger.info("Received final transcript: %s", transcript_text)
                final_transcript = FinalTranscript(
                    text=transcript_text,
                    confidence=alternative.confidence,
                    language_code=language_code,
                    result_end_offset_seconds=offset_seconds,
                )
                self._publish_event(
                    SpeechStreamEvent(
                        event_type="final_transcript",
                        transcript=transcript_text,
                        confidence=alternative.confidence,
                        language_code=language_code,
                        offset_seconds=offset_seconds,
                    )
                )
                self._loop.call_soon_threadsafe(self._final_queue.put_nowait, final_transcript)
                continue

            if self._interim_results:
                self._publish_event(
                    SpeechStreamEvent(
                        event_type="interim_transcript",
                        transcript=transcript_text,
                        stability=result.stability,
                        language_code=language_code,
                        offset_seconds=offset_seconds,
                    )
                )

    def _handle_speech_event(self, response: speech.StreamingRecognizeResponse) -> None:
        speech_event_type = response.speech_event_type
        offset_seconds = _duration_to_seconds(response.speech_event_time)

        if speech_event_type == speech.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_BEGIN:
            with self._state_lock:
                self.caller_is_speaking = True
            self._loop.call_soon_threadsafe(self.interrupt_event.set)
            logger.info("Detected caller speech activity begin")
            self._publish_event(
                SpeechStreamEvent(
                    event_type="speech_start",
                    offset_seconds=offset_seconds,
                )
            )
            return

        if speech_event_type == speech.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_END:
            with self._state_lock:
                self.caller_is_speaking = False
            logger.info("Detected caller speech activity end")
            self._publish_event(
                SpeechStreamEvent(
                    event_type="speech_end",
                    offset_seconds=offset_seconds,
                )
            )
            return

        if speech_event_type == speech.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_TIMEOUT:
            with self._state_lock:
                self.caller_is_speaking = False
            logger.info("Detected Google STT speech activity timeout")
            self._publish_event(
                SpeechStreamEvent(
                    event_type="speech_timeout",
                    offset_seconds=offset_seconds,
                )
            )
            return

        if speech_event_type == speech.StreamingRecognizeResponse.SpeechEventType.END_OF_SINGLE_UTTERANCE:
            with self._state_lock:
                self.caller_is_speaking = False
            logger.info("Detected end of single utterance")
            self._publish_event(
                SpeechStreamEvent(
                    event_type="end_of_single_utterance",
                    offset_seconds=offset_seconds,
                )
            )

    def _publish_event(self, event: SpeechStreamEvent) -> None:
        self._loop.call_soon_threadsafe(self._event_queue.put_nowait, event)


class GoogleSpeechToTextClient:
    def __init__(self, language_code: str | None = None) -> None:
        self.language_code = language_code or os.getenv("GOOGLE_STT_LANGUAGE_CODE", "en-US")
        self.credentials = _load_google_credentials()
        self.client = speech.SpeechClient(credentials=self.credentials)

    async def start_stream(
        self,
        *,
        interim_results: bool = True,
        speech_start_timeout_seconds: float | None = None,
        speech_end_timeout_seconds: float | None = None,
    ) -> StreamingTranscriptionSession:
        loop = asyncio.get_running_loop()
        session = StreamingTranscriptionSession(
            speech_client=self.client,
            language_code=self.language_code,
            loop=loop,
            interim_results=interim_results,
            speech_start_timeout_seconds=speech_start_timeout_seconds,
            speech_end_timeout_seconds=speech_end_timeout_seconds,
        )
        session.start()
        return session

    async def transcribe_audio(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return ""

        def _recognize() -> str:
            response = self.client.recognize(
                config=_build_recognition_config(self.language_code),
                audio=speech.RecognitionAudio(content=audio_bytes),
            )
            transcripts = []
            for result in response.results:
                if result.alternatives:
                    transcripts.append(result.alternatives[0].transcript.strip())
            return " ".join(part for part in transcripts if part)

        try:
            return await asyncio.to_thread(_recognize)
        except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as exc:
            logger.exception("Google STT recognize call failed")
            raise RuntimeError(f"Google STT recognize failed: {exc}") from exc


def _load_google_credentials():
    raw_credentials = os.getenv("GOOGLE_CREDENTIALS", "").strip()
    if not raw_credentials:
        raise RuntimeError("GOOGLE_CREDENTIALS is not set")

    credentials_path = Path(raw_credentials).expanduser()
    if credentials_path.exists():
        logger.info("Loading Google STT credentials from file path")
        return service_account.Credentials.from_service_account_file(str(credentials_path))

    try:
        credentials_info = json.loads(raw_credentials)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "GOOGLE_CREDENTIALS must be a valid file path or service-account JSON"
        ) from exc

    logger.info("Loading Google STT credentials from inline JSON")
    return service_account.Credentials.from_service_account_info(credentials_info)


def _build_recognition_config(language_code: str) -> speech.RecognitionConfig:
    return speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.MULAW,
        sample_rate_hertz=8000,
        language_code=language_code,
        model="phone_call",
        use_enhanced=True,
        enable_automatic_punctuation=True,
        metadata=speech.RecognitionMetadata(
            interaction_type=speech.RecognitionMetadata.InteractionType.PHONE_CALL,
            original_media_type=speech.RecognitionMetadata.OriginalMediaType.AUDIO,
            recording_device_type=speech.RecognitionMetadata.RecordingDeviceType.PHONE_LINE,
        ),
    )


def _build_voice_activity_timeout(
    *,
    speech_start_timeout_seconds: float | None,
    speech_end_timeout_seconds: float | None,
) -> speech.StreamingRecognitionConfig.VoiceActivityTimeout | None:
    timeout_kwargs: dict[str, Duration] = {}

    if speech_start_timeout_seconds is not None:
        timeout_kwargs["speech_start_timeout"] = _seconds_to_duration(speech_start_timeout_seconds)

    if speech_end_timeout_seconds is not None:
        timeout_kwargs["speech_end_timeout"] = _seconds_to_duration(speech_end_timeout_seconds)

    if not timeout_kwargs:
        return None

    return speech.StreamingRecognitionConfig.VoiceActivityTimeout(**timeout_kwargs)


def _seconds_to_duration(seconds: float) -> Duration:
    whole_seconds = int(seconds)
    nanos = int((seconds - whole_seconds) * 1_000_000_000)
    return Duration(seconds=whole_seconds, nanos=nanos)


def _duration_to_seconds(duration: Duration | None) -> float:
    if duration is None:
        return 0.0
    return float(duration.seconds) + (float(duration.nanos) / 1_000_000_000.0)

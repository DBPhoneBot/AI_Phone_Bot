from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)

FALLBACK_FILE_PATH = Path(__file__).resolve().parents[2] / "casedb_fallback.jsonl"


class CaseDBClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("CASEDB_API_KEY", "").strip()
        self.api_secret = os.getenv("CASEDB_API_SECRET", "").strip()
        self.log_url = os.getenv("CASEDB_LOG_URL", "").strip()
        self.explicit_escalation_url = os.getenv("CASEDB_ESCALATION_URL", "").strip()
        self.timeout_seconds = float(os.getenv("HTTP_TIMEOUT_SECONDS", "30") or "30")

    def submit_completed_call_record(
        self,
        call_log: dict[str, Any],
        call_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Save the completed intake record to CaseDB and trigger escalation if requested.
        """
        record = self._build_record(call_log=call_log, call_metadata=call_metadata)

        if not self._is_configured():
            logger.warning("CaseDB is not configured; writing record to fallback file")
            self._write_fallback_record(record, reason="not_configured")
            return {"ok": False, "fallback": True, "reason": "not_configured"}

        try:
            primary_response = self._post_json(
                url=self.log_url,
                payload=self._build_case_log_payload(record),
            )
            result: dict[str, Any] = {
                "ok": True,
                "fallback": False,
                "record_response": primary_response,
            }
            logger.info("Saved completed call record to CaseDB")

            if self._should_escalate(call_log):
                escalation_response = self._post_json(
                    url=self._get_escalation_url(),
                    payload=self._build_escalation_payload(record),
                )
                result["escalation_response"] = escalation_response
                logger.info("Created CaseDB escalation notification")

            return result
        except Exception as exc:
            logger.exception("Failed to save completed call record to CaseDB")
            self._write_fallback_record(record, reason=str(exc))
            return {
                "ok": False,
                "fallback": True,
                "reason": str(exc),
            }

    async def submit_completed_call_record_async(
        self,
        call_log: dict[str, Any],
        call_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.submit_completed_call_record, call_log, call_metadata)

    async def log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        logger.info(
            "Skipping CaseDB event logging because this client is configured for completed call records",
            extra={"event_type": event_type, "payload": payload},
        )

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            url,
            json=payload,
            headers=self._build_headers(),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        try:
            response_data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"CaseDB returned non-JSON response: {response.text.strip()}") from exc

        logger.info(
            "CaseDB transaction completed",
            extra={"url": url, "response": response_data},
        )
        return response_data

    def _build_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "key": self.api_key,
            "secret": self.api_secret,
        }

    def _build_record(
        self,
        call_log: dict[str, Any],
        call_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(call_log, dict):
            raise ValueError("call_log must be a JSON-like dict")
        if not isinstance(call_metadata, dict):
            raise ValueError("call_metadata must be a dict")

        return {
            "call_log": call_log,
            "call_metadata": call_metadata,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_case_log_payload(self, record: dict[str, Any]) -> dict[str, Any]:
        call_log = record["call_log"]
        call_metadata = record["call_metadata"]

        # Confirm with the CaseDB developer whether the completed call log should be
        # sent to this exact endpoint and whether these field names match the final API.
        payload = {
            "caller_phone_number": call_metadata.get("caller_phone_number", ""),
            "call_type": call_metadata.get("call_type", "") or call_log.get("call_type", ""),
            "call_start_time": call_metadata.get("call_start_time", ""),
            "call_end_time": call_metadata.get("call_end_time", ""),
            "call_log": call_log,
            "summary": call_log.get("summary", ""),
            "description": call_log.get("description", ""),
            "message_for_staff": call_log.get("message_for_staff", ""),
            "follow_up_required": bool(call_log.get("follow_up_required", False)),
            "escalate": bool(call_log.get("escalate", False)),
        }

        caller_name = str(call_log.get("caller_name", "")).strip()
        if caller_name:
            payload["caller_name"] = caller_name

        return payload

    def _build_escalation_payload(self, record: dict[str, Any]) -> dict[str, Any]:
        call_log = record["call_log"]
        call_metadata = record["call_metadata"]

        # Confirm with the CaseDB developer whether this should use a dedicated
        # escalation endpoint and whether these payload fields match their contract.
        return {
            "caller_phone_number": call_metadata.get("caller_phone_number", ""),
            "call_type": call_metadata.get("call_type", "") or call_log.get("call_type", ""),
            "summary": call_log.get("summary", ""),
            "description": call_log.get("description", ""),
            "message_for_staff": call_log.get("message_for_staff", ""),
            "next_action": call_log.get("next_action", ""),
            "escalate": True,
            "created_at": record["saved_at"],
        }

    def _get_escalation_url(self) -> str:
        if self.explicit_escalation_url:
            return self.explicit_escalation_url

        # Confirm this derived path with the CaseDB developer before depending on it
        # in production, since the exact escalation route is not yet documented here.
        base_url = self.log_url.rsplit("/", 1)[0] + "/"
        return urljoin(base_url, "create_escalation.php")

    def _write_fallback_record(self, record: dict[str, Any], reason: str) -> None:
        fallback_entry = {
            "reason": reason,
            "record": record,
        }
        FALLBACK_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with FALLBACK_FILE_PATH.open("a", encoding="utf-8") as fallback_file:
            fallback_file.write(json.dumps(fallback_entry, ensure_ascii=True) + "\n")

        logger.warning(
            "Wrote CaseDB record to fallback file",
            extra={"fallback_file": str(FALLBACK_FILE_PATH), "reason": reason},
        )

    def _is_configured(self) -> bool:
        return bool(self.log_url and self.api_key and self.api_secret)

    @staticmethod
    def _should_escalate(call_log: dict[str, Any]) -> bool:
        return bool(call_log.get("escalate") is True)


def submit_completed_call_record(
    call_log: dict[str, Any],
    call_metadata: dict[str, Any],
) -> dict[str, Any]:
    client = CaseDBClient()
    return client.submit_completed_call_record(call_log=call_log, call_metadata=call_metadata)

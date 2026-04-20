from __future__ import annotations

from typing import Any

from ringcentral import SDK

from app.config import get_settings


class RingCentralClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.platform = self._initialize_platform()

    def _initialize_platform(self):
        # Initialize the RingCentral Python SDK using the requested environment variables.
        sdk = SDK(
            self.settings.ringcentral_client_id,
            self.settings.ringcentral_client_secret,
            self.settings.ringcentral_server_url,
        )

        # Authenticate the SDK platform with the account's JWT token.
        platform = sdk.platform()
        platform.login(jwt=self.settings.ringcentral_jwt)
        return platform

    async def validate_webhook(self, payload: dict) -> None:
        # Placeholder for webhook signature or schema validation.
        # Expand this when the telephony module is implemented.
        _ = payload

    async def validate_websocket_message(self, payload: dict) -> None:
        # Placeholder for RingCentral media-stream message validation.
        # Expand this when the streaming contract is defined.
        _ = payload

    async def validate_incoming_call_webhook(
        self,
        payload: dict[str, Any],
        validation_token: str,
    ) -> bool:
        # RingCentral documents webhook authorization via the Validation-Token header.
        # This scaffold compares that header to the configured secret we currently have
        # available in environment variables. If you later add a dedicated webhook token,
        # this method should use that instead.
        expected_token = self.settings.ringcentral_client_secret
        if not validation_token or validation_token != expected_token:
            return False

        # Also confirm the webhook belongs to the expected RingCentral account.
        payload_account_id = str(
            payload.get("ownerId")
            or payload.get("accountId")
            or payload.get("body", {}).get("ownerId", "")
            or payload.get("body", {}).get("accountId", "")
            or ""
        )
        if self.settings.ringcentral_account_id and payload_account_id != self.settings.ringcentral_account_id:
            return False

        return True

    @staticmethod
    def extract_call_session_id(payload: dict[str, Any]) -> str:
        body = payload.get("body", {})
        return str(
            payload.get("sessionId")
            or payload.get("telephonySessionId")
            or body.get("sessionId")
            or body.get("telephonySessionId")
            or body.get("id")
            or ""
        )

    @staticmethod
    def extract_caller_phone_number(payload: dict[str, Any]) -> str:
        body = payload.get("body", {})
        from_section = body.get("from", {})
        caller_info = body.get("party", {})
        return str(
            from_section.get("phoneNumber")
            or from_section.get("extensionNumber")
            or caller_info.get("from", {}).get("phoneNumber")
            or payload.get("from", {}).get("phoneNumber", "")
            or ""
        )

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_env: str = Field(default="development", alias="APP_ENV")
    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")
    webhook_base_url: str = Field(default="", alias="WEBHOOK_BASE_URL")

    livekit_api_key: str = Field(default="", alias="LIVEKIT_API_KEY")
    livekit_api_secret: str = Field(default="", alias="LIVEKIT_API_SECRET")
    livekit_url: str = Field(default="", alias="LIVEKIT_URL")
    twilio_account_sid: str = Field(default="", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(default="", alias="TWILIO_AUTH_TOKEN")

    google_cloud_project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    google_application_credentils: str = Field(default="", alias="GOOGLE_APPLICATION_CREDENTILS")
    google_stt_language_code: str = Field(default="en-US", alias="GOOGLE_STT_LANGUAGE_CODE")

    gemini_conversation_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_CONVERSATION_MODEL")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    # Named Gemini TTS voice.
    google_tts_voice: str = Field(default="Kore", alias="GOOGLE_TTS_VOICE")

    casedb_log_url: str = Field(default="", alias="CASEDB_LOG_URL")
    casedb_api_key: str = Field(default="", alias="CASEDB_API_KEY")
    casedb_api_secret: str = Field(default="", alias="CASEDB_API_SECRET")
    casedb_escalation_url: str = Field(default="", alias="CASEDB_ESCALATION_URL")

    http_timeout_seconds: int = Field(default=30, alias="HTTP_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def apply_runtime_environment(settings: Settings | None = None) -> Settings:
    resolved_settings = settings or get_settings()
    credentials_path = resolved_settings.google_application_credentils.strip()
    if credentials_path and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
    return resolved_settings

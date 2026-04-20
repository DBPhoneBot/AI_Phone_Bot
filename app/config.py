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

    ringcentral_client_id: str = Field(default="", alias="RC_CLIENT_ID")
    ringcentral_client_secret: str = Field(default="", alias="RC_CLIENT_SECRET")
    ringcentral_jwt: str = Field(default="", alias="RC_JWT_TOKEN")
    ringcentral_account_id: str = Field(default="", alias="RC_ACCOUNT_ID")
    ringcentral_server_url: str = Field(
        default="https://platform.ringcentral.com",
        alias="RC_SERVER_URL",
    )

    google_cloud_project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    google_credentials: str = Field(default="", alias="GOOGLE_CREDENTIALS")
    google_stt_language_code: str = Field(default="en-US", alias="GOOGLE_STT_LANGUAGE_CODE")

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_conversation_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_CONVERSATION_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")

    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    google_tts_voice: str = Field(default="Sulafat", alias="GOOGLE_TTS_VOICE")

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

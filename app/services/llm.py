from app.config import get_settings


class ConversationLLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate_response(self, transcript: str) -> str:
        # Placeholder for GPT-4o conversation handling.
        _ = transcript
        return ""


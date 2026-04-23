# phone-system

`phone-system` is a dedicated Python/FastAPI service for handling inbound Daly & Black phone calls separately from the rest of the platform.

## What This Project Does

This service is intended to:

- receive inbound phone-call events from Twilio and hand them off to LiveKit via TwiML
- run the live voice assistant in a LiveKit room
- transcribe caller audio using Google Speech-to-Text
- run the conversation through Gemini using the Ashley system prompt
- generate spoken responses with Google Gemini TTS
- log structured call activity to CaseDB

The initial scaffold in this project sets up:

- a FastAPI application entrypoint
- environment-based configuration using `python-dotenv`
- placeholder API routes for health checks and telephony webhooks
- service modules for telephony, transcription, LLM, TTS, and CaseDB integration

## Project Structure

```text
phone-system/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── app/
    ├── __init__.py
    ├── config.py
    ├── livekit_agent.py
    ├── main.py
    ├── api/
    │   ├── __init__.py
    │   └── routes/
    │       ├── __init__.py
    │       ├── health.py
    │       └── twilio.py
    └── services/
        ├── __init__.py
        ├── call_records.py
        ├── casedb.py
        ├── llm.py
        └── stt.py
```

## Setup

1. Create and activate a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Copy the example environment file and fill in your real credentials.

```bash
cp .env.example .env
```

Required for a live inbound-call test:

- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `LIVEKIT_URL`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `GOOGLE_API_KEY`
- `GOOGLE_APPLICATION_CREDENTILS`
- `GEMINI_CONVERSATION_MODEL`
- `CASEDB_LOG_URL`
- `CASEDB_API_KEY`
- `CASEDB_API_SECRET`

Optional:

- `GOOGLE_TTS_VOICE`
- `CASEDB_ESCALATION_URL`
- `HTTP_TIMEOUT_SECONDS`

4. Start the FastAPI server.

```bash
uvicorn app.main:app --reload
```

5. Start the LiveKit Ashley agent worker.

```bash
python3 -m app.livekit_agent dev
```

For a local Ashley conversation test without the telephony provider, run:

```bash
python3 scripts/local_conversation_test.py
```

This local test only loads the Ashley conversation service and Gemini conversation client. It does not start FastAPI or initialize the telephony provider.

## Available Endpoints

- `GET /health`
  - basic health check for the service
- `POST /incoming-call`
  - Twilio webhook that returns TwiML to connect callers to LiveKit SIP

## Notes

- This scaffold is intentionally minimal and safe to extend one module at a time.
- It does not yet implement full call streaming, transcription, or audio response handling.
- The current conversation runtime loads the Ashley system prompt from `ashley_system_prompt.txt`.
- The FastAPI app returns TwiML only; the live call experience runs in the LiveKit agent worker.
- Twilio inbound calling still requires a LiveKit inbound trunk and dispatch rule outside this repo.

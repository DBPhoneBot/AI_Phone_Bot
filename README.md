# phone-system

`phone-system` is a dedicated Python/FastAPI service for handling inbound Daly & Black phone calls separately from the rest of the platform.

## What This Project Does

This service is intended to:

- receive inbound phone-call events from RingCentral
- transcribe caller audio using Google Speech-to-Text
- run the conversation through Gemini using the Ashley system prompt
- generate spoken responses with Gemini 3.1 Flash TTS
- log structured call activity to CaseDB

The initial scaffold in this project sets up:

- a FastAPI application entrypoint
- environment-based configuration using `python-dotenv`
- placeholder API routes for health checks and RingCentral webhooks
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
    ├── main.py
    ├── api/
    │   ├── __init__.py
    │   └── routes/
    │       ├── __init__.py
    │       ├── health.py
    │       └── ringcentral.py
    └── services/
        ├── __init__.py
        ├── casedb.py
        ├── llm.py
        ├── ringcentral.py
        ├── stt.py
        └── tts.py
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

- `RC_CLIENT_ID`
- `RC_CLIENT_SECRET`
- `RC_JWT_TOKEN`
- `RC_ACCOUNT_ID`
- `GEMINI_API_KEY`
- `GEMINI_CONVERSATION_MODEL`
- `GOOGLE_API_KEY`
- `GOOGLE_CREDENTIALS`
- `CASEDB_LOG_URL`
- `CASEDB_API_KEY`
- `CASEDB_API_SECRET`

Optional:

- `GOOGLE_TTS_VOICE`
- `CASEDB_ESCALATION_URL`
- `HTTP_TIMEOUT_SECONDS`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

4. Start the FastAPI server.

```bash
uvicorn app.main:app --reload
```

For a local Ashley conversation test without RingCentral, run:

```bash
python3 scripts/local_conversation_test.py
```

This local test only loads the Ashley conversation service and Gemini conversation client. It does not start FastAPI or initialize RingCentral.

## Available Endpoints

- `GET /health`
  - basic health check for the service
- `POST /incoming-call`
  - inbound RingCentral webhook route

## Notes

- This scaffold is intentionally minimal and safe to extend one module at a time.
- It does not yet implement full call streaming, transcription, or audio response handling.
- The current conversation runtime loads the Ashley system prompt from `ashley_system_prompt.txt`.
- The current TTS service is wired for Gemini 3.1 Flash TTS with RingCentral-compatible audio output.

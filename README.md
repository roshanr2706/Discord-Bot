# Discord Bot

A small Discord bot with three independent features:

- **Calendar sync** — mirrors an upcoming Google Calendar window into a channel as embeds, polling every 15 minutes.
- **AI summary** — `!Summary <count>` summarizes recent chat, backed by a rolling memory snapshot that refreshes every 3 hours.
- **Boulder bot** — randomly chimes into climbing chatter with a spoilered one-liner.

## Setup

1. Create and activate a virtualenv, then install deps:

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill it in:

   ```bash
   cp .env.example .env
   ```

3. Drop your Google service-account key at `config/credentials.json` (the
   `config/` directory is gitignored and is created automatically at runtime).
   Share the target calendar with the service account's email address.

4. Run it:

   ```bash
   python bot.py
   ```

## Run with Docker

The repo ships a `Dockerfile` and `docker-compose.yml`. Secrets and runtime
state stay out of the image: `.env` is loaded at run time and `config/` is
mounted as a volume (so `credentials.json` is readable and
`posted_events.json` / `chat_memory.json` persist across rebuilds).

```bash
cp .env.example .env          # then fill it in
mkdir -p config               # drop credentials.json here if using calendar
docker compose up -d --build  # build + run detached
docker compose logs -f        # follow logs
```

Common commands:

```bash
docker compose restart        # restart the bot
docker compose down           # stop + remove
docker compose up -d --build  # rebuild after code changes
```

## Environment variables

| Var | Used by | Notes |
| --- | --- | --- |
| `DISCORD_TOKEN` | core | Bot token. |
| `EVENTS_CHANNEL_ID` | events | Channel that mirrors the calendar. |
| `GOOGLE_CALENDAR_ID` | events | Calendar to read. |
| `GOOGLE_CREDENTIALS_PATH` | events | Path to the service-account JSON. |
| `SUMMARY_CHANNEL_ID` | summary | Channel watched by the rolling memory task. |
| `AI_BACKEND` | ai | `anthropic` or `ollama`. |
| `ANTHROPIC_API_KEY` | ai | Required for the Anthropic backend. |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | ai | Defaults `http://localhost:11434` / `gemma3:4b`. |
| `BOULDER_CHANNEL_ID` | boulder | `0` = listen in all channels. |
| `BOULDER_CHIME_CHANCE` | boulder | Probability (default `0.25`). |

## Commands

- `!events` — force an immediate calendar sync.
- `!Summary <count>` — summarize the last *count* messages (default 50).
- `!memory` — show the current rolling memory (requires Manage Messages).
- `!boulder` — force a random chime, for testing.

## Notes

- AI generation routes through `utils/ai.py`. The Anthropic backend uses
  `claude-haiku-4-5-20251001`; the Ollama backend POSTs to `/api/generate`.
- The Google Calendar client is synchronous, so calls are wrapped in
  `asyncio.to_thread()` to avoid blocking the event loop.
- Cancelled/removed events are never deleted — the embed is greyed out and the
  title prefixed with `❌ CANCELLED —`.

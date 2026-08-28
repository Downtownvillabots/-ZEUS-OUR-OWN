# DOWNTOWN VILLA

A completely new, modular Telegram bot project.

The old bot is used only as a behavior/reference source. This repository does
not depend on the old bot's architecture.

## Current scope

This first release is intentionally small and runnable:

- Docker-based deployment
- Python 3.12
- Pyrofork Telegram client
- Environment-based configuration
- Central logging
- Central runtime state
- Health endpoint for Render
- `/start` command
- `/help` command
- Modular `functions/` feature layout

Database, media indexing, search, IMDb, spell check, rename, admin, backup,
premium, filters, and other features are deliberately NOT implemented yet.
They will be added one feature at a time.

## Run with Docker

Build:

    docker build -t downtown-villa .

Run:

    docker run --env-file .env downtown-villa

## Render

Create a Render Web Service using the repository's Dockerfile.

Set the required environment variables in Render:

- API_ID
- API_HASH
- BOT_TOKEN

Optional:

- LOG_LEVEL=INFO
- PORT=8080
- SESSION_NAME=downtown_villa_bot

The health endpoint is:

    /health

## Project rule

One feature at a time:
design -> implement -> test -> commit -> next feature.

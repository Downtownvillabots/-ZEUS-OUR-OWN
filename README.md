# Telegram Bot

Production-oriented Telegram bot with a modular architecture for search, movies, files, delivery, verification, filtering, moderation, broadcasting, indexing, and administrative functionality.

---

## Project Structure

```text

.

├── bot/

│   ├── app/

│   ├── core/

│   ├── database/

│   ├── services/

│   │   ├── search.py

│   │   ├── movie.py

│   │   ├── delivery.py

│   │   ├── shortener.py

│   │   ├── verification.py

│   │   ├── file\_search.py

│   │   ├── filter.py

│   │   ├── broadcast.py

│   │   ├── moderation.py

│   │   └── indexer.py

│   ├── middleware/

│   ├── handlers/

│   │   ├── init.py

│   │   ├── start.py

│   │   ├── search.py

│   │   ├── user.py

│   │   └── admin.py

│   ├── keyboards/

│   ├── utils/

│   └── integration/

│

├── tests/

├── storage/

├── main.py

├── run.py

├── healthcheck.py

├── Dockerfile

├── docker-compose.yml

├── .dockerignore

├── .env.example

├── .gitignore

└── pyproject.toml

```

---

# Requirements

## Software

Recommended development environment:

* Python 3.12
* PostgreSQL
* Redis
* Docker
* Docker Compose
* Git

The application is designed to run without Docker for development, but Docker Compose is recommended when PostgreSQL and Redis should be isolated from the host system.

---

# Installation

## 1. Clone the project

```bash

git clone <repository-url>

cd <project-directory>

```

Do not commit credentials or private configuration into Git.

---

## 2. Create a virtual environment

Linux/macOS:

```bash

python3.12 -m venv .venv

source .venv/bin/activate

```

Windows PowerShell:

```powershell

py -3.12 -m venv .venv

.venv\\Scripts\\Activate.ps1

```

---

## 3. Install dependencies

Development installation:

```bash

python -m pip install --upgrade pip

python -m pip install -e ".\[dev]"

```

Production-style installation:

```bash

python -m pip install .

```

---

# Environment Configuration

Copy the example environment file:

```bash

cp .env.example .env

```

On Windows:

```powershell

Copy-Item .env.example .env

```

Open `.env` and configure at minimum:

```env

BOT\_TOKEN=your-telegram-bot-token



DATABASE\_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/telegram\_bot



REDIS\_URL=redis://localhost:6379/0

```

For administrators:

```env

ADMIN\_IDS=123456789,987654321

OWNER\_IDS=123456789

```

Never commit `.env`.

---

# Telegram Bot Token

Create the bot through Telegram's official bot-management interface.

Copy the generated token into:

```env

BOT\_TOKEN=

```

Do not put the token directly into Python source code.

Do not commit the token to Git.

Do not print the token in application logs.

---

# Local PostgreSQL and Redis

The easiest development setup is:

```bash

docker compose up -d postgres redis

```

Verify containers:

```bash

docker compose ps

```

Expected services:

```text

telegram-bot-postgres

telegram-bot-redis

```

PostgreSQL is exposed on:

```text

localhost:5432

```

Redis is exposed on:

```text

localhost:6379

```

---

# Running the Bot Locally

After PostgreSQL and Redis are available:

```bash

python main.py

```

Polling mode:

```bash

python main.py --polling

```

Webhook mode:

```bash

python main.py --webhook

```

The runtime mode can also be selected using:

```env

BOT\_MODE=polling

```

or:

```env

BOT\_MODE=webhook

```

Command-line configuration takes precedence over `BOT\_MODE`.

---

# Running with Docker

Build and start the complete stack:

```bash

docker compose up -d --build

```

View service status:

```bash

docker compose ps

```

Follow bot logs:

```bash

docker compose logs -f bot

```

Follow all logs:

```bash

docker compose logs -f

```

Stop the stack:

```bash

docker compose down

```

Stop and remove persistent volumes:

```bash

docker compose down -v

```

Use the volume-removal command carefully because it removes persistent PostgreSQL and Redis data.

---

# Health Checks

Liveness:

```bash

python healthcheck.py --liveness

```

Readiness:

```bash

python healthcheck.py --readiness

```

Complete health check:

```bash

python healthcheck.py

```

Machine-readable output:

```bash

python healthcheck.py --json

```

Quiet mode:

```bash

python healthcheck.py --readiness --quiet

```

Exit codes:

```text

0 = healthy

1 = unhealthy

2 = invalid invocation/configuration

```

Docker uses the readiness check automatically.

---

# Architecture

The project uses a layered architecture.

```text

&#x20;                   Telegram

&#x20;                      │

&#x20;                      ▼

&#x20;               ┌─────────────┐

&#x20;               │  Handlers   │

&#x20;               └──────┬──────┘

&#x20;                      │

&#x20;                      ▼

&#x20;               ┌─────────────┐

&#x20;               │ Middleware  │

&#x20;               └──────┬──────┘

&#x20;                      │

&#x20;                      ▼

&#x20;               ┌─────────────┐

&#x20;               │  Services   │

&#x20;               └──────┬──────┘

&#x20;                      │

&#x20;            ┌─────────┴─────────┐

&#x20;            ▼                   ▼

&#x20;      ┌──────────┐        ┌──────────┐

&#x20;      │ Database │        │  Redis   │

&#x20;      └──────────┘        └──────────┘

```

The integration layer composes these components:

```text

bot/integration/

├── service\_registry.py

├── handler\_registry.py

├── middleware\_registry.py

├── health.py

├── checks.py

└── wiring.py

```

---

# Application Layer

The application layer is responsible for creating and managing the runtime.

Important responsibilities include:

* application construction
* dependency initialization
* Telegram application creation
* polling/webhook selection
* graceful shutdown
* startup validation
* runtime lifecycle

Business logic should not be placed in `main.py`.

---

# Core Layer

The core layer contains cross-cutting application infrastructure.

Typical responsibilities:

* configuration
* logging
* constants
* exceptions
* application context
* runtime utilities
* security primitives

Core modules should remain independent of Telegram-specific business behavior whenever possible.

---

# Database Layer

The database layer owns persistence.

Typical responsibilities:

* SQLAlchemy models
* database engine
* sessions
* repositories
* migrations
* transactions
* database health checks

Database access should generally happen through repositories or dedicated persistence abstractions instead of being duplicated throughout handlers.

---

# Service Layer

Services contain application business logic.

Current service areas include:

```text

search

movie

delivery

shortener

verification

file\_search

filter

broadcast

moderation

indexer

```

Handlers should remain thin.

A preferred request flow is:

```text

Telegram Update

&#x20;     │

&#x20;     ▼

Handler

&#x20;     │

&#x20;     ▼

Service

&#x20;     │

&#x20;     ├──────► Repository

&#x20;     │

&#x20;     ├──────► Redis

&#x20;     │

&#x20;     └──────► External API

&#x20;     │

&#x20;     ▼

Handler response

```

---

# Handler Layer

Handlers translate Telegram updates into application operations.

Current handler areas include:

```text

init

start

search

user

admin

```

Handlers should:

1. validate the incoming update
2. check authorization where necessary
3. extract user input
4. call a service
5. format the response
6. return control to the Telegram framework

Handlers should not contain large database queries or duplicated business logic.

---

# Keyboard Layer

Keyboards provide Telegram UI components.

Keep keyboard construction separate from service logic.

Examples:

```text

search keyboard

pagination keyboard

admin keyboard

user settings keyboard

verification keyboard

movie keyboard

file delivery keyboard

```

Callback data should use stable identifiers and should not contain secrets.

---

# Middleware Layer

Middleware handles cross-cutting request concerns.

Examples:

```text

authentication

authorization

rate limiting

logging

error handling

request context

```

Middleware ordering is important.

A typical order is:

```text

Error handling

&#x20;     ↓

Logging / request context

&#x20;     ↓

Authentication

&#x20;     ↓

Rate limiting

&#x20;     ↓

Authorization

&#x20;     ↓

Handler

```

The actual order should follow the behavior implemented by the existing middleware modules.

---

# Integration Layer

The integration layer is responsible for wiring components together.

The main registries are:

```text

ServiceRegistry

HandlerRegistry

MiddlewareRegistry

```

The central composition object is:

```text

ApplicationWiring

```

Its responsibilities include:

* discovering components
* registering components
* dependency ordering
* initialization
* Telegram installation
* health checks
* shutdown

This keeps application composition out of individual services.

---

# Configuration

Configuration is loaded through the application's configuration layer.

Environment variables should be treated as deployment configuration.

Examples:

```env

ENVIRONMENT=production

DEBUG=false

LOG\_LEVEL=INFO

BOT\_MODE=polling

```

Secrets should never be hard-coded.

---

# Database Migrations

Database schema changes should be managed through migrations.

Typical workflow:

```bash

alembic revision --autogenerate -m "describe change"

```

Review the generated migration before applying it.

Apply migrations:

```bash

alembic upgrade head

```

Check current revision:

```bash

alembic current

```

View migration history:

```bash

alembic history

```

Do not rely on automatic destructive schema changes in production.

---

# Testing

Run the complete test suite:

```bash

pytest

```

Run with coverage:

```bash

pytest --cov=bot --cov-report=term-missing

```

Run unit tests:

```bash

pytest -m unit

```

Run integration tests:

```bash

pytest -m integration

```

Run end-to-end tests:

```bash

pytest -m e2e

```

The project targets a minimum coverage threshold of 80%.

---

# Code Formatting

Ruff formatting:

```bash

ruff format .

```

Check formatting:

```bash

ruff format --check .

```

---

# Linting

Run:

```bash

ruff check .

```

Automatically fix supported issues:

```bash

ruff check . --fix

```

Always review automatically modified code before committing.

---

# Type Checking

Run:

```bash

mypy bot

```

Type checking should be introduced incrementally where older modules are not yet fully typed.

---

# Recommended Development Workflow

Before starting work:

```bash

git pull

```

Create a feature branch:

```bash

git checkout -b feature/my-change

```

Activate the environment:

```bash

source .venv/bin/activate

```

Run tests:

```bash

pytest

```

Implement the change.

Format:

```bash

ruff format .

```

Lint:

```bash

ruff check .

```

Type check:

```bash

mypy bot

```

Run tests again:

```bash

pytest

```

Commit:

```bash

git add .

git commit -m "Describe the change"

```

---

# Production Deployment

Before production:

1. create a production `.env`
2. configure a strong database password
3. configure the Telegram bot token
4. configure administrator IDs
5. configure Redis
6. configure webhook settings if webhook mode is used
7. run database migrations
8. build the Docker image
9. start the application
10. verify readiness
11. inspect application logs
12. verify Telegram functionality

Build:

```bash

docker compose build

```

Start:

```bash

docker compose up -d

```

Verify:

```bash

docker compose ps

```

Check logs:

```bash

docker compose logs --tail=200 bot

```

Run readiness:

```bash

docker compose exec bot python healthcheck.py --readiness

```

---

# Security Rules

Never commit:

```text

.env

BOT\_TOKEN

DATABASE\_PASSWORD

REDIS\_PASSWORD

SECRET\_KEY

ENCRYPTION\_KEY

JWT\_SECRET

private keys

API credentials

```

Use:

```text

.env.example

```

for configuration documentation.

Use:

```text

.env

```

for local secrets.

Production secrets should preferably be provided through the deployment platform's secret-management mechanism.

---

# Logging

Logs should not expose:

* Telegram bot tokens
* database passwords
* API keys
* authentication tokens
* private user information

Debug logging should be disabled in production unless temporarily required for diagnosis.

Recommended production configuration:

```env

ENVIRONMENT=production

DEBUG=false

LOG\_LEVEL=INFO

LOG\_FORMAT=json

```

---

# Redis Usage

Redis can be used for:

* caching
* rate limiting
* temporary verification state
* distributed locks
* queues
* short-lived session data

Redis should not be treated as the permanent source of truth for important application data.

PostgreSQL remains the durable persistence layer.

---

# Background Workers

Long-running work should not block Telegram update processing.

Examples include:

* indexing
* large broadcasts
* bulk delivery
* cleanup
* expensive external API operations

Use queues/workers for operations that can safely execute asynchronously.

Workers must support graceful shutdown.

---

# Graceful Shutdown

The application should:

1. stop accepting new work
2. stop Telegram polling/webhook processing
3. finish safe in-flight operations
4. stop background workers
5. flush logging
6. close Redis connections
7. close database connections
8. release resources

Shutdown should be bounded by a timeout.

Configured through:

```env

SHUTDOWN\_TIMEOUT=30

```

---

# Docker Volumes

The Compose configuration uses persistent volumes for:

```text

postgres\_data

redis\_data

bot\_storage

bot\_tmp

bot\_logs

```

Do not delete production volumes unless data destruction is explicitly intended.

---

# Troubleshooting

## Bot does not start

Check:

```bash

docker compose logs bot

```

Then verify:

```env

BOT\_TOKEN=

DATABASE\_URL=

REDIS\_URL=

```

---

## PostgreSQL unavailable

Check:

```bash

docker compose ps postgres

```

Then:

```bash

docker compose logs postgres

```

---

## Redis unavailable

Check:

```bash

docker compose ps redis

```

Then:

```bash

docker compose logs redis

```

---

## Configuration errors

Run:

```bash

python healthcheck.py --readiness

```

The health output identifies configuration or dependency failures.

---

# Useful Commands

Start everything:

```bash

docker compose up -d --build

```

Stop everything:

```bash

docker compose down

```

View logs:

```bash

docker compose logs -f

```

Restart bot:

```bash

docker compose restart bot

```

Open a shell:

```bash

docker compose exec bot sh

```

Check database:

```bash

docker compose exec postgres pg\_isready

```

Check Redis:

```bash

docker compose exec redis redis-cli ping

```

Check readiness:

```bash

docker compose exec bot python healthcheck.py --readiness

```

---

# Architecture Principles

The project follows these principles:

### Single responsibility

Each layer should have one primary responsibility.

### Dependency inversion

Business services should not depend directly on Telegram update objects where avoidable.

### Thin handlers

Handlers orchestrate requests rather than implementing large business workflows.

### Centralized configuration

Configuration belongs in the configuration layer.

### Explicit dependencies

Services should receive dependencies rather than creating hidden global connections.

### Durable persistence

Important state belongs in PostgreSQL.

### Fast temporary state

Short-lived state may use Redis.

### Safe shutdown

Every long-lived resource should have a cleanup path.

### Observable runtime

Health checks and structured logs should make failures diagnosable.

---

# Development Status

Current major components:

```text

Core                 ✅

Database             ✅

Services             ✅

Middleware           ✅

Handlers             ✅

Keyboards            ✅

Application          ✅

Integration          ✅

Runtime entrypoints  ✅

Docker               ✅

Compose              ✅

Health checks        ✅

Environment template ✅

Documentation        ✅

```

The next phase should focus on **verification and integration testing**, not adding arbitrary duplicate layers.

---

# License

Add the project's actual license here before publishing or distributing the repository.

---

# Professional Architecture Help

Need professional help reviewing, implementing, or deploying your architecture?

Please contact me at @D_W_T_1

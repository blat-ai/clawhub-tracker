VERSION 0.8

FROM python:3.13-slim
WORKDIR /app

deps:
    RUN pip install uv
    COPY pyproject.toml .
    RUN uv venv && uv pip install -e ".[dev]"

src:
    FROM +deps
    COPY app/ app/
    COPY tests/ tests/
    COPY crontab crontab

lint:
    FROM +src
    RUN .venv/bin/ruff check .
    RUN .venv/bin/ruff format --check .

test:
    FROM +src
    RUN .venv/bin/pytest tests/unit -v

scrape:
    FROM +src
    RUN mkdir -p data
    RUN .venv/bin/python -m app.scraper
    SAVE ARTIFACT data/skills.json AS LOCAL data/skills.json
    SAVE ARTIFACT data/clawhub.duckdb AS LOCAL data/clawhub.duckdb

all:
    BUILD +lint
    BUILD +test

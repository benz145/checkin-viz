# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PUID=1000
ENV PGID=1000

RUN apt-get update -y
RUN apt-get install -y libcairo2 git
RUN pip install poetry

COPY README.md ./
COPY poetry.lock ./
COPY pyproject.toml ./
COPY scripts/entrypoint /
COPY src /src
COPY src/static/*.css /src/static/

RUN --mount=type=bind,source=.git,target=/git,readonly \
    export VERSION_NUMBER="$(date -u +%Y-%m-%dT%H:%M:%SZ)|$(git --git-dir=/git rev-parse --short HEAD)" && \
    python -c "import os; from pathlib import Path; p = Path('/src/main.py'); p.write_text(p.read_text().replace('__VERSION_NUMBER__ = \"__VERSION_NUMBER__\"', '__VERSION_NUMBER__ = ' + repr(os.environ['VERSION_NUMBER'])))"

RUN poetry install --no-interaction --no-ansi

ENTRYPOINT [ "poetry", "run", "./entrypoint" ]

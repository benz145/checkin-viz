FROM python:3.12-slim

ENV PUID=1000
ENV PGID=1000

RUN apt-get update -y
RUN apt-get install -y libcairo2
RUN pip install poetry

COPY README.md ./
COPY poetry.lock ./
COPY pyproject.toml ./
COPY scripts/entrypoint /
COPY src /src
COPY src/static/*.css /src/static/

ARG VERSION_NUMBER=__VERSION_NUMBER__
RUN python -c "import os; from pathlib import Path; p = Path('/src/main.py'); p.write_text(p.read_text().replace('\"__VERSION_NUMBER__\"', repr(os.environ['VERSION_NUMBER'])))"

RUN poetry install --no-interaction --no-ansi

ENTRYPOINT [ "poetry", "run", "./entrypoint" ]

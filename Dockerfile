FROM python:3.12-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /usr/local/bin/
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-trixie
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY --from=build /app/.venv .venv
COPY bot.py pchome.py store.py ./
USER 1000:1000
ENTRYPOINT ["python", "bot.py"]

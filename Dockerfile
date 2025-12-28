FROM ghcr.io/astral-sh/uv:0.9.5-python3.13-alpine AS base
WORKDIR /app

FROM base AS deps
# python-olm requires a C/C++ compiler and cmake/gmake.
RUN apk add --no-cache build-base cmake
COPY .python-version pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache

FROM base
COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY src src
CMD ["python", "src/main.py"]

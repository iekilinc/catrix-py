FROM python:3.13-alpine AS base
WORKDIR /app

FROM base AS deps
# python-olm requires a C/C++ compiler and cmake/gmake.
RUN apk add --no-cache build-base cmake
COPY requirements.txt .
ENV PIP_NO_CACHE_DIR=1
RUN python -m venv /.venv && \
    . /.venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt

FROM base
COPY --from=deps /.venv /.venv
ENV PATH="/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY src src
CMD ["python", "src/main.py"]

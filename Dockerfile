FROM python:3.12-slim AS base
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENTRYPOINT ["certbot"]

FROM base AS test
RUN pip install --no-cache-dir '.[test]'
COPY tests ./tests
COPY integrations ./integrations
ENTRYPOINT ["pytest"]

FROM base AS runtime

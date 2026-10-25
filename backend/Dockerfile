FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv
FROM python:3.12.13-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/app/backend/.venv/bin:$PATH
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN uv sync --project backend --locked --no-dev --no-install-project
COPY backend/src ./backend/src
RUN uv sync --project backend --locked --no-dev \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin docksight
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "docksight.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

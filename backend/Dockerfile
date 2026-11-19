FROM ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d AS uv
FROM python:3.14.10-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    DOCKSIGHT_STATE_PATH=/var/lib/docksight/state.sqlite3 \
    PATH=/app/backend/.venv/bin:$PATH

COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN uv sync --project backend --locked --no-dev --no-install-project

COPY backend/src ./backend/src
RUN uv sync --project backend --locked --no-dev \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin docksight \
    && install -d -o 10001 -g 10001 /var/lib/docksight

USER 10001:10001
VOLUME ["/var/lib/docksight"]
EXPOSE 8000
CMD ["uvicorn", "docksight.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

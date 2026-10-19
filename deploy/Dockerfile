FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Runtime deps only; the project itself is copied after so layer caching works.
RUN pip install --upgrade pip && pip install nautilus-trader==1.231.0 pyarrow==26.0.0
COPY src ./src
COPY configs ./configs
COPY research ./research
COPY tools ./tools
RUN pip install -e .
RUN useradd -r -u 10001 cryptobot && mkdir -p /app/data /app/runs && \
    chown -R cryptobot:cryptobot /app
USER cryptobot
ENTRYPOINT ["python", "-m", "cryptobot"]
CMD ["--help"]

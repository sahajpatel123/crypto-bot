FROM python:3.12-slim
WORKDIR /opt/cryptobot
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY configs ./configs
RUN pip install --no-cache-dir uv && uv sync --locked --extra dev || pip install -e .
# Prod submission stays OFF by default (configs/prod.toml). No keys in image.
ENTRYPOINT ["cryptobot"]
CMD ["doctor", "--config", "configs/paper.toml"]

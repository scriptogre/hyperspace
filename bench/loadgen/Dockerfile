# Load generator that runs the bench scripts behind a shaped (netem) link, so
# crowd.py / echo_latency.py see real-ish RTT, jitter, loss and bandwidth instead
# of free loopback. Needs --cap-add=NET_ADMIN to program tc.
FROM python:3.14-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir websockets "httpx[http2]"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app
ENTRYPOINT ["/entrypoint.sh"]

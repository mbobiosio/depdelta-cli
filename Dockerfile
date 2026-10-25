FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/depdelta-cli
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /opt/depdelta-cli

# CI mounts the checkout here (GitLab and Jenkins run in their own workdir).
WORKDIR /workspace
# The checkout belongs to another user inside CI containers.
RUN git config --system --add safe.directory '*'

ENTRYPOINT []
CMD ["depdelta"]

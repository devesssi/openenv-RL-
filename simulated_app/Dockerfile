# Lightweight Node.js image for the DevOps Sandbox
FROM node:20-slim

# Install bash, git, curl, and common debugging tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bash \
        git \
        curl \
        procps \
        sed \
        grep \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the buggy application
COPY package.json /app/package.json
RUN npm install --production 2>/dev/null || true

COPY . /app

# The container stays alive so the agent can interact via `docker exec`
# The agent is responsible for starting/restarting the Node app.
CMD ["tail", "-f", "/dev/null"]

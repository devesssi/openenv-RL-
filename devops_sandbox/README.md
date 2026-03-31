---
title: Self-Healing DevOps Sandbox
emoji: 🔧
colorFrom: red
colorTo: green
sdk: docker
pinned: false
app_port: 8000
base_path: /web
tags:
  - openenv
---

# Self-Healing DevOps Sandbox

An OpenEnv RL environment where an AI agent is dropped into a **broken Node.js backend** inside a Docker container. The agent must use **bash commands only** to diagnose bugs, edit files, and fix the app -- just like a real DevOps engineer would.

Built for the **Meta PyTorch OpenEnv Hackathon**.

---

## What Is This?

A 3-task challenge of increasing difficulty. The agent starts in a Docker container with a broken Express.js app in `/app` and must make all endpoints healthy.

| # | Difficulty | Bug             | What's Wrong                          |
|---|-----------|-----------------|---------------------------------------|
| 1 | Easy      | `config.json`    | Port set to `9999` instead of `3000`  |
| 2 | Medium    | `routes/users.js`| Missing `)` causes SyntaxError crash  |
| 3 | Hard      | `routes/data.js` | Missing `await` causes HTTP 500       |

**Goal:** Fix all bugs so these endpoints return HTTP 200:
- `GET /health` returns `{"status": "ok"}`
- `GET /api/users` returns `{"users": [...]}`
- `GET /api/data` returns `{"records": [...]}`

---

## Scoring (Partial Rewards)

The grader runs **after every command** and awards cumulative points:

| Milestone                        | Points | Total    |
|----------------------------------|--------|----------|
| App starts on port 3000          | +0.35  | 0.35     |
| `/health` returns 200            | +0.10  | 0.45     |
| `/api/users` returns valid JSON  | +0.15  | 0.60     |
| `/api/data` returns valid JSON   | +0.25  | 0.85     |
| All endpoints correct            | +0.15  | **1.00** |

---

## Getting Started

### Prerequisites

- **Python 3.10+**
- **Docker Desktop** (running)
- **uv** package manager (`pip install uv`)

### 1. Install Dependencies

```bash
cd devops_sandbox
uv sync
```

### 2. Build the Sandbox Docker Image

```bash
docker build -t devops-sandbox-node:latest -f simulated_app/Dockerfile simulated_app/
```

### 3. Start the Environment Server

```bash
uv run server
```

The server starts at `http://localhost:8000`.

### 4. Run the Baseline Agent

In a **separate terminal**:

```bash
# Set your OpenAI API key
export OPENAI_API_KEY="sk-..."          # Linux/Mac
$env:OPENAI_API_KEY = "sk-..."          # PowerShell

# Run the baseline
uv run python baseline.py
```

---

## Test Your Own Agent

### Option A: Use the Python Client

```python
from devops_sandbox import BashAction, DevopsSandboxEnv

with DevopsSandboxEnv(base_url="http://localhost:8000").sync() as env:
    # Reset creates a fresh Docker container
    result = env.reset()
    print(result.observation.stdout)       # Task description
    print(result.observation.grader_score)  # 0.0

    # Send bash commands
    result = env.step(BashAction(command="cat /app/config.json"))
    print(result.observation.stdout)       # File contents
    print(result.observation.grader_score)  # Score after grading

    # Fix a bug
    result = env.step(BashAction(command="sed -i 's/9999/3000/' /app/config.json"))
    print(result.observation.grader_score)  # Partial score

    # Check if done
    if result.done:
        print("Episode complete!")
```

### Option B: Use the REST API Directly

```bash
# Reset the environment
curl -X POST http://localhost:8000/reset

# Send a command
curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"action": {"command": "ls -la /app"}}'
```

### Option C: Use the WebSocket Endpoint

Connect to `ws://localhost:8000/ws` for persistent sessions.

---

## Project Structure

```
devops_sandbox/
|-- openenv.yaml                 # OpenEnv manifest
|-- pyproject.toml               # Python dependencies
|-- README.md                    # This file
|-- baseline.py                  # LLM-powered baseline agent
|-- models.py                    # BashAction & TerminalObservation schemas
|-- client.py                    # Python client for the environment
|
|-- server/
|   |-- app.py                   # FastAPI server (entry point)
|   +-- devops_sandbox_environment.py  # Environment logic + grader
|
+-- simulated_app/               # The broken Node.js app (Docker context)
    |-- Dockerfile               # node:20-slim sandbox container
    |-- package.json             # Express.js project
    |-- server.js                # Main entry point
    |-- config.json              # Bug 1: wrong port
    +-- routes/
        |-- users.js             # Bug 2: syntax error
        +-- data.js              # Bug 3: missing await
```

---

## How It Works

```
+-----------+   BashAction    +------------+   docker exec   +--------------+
|  Agent    | --------------> |  OpenEnv   | --------------> |  Docker      |
| (LLM/RL) |                 |  Server    |                 |  Container   |
|           | <-------------- |  (8000)    | <-------------- |  (broken app)|
+-----------+  Observation    +-----+------+   stdout/stderr +--------------+
               + grader_score       |
                              +-----+------+
                              |   Grader   |
                              | (curl test |
                              |  endpoints)|
                              +------------+
```

1. **Agent** sends a `BashAction` (e.g., `cat /app/config.json`)
2. **Server** runs it inside the Docker container via `docker exec`
3. **Grader** restarts the Node app and curls all endpoints
4. **Observation** returns: stdout, stderr, score (0.0-1.0), feedback

---

## Configuration

| Env Variable        | Default                  | Description                        |
|--------------------|--------------------------|------------------------------------|
| `OPENAI_API_KEY`    | *(required)*             | OpenAI API key for baseline        |
| `OPENAI_MODEL`      | `gpt-4o-mini`            | LLM model to use                   |
| `OPENAI_BASE_URL`   | *(OpenAI default)*       | Custom endpoint (Ollama, vLLM)     |
| `MAX_TURNS`         | `30`                     | Max steps per episode              |
| `DEVOPS_SANDBOX_URL`| `http://localhost:8000`  | Environment server URL             |

### Use with Local LLMs (Ollama, vLLM)

```bash
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_MODEL="llama3"
export OPENAI_API_KEY="dummy"
uv run python baseline.py
```

---

## Validation

```bash
uv run openenv validate
# Expected: [OK] devops_sandbox: Ready for multi-mode deployment
```

---

## License

BSD-style license. See LICENSE for details.

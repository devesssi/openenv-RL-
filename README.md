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

# 🔧 Self-Healing DevOps Sandbox

An **OpenEnv RL environment** where an AI agent is dropped into a broken Node.js Express backend and must use **bash commands only** to diagnose and fix production-like bugs — just like a real DevOps engineer responding to a 3 AM incident.

Built for the **Meta PyTorch OpenEnv Hackathon**.

---

## 🎯 Why This Environment?

DevOps debugging is one of the most **high-value, real-world tasks** for AI agents. Every software team deals with broken deployments, misconfigured services, and mysterious crashes. This environment tests whether an AI agent can:

- **Read and understand** error logs, config files, and source code
- **Diagnose root causes** from symptoms (crash logs → specific file + line)
- **Apply targeted fixes** using command-line tools (sed, echo, etc.)
- **Verify its own work** by restarting services and checking endpoints

---

## 🏗️ Task Design

### Three Difficulty Levels

| # | Task | Bugs | What's Broken | Grading Target |
|---|------|------|---------------|----------------|
| 1 | `easy` | 1 | `config.json` → port `9999` instead of `3000` | Fix port, app starts |
| 2 | `medium` | 2 | + `routes/users.js` → missing `)` causes SyntaxError | + `/api/users` works |
| 3 | `hard` | 3 | + `routes/data.js` → missing `await` breaks async response | All endpoints pass |

Each task builds on the previous — meaningful difficulty progression where easy tasks are subsets of harder ones.

### The Broken App (`/app`)

```
/app/
├── config.json          ← Bug 1: port set to 9999 (should be 3000)
├── package.json         ← Express.js project config
├── server.js            ← Main entry point (loads config + routes)
└── routes/
    ├── users.js         ← Bug 2: missing closing parenthesis on router.get()
    └── data.js          ← Bug 3: missing `await` before async DB call
```

---

## 📊 Reward Shaping

The grader runs **after every command** and awards granular partial credit:

### Phase 1: File-Level Verification
| Event | Points |
|-------|--------|
| Modified `config.json` | +0.05 |
| Modified `routes/users.js` | +0.05 |
| Modified `routes/data.js` | +0.05 |

### Phase 2: HTTP Endpoint Testing
| Milestone | Points |
|-----------|--------|
| App starts on port 3000 | +0.30 |
| `GET /health` returns 200 | +0.10 |
| `GET /api/users` returns valid JSON | +0.15 |
| `GET /api/data` returns valid JSON | +0.20 |
| All endpoints passing (bonus) | +0.05 |

### Phase 3: Difficulty Scaling
Raw scores are scaled by task difficulty so each task can reach near-maximum independently.

> **All scores are strictly within (0, 1)** per the OpenEnv specification — never exactly 0.0 or 1.0.

---

## 🚀 Getting Started

### Docker (Recommended)

```bash
docker build -t devops-sandbox:latest .
docker run --rm -p 8000:8000 devops-sandbox:latest
curl http://localhost:8000/health
```

Health response: `{"status":"healthy","service":"devops_sandbox"}`

### Without Docker

```bash
uv sync
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

### Quick Start (Demo)

Update the API key in `scenario_config.json` and run:

```bash
python inference.py
```

---

## 🧪 Test Your Own Agent

### Option A: Python Client

```python
from client import DevopsSandboxEnv
from models import BashAction

with DevopsSandboxEnv(base_url="http://localhost:8000").sync() as env:
    # Reset with task difficulty
    result = env.reset(task_name="easy")
    print(result.observation.stdout)        # Task description
    print(result.observation.grader_score)   # 0.01

    # Send bash commands
    result = env.step(BashAction(command="cat /app/config.json"))
    print(result.observation.stdout)         # File contents
    print(result.observation.metadata)       # Rich metadata

    # Fix a bug
    result = env.step(BashAction(command="sed -i 's/9999/3000/' /app/config.json"))
    print(result.observation.grader_score)   # Score increases
    print(result.observation.grader_feedback) # "✓ Modified config.json (+0.05)"
```

### Option B: REST API

```bash
# Reset the environment
curl -X POST http://localhost:8000/reset -d '{"task_name": "hard"}'

# Send a command
curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"action": {"command": "ls -la /app"}}'
```

### Option C: WebSocket

Connect to `ws://localhost:8000/ws` for persistent sessions.

---

## 📁 Project Structure

```
devops_sandbox/
├── openenv.yaml               # OpenEnv manifest (spec_version: 1)
├── pyproject.toml              # Python dependencies
├── Dockerfile                  # HF Spaces deployment
├── scenario_config.json        # Task definitions + verifiers
├── models.py                   # BashAction & TerminalObservation (Pydantic)
├── client.py                   # Python client for the environment
├── inference.py                # LLM baseline agent (3-task evaluation)
│
├── server/
│   ├── app.py                  # FastAPI server (OpenEnv entry point)
│   └── devops_sandbox_environment.py  # Core environment + grader
│
└── simulated_app/              # The broken Node.js app
    ├── package.json
    ├── server.js
    ├── config.json             # Bug 1: wrong port
    └── routes/
        ├── users.js            # Bug 2: syntax error
        └── data.js             # Bug 3: missing await
```

---

## ⚙️ Architecture

```
┌──────────┐   BashAction    ┌────────────┐   subprocess   ┌──────────────┐
│  Agent   │ ──────────────> │  OpenEnv   │ ────────────> │  /app/       │
│ (LLM/RL) │                 │  Server    │               │ (broken app) │
│          │ <────────────── │  (:8000)   │ <──────────── │              │
└──────────┘  Observation    └─────┬──────┘  stdout/stderr └──────────────┘
              + grader_score       │
              + metadata     ┌─────┴──────┐
                             │  Grader    │
                             │ ┌────────┐ │
                             │ │File Δ  │ │  ← Detects which files were modified
                             │ │Checker │ │
                             │ ├────────┤ │
                             │ │HTTP    │ │  ← Starts app, curls all endpoints
                             │ │Tester  │ │
                             │ └────────┘ │
                             └────────────┘
```

1. **Agent** sends a `BashAction` (e.g., `cat /app/config.json`)
2. **Server** executes it via `subprocess.run()` in the `/app` directory
3. **Grader** runs two-phase verification:
   - **File tracking**: MD5 hash comparison to detect which bug files changed
   - **HTTP testing**: Starts the Node app, curls `/health`, `/api/users`, `/api/data`
4. **Observation** returns: stdout, stderr, score (0.01–0.99), feedback, and metadata

---

## 📋 Observation Metadata

Each observation includes rich metadata for training analysis:

```json
{
  "episode_id": "abc-123",
  "step": 3,
  "task": "hard",
  "max_steps": 50,
  "bugs_total": 3,
  "files_modified": ["config.json", "routes/users.js"],
  "commands_count": 3
}
```

---

## 🔧 Configuration

| Env Variable | Default | Description |
|-------------|---------|-------------|
| `HF_TOKEN` | *(required)* | Hugging Face token for LLM API |
| `MODEL_NAME` | `gpt-4o-mini` | LLM model to use |
| `API_BASE_URL` | `https://router.huggingface.co/v1` | LLM endpoint |
| `MAX_TURNS` | `8` | Max steps per task in inference |

---

## ✅ Validation

```bash
uv run openenv validate
# Expected: [OK] devops_sandbox: Ready for deployment
```

---

## 📄 License

BSD-style license. See LICENSE for details.

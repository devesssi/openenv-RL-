#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Baseline inference script for the Self-Healing DevOps Sandbox.

Uses an LLM (via the OpenAI-compatible API) to diagnose and fix a broken
Node.js backend running inside a Docker container.
"""

import json
import os
import sys

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: 'openai' package is required. Install with: pip install openai")
    sys.exit(1)

from client import DevopsSandboxEnv
from models import BashAction

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE_URL = os.getenv("API_BASE_URL") or "https://router.huggingface.co/v1"
MODEL_NAME = os.getenv("MODEL_NAME") or "gpt-4o-mini"
HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("API_KEY")

ENV_URL = os.getenv("DEVOPS_SANDBOX_URL", "http://localhost:8000")
TASK_NAME = os.getenv("MY_ENV_V4_TASK", "devops_sandbox")
BENCHMARK = os.getenv("MY_ENV_V4_BENCHMARK", "devops_sandbox")
MAX_TURNS = int(os.getenv("MAX_TURNS", "8"))

SYSTEM_PROMPT = """\
You are an expert DevOps engineer and Node.js developer.

You have been dropped into a Linux container with a broken Express.js backend in /app.
Your goal is to diagnose and fix ALL bugs so the app runs correctly.

RULES:
1. Respond ONLY with a JSON object: {"command": "<bash command>"}
2. Use standard bash/Linux commands (ls, cat, grep, sed, node, npm, etc.)
3. Do NOT use interactive editors (vi, nano). Use sed or echo/cat with redirection.
4. After fixing bugs, restart the app with: cd /app && npm start &
5. Be methodical: read files first, understand the bug, then fix it.

EXPECTED FINAL STATE:
- App starts without errors on port 3000
- GET /health → 200
- GET /api/users → 200 with JSON containing "users" array
- GET /api/data → 200 with JSON containing "records" array
"""

def extract_command(llm_response: str) -> str:
    """Extract a bash command from the LLM's response (JSON or raw text)."""
    try:
        data = json.loads(llm_response.strip())
        if isinstance(data, dict) and "command" in data:
            return data["command"]
    except (json.JSONDecodeError, TypeError):
        pass

    if "```" in llm_response:
        lines = llm_response.split("```")
        for block in lines[1::2]:
            code = block.strip()
            if code.startswith("json"):
                code = code[4:].strip()
                try:
                    data = json.loads(code)
                    if isinstance(data, dict) and "command" in data:
                        return data["command"]
                except (json.JSONDecodeError, TypeError):
                    pass
            elif code.startswith("bash") or code.startswith("sh"):
                code = code.split("\n", 1)[-1].strip()
                return code
            else:
                first_line = code.split("\n")[0].strip()
                if first_line:
                    return first_line

    cmd = llm_response.strip().strip("`").strip()
    if cmd.startswith("{"):
        try:
            return json.loads(cmd)["command"]
        except Exception:
            pass
    return cmd

def main():
    if not HF_TOKEN:
        pass # we can let it fail or use empty key depending on endpoint

    client = OpenAI(api_key=HF_TOKEN or "dummy_key", base_url=API_BASE_URL)

    TASKS = ["easy", "medium", "hard"]

    # Note: openenv evaluation specifically needs exactly 3 things: [START], [STEP] logs, [END]
    for task_name in TASKS:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        try:
            with DevopsSandboxEnv(base_url=ENV_URL).sync() as env:
                result = env.reset(task_name=task_name)
                obs = result.observation
                
                print(f"[START] task={task_name} env={BENCHMARK} model={MODEL_NAME}", flush=True)

                messages.append({
                    "role": "user",
                    "content": (
                        f"Here is the initial state of the broken app:\n\n"
                        f"```\n{obs.stdout}\n```\n\n"
                        f"Current directory: {obs.current_dir}\n"
                        f"Score: {obs.grader_score}/1.0\n\n"
                        f"What bash command should I run first?"
                    ),
                })

                rewards = []
                is_done = False
                steps_taken = 0
                final_score = 0.0

                for turn in range(1, MAX_TURNS + 1):
                    try:
                        response = client.chat.completions.create(
                            model=MODEL_NAME,
                            messages=messages,
                            temperature=0.2,
                            max_tokens=256,
                        )
                        llm_text = response.choices[0].message.content or ""
                    except Exception as e:
                        err_msg = str(e).replace('"', "'")
                        break

                    command = extract_command(llm_text)
                    if not command:
                        command = "ls -la /app"

                    error_msg = "null"
                    try:
                        result = env.step(BashAction(command=command))
                        obs = result.observation
                    except Exception as e:
                        obs = env.state  # Mock failed obs
                        error_msg = str(e).replace('\n', ' ')

                    steps_taken += 1
                    reward_val = obs.reward if hasattr(obs, 'reward') else getattr(obs, 'grader_score', 0.0)
                    rewards.append(f"{reward_val:.2f}")
                    is_done = result.done if hasattr(result, 'done') else getattr(obs, 'done', False)
                    done_str = "true" if is_done else "false"

                    action_str = command.replace('\n', ' ; ')
                    print(f"[STEP] step={steps_taken} action={action_str} reward={reward_val:.2f} done={done_str} error={error_msg}", flush=True)

                    messages.append({"role": "assistant", "content": llm_text})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Command output:\n"
                            f"stdout:\n```\n{getattr(obs, 'stdout', '')}\n```\n"
                            f"stderr:\n```\n{getattr(obs, 'stderr', '')}\n```\n"
                            f"Current score: {getattr(obs, 'grader_score', 0.0)}/1.0\n"
                            f"Grader feedback: {getattr(obs, 'grader_feedback', '')}\n\n"
                            f"What command should I run next?"
                        ),
                    })

                    final_score = getattr(obs, 'grader_score', 0.0)
                    if getattr(obs, 'grader_score', 0.0) >= 0.99 or getattr(obs, 'done', False) or (hasattr(result, 'done') and result.done):
                        break

                success_str = "true" if final_score >= 0.99 else "false"
                rewards_str = ",".join(rewards) if rewards else "0.00"
                print(f"[END] success={success_str} steps={steps_taken} score={final_score:.2f} rewards={rewards_str}", flush=True)
        except Exception as e:
             # Make sure to emit END log even on catastrophic wrapper failures so Hackathon doesn't crash inference.py
             print(f"[END] success=false steps=0 score=0.00 rewards=0.00", flush=True)

if __name__ == "__main__":
    main()

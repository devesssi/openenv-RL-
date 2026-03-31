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

Usage:
    export OPENAI_API_KEY="sk-..."
    python baseline.py

    # Or with a custom endpoint (e.g., local vLLM):
    export OPENAI_BASE_URL="http://localhost:8080/v1"
    python baseline.py
"""

import json
import os
import sys

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: 'openai' package is required. Install with: pip install openai")
    sys.exit(1)

from devops_sandbox import BashAction, DevopsSandboxEnv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ENV_URL = os.getenv("DEVOPS_SANDBOX_URL", "http://localhost:8000")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_TURNS = int(os.getenv("MAX_TURNS", "30"))

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
    # Try JSON parsing first
    try:
        data = json.loads(llm_response.strip())
        if isinstance(data, dict) and "command" in data:
            return data["command"]
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting from markdown code block
    if "```" in llm_response:
        lines = llm_response.split("```")
        for block in lines[1::2]:  # odd indices are code blocks
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

    # Fallback: treat entire response as a command
    cmd = llm_response.strip().strip("`").strip()
    if cmd.startswith("{"):
        # One more try
        try:
            return json.loads(cmd)["command"]
        except Exception:
            pass
    return cmd


def main():
    print("=" * 60)
    print(" Self-Healing DevOps Sandbox — Baseline Agent")
    print("=" * 60)

    client = OpenAI()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    with DevopsSandboxEnv(base_url=ENV_URL).sync() as env:
        # Reset the environment
        print("\n[*] Resetting environment...")
        result = env.reset()
        obs = result.observation

        print(f"\n[INIT] Task prompt:\n{obs.stdout[:500]}...")
        print(f"[INIT] Score: {obs.grader_score} | Feedback: {obs.grader_feedback}")

        # Add initial observation to messages
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

        for turn in range(1, MAX_TURNS + 1):
            print(f"\n{'─' * 40}")
            print(f"Turn {turn}/{MAX_TURNS}")
            print(f"{'─' * 40}")

            # Get LLM response
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=256,
                )
                llm_text = response.choices[0].message.content or ""
            except Exception as e:
                print(f"[ERROR] LLM call failed: {e}")
                break

            # Extract command
            command = extract_command(llm_text)
            if not command:
                print("[WARN] Could not extract command from LLM response")
                command = "ls -la /app"

            print(f"[CMD] {command}")

            # Execute in environment
            result = env.step(BashAction(command=command))
            obs = result.observation

            stdout_preview = obs.stdout[:300] if obs.stdout else "(empty)"
            stderr_preview = obs.stderr[:200] if obs.stderr else "(none)"
            print(f"[OUT] {stdout_preview}")
            if obs.stderr:
                print(f"[ERR] {stderr_preview}")
            print(f"[SCORE] {obs.grader_score:.2f} | {obs.grader_feedback}")

            # Add to conversation
            messages.append({"role": "assistant", "content": llm_text})
            messages.append({
                "role": "user",
                "content": (
                    f"Command output:\n"
                    f"stdout:\n```\n{obs.stdout}\n```\n"
                    f"stderr:\n```\n{obs.stderr}\n```\n"
                    f"Current score: {obs.grader_score}/1.0\n"
                    f"Grader feedback: {obs.grader_feedback}\n\n"
                    f"What command should I run next?"
                ),
            })

            # Check if done
            if result.done:
                print(f"\n{'=' * 60}")
                if obs.grader_score >= 1.0:
                    print(" ✅ ALL BUGS FIXED — PERFECT SCORE!")
                else:
                    print(f" Episode ended. Final score: {obs.grader_score:.2f}/1.0")
                print(f"{'=' * 60}")
                break
        else:
            print(f"\n[!] Max turns ({MAX_TURNS}) reached.")
            print(f"    Final score: {obs.grader_score:.2f}/1.0")

    print("\n[*] Done.")


if __name__ == "__main__":
    main()

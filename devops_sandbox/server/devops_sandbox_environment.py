# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Self-Healing DevOps Sandbox — Environment Implementation.

Spins up an isolated Docker container with a broken Node.js backend.
The RL agent executes bash commands to diagnose and fix 3 bugs.
A programmatic grader awards partial credit (0.0 → 1.0) after every step.
"""

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import BashAction, TerminalObservation
except ImportError:
    from models import BashAction, TerminalObservation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONTAINER_NAME_PREFIX = "devops_sandbox_"
IMAGE_NAME = "devops-sandbox-node:latest"
EXPECTED_PORT = 3000          # The port the fixed app should listen on
MAX_STEPS = 50                # Episode budget
SIMULATED_APP_DIR = Path(__file__).resolve().parent.parent / "simulated_app"


class DevOpsSandbox(Environment):
    """
    RL environment: fix a broken Node.js backend inside a Docker container.

    reset() → build image (if needed) + start container + return initial obs
    step()  → docker exec the agent's command + run grader → obs + reward
    close() → tear down container
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def __init__(self):
        super().__init__()
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._container_name: Optional[str] = None
        self._container_running: bool = False
        self._current_dir: str = "/app"
        self._last_score: float = 0.0

    # ------------------------------------------------------------------
    # reset
    # ------------------------------------------------------------------
    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs: Any,
    ) -> TerminalObservation:
        """Build the Docker image, start the container, return the task prompt."""
        # Cleanup previous episode
        self._cleanup_container()

        # New episode
        eid = episode_id or str(uuid4())
        self._state = State(episode_id=eid, step_count=0)
        self._last_score = 0.0
        self._current_dir = "/app"

        # Build image (idempotent — Docker caches layers)
        self._build_image()

        # Start container
        self._container_name = f"{CONTAINER_NAME_PREFIX}{eid[:8]}"
        self._start_container()

        # Inject the grader script into the container
        self._inject_grader_script()

        # Gather initial observation
        init_stdout = self._docker_exec("ls -la /app && echo '---' && cat /app/config.json")

        task_prompt = (
            "=== SELF-HEALING DEVOPS SANDBOX ===\n"
            "You have been dropped into a Docker container with a broken Node.js "
            "Express backend in /app.\n\n"
            "YOUR MISSION: Diagnose and fix ALL bugs so that:\n"
            "  1. The app starts without errors on port 3000\n"
            "  2. GET /health returns HTTP 200\n"
            "  3. GET /api/users returns HTTP 200 with valid JSON\n"
            "  4. GET /api/data returns HTTP 200 with valid JSON\n\n"
            "HINTS:\n"
            "  - Check config files for wrong settings\n"
            "  - Look for syntax errors that prevent startup\n"
            "  - Watch out for async/await issues\n\n"
            "Use bash commands to explore, edit files, and test.\n"
            "When you think you've fixed everything, run: npm start\n\n"
            "--- INITIAL DIRECTORY LISTING ---\n"
            f"{init_stdout}\n"
        )

        return TerminalObservation(
            stdout=task_prompt,
            stderr="",
            current_dir=self._current_dir,
            task_id="devops_sandbox",
            grader_score=0.0,
            grader_feedback="Episode started. Fix the bugs!",
            done=False,
            reward=0.0,
        )

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------
    def step(
        self,
        action: BashAction,  # type: ignore[override]
        timeout_s: Optional[float] = None,
        **kwargs: Any,
    ) -> TerminalObservation:
        """Execute the agent's bash command, run grader, return observation."""
        self._state.step_count += 1

        if not self._container_running:
            return TerminalObservation(
                stdout="",
                stderr="ERROR: Container is not running. Call reset() first.",
                current_dir=self._current_dir,
                task_id="devops_sandbox",
                grader_score=0.0,
                grader_feedback="Container not running.",
                done=True,
                reward=0.0,
            )

        # Execute the command
        command = action.command.strip()
        if not command:
            return TerminalObservation(
                stdout="",
                stderr="Empty command. Please provide a bash command.",
                current_dir=self._current_dir,
                task_id="devops_sandbox",
                grader_score=self._last_score,
                grader_feedback="No command executed.",
                done=False,
                reward=self._last_score,
            )

        try:
            timeout = timeout_s or 30.0
            stdout, stderr = self._docker_exec_split(command, timeout=timeout)
        except Exception as e:
            stdout, stderr = "", f"Command execution error: {e}"

        # Run the grader
        score, feedback = self._grade()
        self._last_score = score

        episode_done = (score >= 1.0) or (self._state.step_count >= MAX_STEPS)

        return TerminalObservation(
            stdout=stdout,
            stderr=stderr,
            current_dir=self._current_dir,
            task_id="devops_sandbox",
            grader_score=score,
            grader_feedback=feedback,
            done=episode_done,
            reward=score,
        )

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    @property
    def state(self) -> State:
        return self._state

    # ------------------------------------------------------------------
    # close
    # ------------------------------------------------------------------
    def close(self) -> None:
        self._cleanup_container()

    # ==================================================================
    #  GRADER — partial reward (0.0 → 1.0)
    #  The grader script is injected as a file into the container at
    #  reset() time, then executed via `bash /tmp/grader.sh` to avoid
    #  Windows subprocess escaping issues with complex bash scripts.
    # ==================================================================
    def _inject_grader_script(self) -> None:
        """Write the grader bash script into the container as /tmp/grader.sh."""
        # Use a heredoc via docker exec to write the file
        # We write it line-by-line to avoid any escaping issues
        lines = [
            '#!/bin/bash',
            'set -m',
            '',
            'pkill -f "node server.js" 2>/dev/null',
            'sleep 0.5',
            '',
            'cd /app',
            'node server.js > /tmp/node.log 2>&1 &',
            'NODE_PID=$!',
            '',
            'for i in 1 2 3 4; do',
            '  sleep 1',
            '  if curl -s http://localhost:3000/health > /dev/null 2>&1; then',
            '    break',
            '  fi',
            'done',
            '',
            'STARTUP_LOG=$(cat /tmp/node.log 2>/dev/null)',
            '',
            "HEALTH_CODE=$(curl -s -o /tmp/health.json -w '%{http_code}' http://localhost:3000/health 2>/dev/null)",
            "USERS_CODE=$(curl -s -o /tmp/users.json -w '%{http_code}' http://localhost:3000/api/users 2>/dev/null)",
            "DATA_CODE=$(curl -s -o /tmp/data.json -w '%{http_code}' http://localhost:3000/api/data 2>/dev/null)",
            'USERS_BODY=$(cat /tmp/users.json 2>/dev/null)',
            'DATA_BODY=$(cat /tmp/data.json 2>/dev/null)',
            '',
            'kill $NODE_PID 2>/dev/null',
            'wait $NODE_PID 2>/dev/null',
            '',
            'echo "GRADER_STARTUP_LOG:${STARTUP_LOG}"',
            'echo "GRADER_HEALTH_CODE:${HEALTH_CODE}"',
            'echo "GRADER_USERS_CODE:${USERS_CODE}"',
            'echo "GRADER_DATA_CODE:${DATA_CODE}"',
            'echo "GRADER_USERS_BODY:${USERS_BODY}"',
            'echo "GRADER_DATA_BODY:${DATA_BODY}"',
        ]
        script_content = '\n'.join(lines) + '\n'

        # Write via docker cp using a temp file on the host
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.sh', delete=False, newline='\n'
        ) as f:
            f.write(script_content)
            tmp_path = f.name

        try:
            subprocess.run(
                ["docker", "cp", tmp_path, f"{self._container_name}:/tmp/grader.sh"],
                check=True,
                capture_output=True,
                timeout=10,
            )
            self._docker_exec("chmod +x /tmp/grader.sh")
        finally:
            os.unlink(tmp_path)

    def _grade(self) -> tuple:
        """
        Run the grader script inside the container.
        Returns (score: float, feedback: str).
        """
        score = 0.0
        feedback_parts = []

        try:
            raw = self._docker_exec("bash /tmp/grader.sh", timeout=20.0)

            # Parse structured output
            results = {}
            for line in raw.splitlines():
                if line.startswith("GRADER_"):
                    key, _, value = line.partition(":")
                    results[key] = value.strip()

            startup_log = results.get("GRADER_STARTUP_LOG", "")
            health_code = results.get("GRADER_HEALTH_CODE", "000")
            users_code = results.get("GRADER_USERS_CODE", "000")
            data_code = results.get("GRADER_DATA_CODE", "000")
            users_body = results.get("GRADER_USERS_BODY", "")
            data_body = results.get("GRADER_DATA_BODY", "")

            # --- Check 1: App starts on correct port ---
            has_syntax_error = "SyntaxError" in startup_log
            has_crash = (has_syntax_error
                         or "Cannot find module" in startup_log
                         or "ReferenceError" in startup_log)
            app_listening = f"Server running on port {EXPECTED_PORT}" in startup_log

            if has_crash and not app_listening:
                feedback_parts.append(f"✗ App crashes on startup")
                if has_syntax_error:
                    feedback_parts.append("(SyntaxError detected)")
                return (score, " | ".join(feedback_parts))

            if app_listening:
                score += 0.35
                feedback_parts.append("✓ App starts on port 3000 (+0.35)")
            else:
                feedback_parts.append("✗ App not listening on port 3000")
                return (score, " | ".join(feedback_parts))

            # --- Check 2: /health ---
            if health_code == "200":
                score += 0.10
                feedback_parts.append("✓ /health returns 200 (+0.10)")
            else:
                feedback_parts.append(f"✗ /health returned {health_code}")

            # --- Check 3: /api/users ---
            if users_code == "200":
                if '"users"' in users_body:
                    score += 0.15
                    feedback_parts.append("✓ /api/users returns valid JSON (+0.15)")
                else:
                    score += 0.05
                    feedback_parts.append("~ /api/users 200 but bad body (+0.05)")
            else:
                feedback_parts.append(f"✗ /api/users returned {users_code}")

            # --- Check 4: /api/data ---
            if data_code == "200":
                if '"records"' in data_body:
                    score += 0.25
                    feedback_parts.append("✓ /api/data returns valid JSON (+0.25)")
                else:
                    score += 0.05
                    feedback_parts.append("~ /api/data 200 but bad body (+0.05)")
            else:
                feedback_parts.append(f"✗ /api/data returned {data_code}")

            # --- Check 5: all endpoints correct ---
            if score >= 0.85:
                score = min(score + 0.15, 1.0)
                feedback_parts.append("✓ All endpoints healthy — FULL SCORE (+0.15)")

        except Exception as exc:
            logger.exception("Grader error")
            feedback_parts.append(f"Grader error (score preserved): {exc}")

        score = round(min(max(score, 0.0), 1.0), 2)
        return (score, " | ".join(feedback_parts))

    # ==================================================================
    #  DOCKER HELPERS
    # ==================================================================
    def _build_image(self) -> None:
        """Build the sandbox Docker image from simulated_app/."""
        try:
            logger.info("Building Docker image %s …", IMAGE_NAME)
            subprocess.run(
                ["docker", "build", "-t", IMAGE_NAME, "."],
                cwd=str(SIMULATED_APP_DIR),
                check=True,
                capture_output=True,
                timeout=120,
            )
            logger.info("Docker image built successfully.")
        except subprocess.CalledProcessError as e:
            logger.error("Docker build failed: %s", e.stderr.decode(errors="replace"))
            raise RuntimeError(f"Docker build failed: {e.stderr.decode(errors='replace')}") from e
        except FileNotFoundError:
            raise RuntimeError(
                "Docker CLI not found. Ensure Docker is installed and on PATH."
            )

    def _start_container(self) -> None:
        """Run the sandbox container in detached mode."""
        try:
            # Remove stale container with same name
            subprocess.run(
                ["docker", "rm", "-f", self._container_name],
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                [
                    "docker", "run", "-d",
                    "--init",
                    "--name", self._container_name,
                    IMAGE_NAME,
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            self._container_running = True
            logger.info("Container %s started.", self._container_name)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to start container: {e.stderr.decode(errors='replace')}"
            ) from e

    def _docker_exec(self, cmd: str, timeout: float = 30.0) -> str:
        """Execute a command inside the running container and return combined output."""
        try:
            result = subprocess.run(
                ["docker", "exec", self._container_name, "bash", "-c", cmd],
                capture_output=True,
                timeout=timeout,
            )
            out = result.stdout.decode(errors="replace")
            err = result.stderr.decode(errors="replace")
            return (out + err).strip()
        except subprocess.TimeoutExpired:
            return "[command timed out]"
        except Exception as e:
            return f"[docker exec error: {e}]"

    def _docker_exec_split(self, cmd: str, timeout: float = 30.0) -> tuple:
        """Execute command; return (stdout, stderr) separately."""
        try:
            result = subprocess.run(
                ["docker", "exec", self._container_name, "bash", "-c", cmd],
                capture_output=True,
                timeout=timeout,
            )
            return (
                result.stdout.decode(errors="replace"),
                result.stderr.decode(errors="replace"),
            )
        except subprocess.TimeoutExpired:
            return ("", "[command timed out]")
        except Exception as e:
            return ("", f"[docker exec error: {e}]")

    def _cleanup_container(self) -> None:
        """Stop and remove the container if it exists."""
        if self._container_name:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self._container_name],
                    capture_output=True,
                    timeout=15,
                )
                logger.info("Container %s removed.", self._container_name)
            except Exception:
                pass
        self._container_running = False
        self._container_name = None

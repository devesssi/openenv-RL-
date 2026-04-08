# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Self-Healing DevOps Sandbox — Environment Implementation.

Runs entirely natively on the host filesystem (Hugging Face Spaces compatible).
The RL agent executes bash commands to diagnose and fix 3 bugs via direct subprocesses.
"""

import logging
import os
import shutil
import subprocess
import sys
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
EXPECTED_PORT = 3000          # The port the fixed app should listen on
MAX_STEPS = 50                # Episode budget
SIMULATED_APP_DIR = Path(__file__).resolve().parent.parent / "simulated_app"

class DevOpsSandbox(Environment):
    """
    RL environment: fix a broken Node.js backend.
    No longer uses Docker (Docker-in-Docker is unsupported in HF Spaces).
    Instead, uses native subprocess.run() in a reset /app/ directory.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = False

    def __init__(self):
        super().__init__()
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._current_dir: str = "/app"
        self._last_score: float = 0.0
        
        # When running on Windows locally, `/app` and `/app_backup` don't exist naturally,
        # so we will use absolute paths mapped to our repo if they aren't at root.
        # But for HF Space (Linux), /app will be at root.
        if sys.platform == "win32":
            # For Windows local dev, use safe paths inside the workspace
            workspace = Path(__file__).resolve().parent.parent
            self._app_dir = str(workspace / ".app_sandbox")
            self._app_backup_dir = str(SIMULATED_APP_DIR)
            self._tmp_dir = str(workspace / ".tmp")
            os.makedirs(self._tmp_dir, exist_ok=True)
            self._current_dir = self._app_dir
        else:
            # For Hugging Face Spaces (Linux)
            self._app_dir = "/app"
            self._app_backup_dir = "/app_backup"
            self._tmp_dir = "/tmp"
            self._current_dir = "/app"

    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs: Any,
    ) -> TerminalObservation:
        """Reset the environment state by copying the backup to the working dir."""
        eid = episode_id or str(uuid4())
        self._state = State(episode_id=eid, step_count=0)
        self._last_score = 0.0
        self._current_dir = self._app_dir

        self._reset_filesystem()
        self._inject_grader_script()

        # Gather initial observation
        init_stdout = self._exec_cmd(f"ls -la {self._app_dir} && echo '---' && cat {os.path.join(self._app_dir, 'config.json')}")

        task_prompt = (
            "=== SELF-HEALING DEVOPS SANDBOX ===\n"
            f"You have been dropped into a container with a broken Node.js Express backend in {self._app_dir}.\n\n"
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

    def step(
        self,
        action: BashAction,  # type: ignore[override]
        timeout_s: Optional[float] = None,
        **kwargs: Any,
    ) -> TerminalObservation:
        """Execute the agent's command natively, run grader, return observation."""
        self._state.step_count += 1

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

        # Handle 'cd' commands manually since subprocess run is transient
        if command.startswith("cd "):
            target = command[3:].strip()
            # Handle standard cd edge cases
            if target == "" or target == "~":
                # Assuming /app is home for this exercise
                new_dir = self._app_dir
            elif target.startswith("/"):
                new_dir = os.path.normpath(target)
            else:
                new_dir = os.path.normpath(os.path.join(self._current_dir, target))
            
            if os.path.isdir(new_dir):
                self._current_dir = new_dir
                stdout, stderr = "", ""
            else:
                stdout, stderr = "", f"bash: cd: {target}: No such file or directory"
                
            # Run the grader anyway, even if just a cd
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

        # Execute normal command
        try:
            timeout = timeout_s or 30.0
            stdout, stderr = self._exec_cmd_split(command, timeout=timeout)
        except Exception as e:
            stdout, stderr = "", f"Command execution error: {e}"

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

    @property
    def state(self) -> State:
        return self._state

    def close(self) -> None:
        # pkill node servers that we might have spawned during the session
        self._exec_cmd("pkill -f 'node server.js'")

    # ==================================================================
    #  FILESYSTEM & EXECUTION HELPERS
    # ==================================================================
    def _reset_filesystem(self) -> None:
        """Replace the current working /app with the pristine /app_backup."""
        # Ensure we don't accidentally wipe out the whole host on windows if paths are wrong
        os.makedirs(self._app_dir, exist_ok=True)
        
        # Clean contents of /app instead of deleting /app itself
        for item in os.listdir(self._app_dir):
            item_path = os.path.join(self._app_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path, ignore_errors=True)
            else:
                try:
                    os.remove(item_path)
                except OSError:
                    pass
            
        # Copy from backup to app dir
        if os.path.exists(self._app_backup_dir):
            for item in os.listdir(self._app_backup_dir):
                s = os.path.join(self._app_backup_dir, item)
                d = os.path.join(self._app_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
        else:
            logger.warning(f"Backup directory {self._app_backup_dir} not found. Ensure Dockerfile copied simulated_app here.")

    def _exec_cmd(self, cmd: str, timeout: float = 30.0) -> str:
        """Execute command natively; return combined output."""
        stdout, stderr = self._exec_cmd_split(cmd, timeout)
        return (stdout + "\n" + stderr).strip()

    def _exec_cmd_split(self, cmd: str, timeout: float = 30.0) -> tuple:
        """Execute command natively; return (stdout, stderr)."""
        kwargs = {
            "cwd": self._current_dir,
            "shell": True,
            "capture_output": True,
            "timeout": timeout,
        }
        
        # Hugging Face space requires POSIX bash, windows uses powershell/cmd
        if sys.platform != "win32":
            kwargs["executable"] = "/bin/bash"

        try:
            result = subprocess.run(cmd, **kwargs)
            return (
                result.stdout.decode(errors="replace"),
                result.stderr.decode(errors="replace"),
            )
        except subprocess.TimeoutExpired:
            return ("", "[command timed out]")
        except Exception as e:
            return ("", f"[exec error: {e}]")

    # ==================================================================
    #  GRADER
    # ==================================================================
    def _inject_grader_script(self) -> None:
        self.grader_path = os.path.join(self._tmp_dir, "grader.sh")
        lines = [
            '#!/bin/bash',
            'set -m',
            '',
            'pkill -f "node server.js" 2>/dev/null',
            'sleep 0.5',
            '',
            f'cd {self._app_dir}',
            f'node server.js > {self._tmp_dir}/node.log 2>&1 &',
            'NODE_PID=$!',
            '',
            'for i in 1 2 3 4; do',
            '  sleep 1',
            '  if curl -s http://localhost:3000/health > /dev/null 2>&1; then',
            '    break',
            '  fi',
            'done',
            '',
            f'STARTUP_LOG=$(cat {self._tmp_dir}/node.log 2>/dev/null)',
            '',
            f"HEALTH_CODE=$(curl -s -o {self._tmp_dir}/health.json -w '%{{http_code}}' http://localhost:3000/health 2>/dev/null)",
            f"USERS_CODE=$(curl -s -o {self._tmp_dir}/users.json -w '%{{http_code}}' http://localhost:3000/api/users 2>/dev/null)",
            f"DATA_CODE=$(curl -s -o {self._tmp_dir}/data.json -w '%{{http_code}}' http://localhost:3000/api/data 2>/dev/null)",
            f'USERS_BODY=$(cat {self._tmp_dir}/users.json 2>/dev/null)',
            f'DATA_BODY=$(cat {self._tmp_dir}/data.json 2>/dev/null)',
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
        with open(self.grader_path, "w", newline='\n') as f:
            f.write(script_content)
            
        if sys.platform != "win32":
            subprocess.run(["chmod", "+x", self.grader_path])

    def _grade(self) -> tuple:
        score = 0.0
        feedback_parts = []

        try:
            if sys.platform == "win32":
                # We use bash via wsl or bash.exe on Windows if we can, 
                # but if not we might fail grading natively on Windows unless Git Bash is installed.
                raw = self._exec_cmd(f"bash {self.grader_path}", timeout=20.0)
            else:
                raw = self._exec_cmd(f"/bin/bash {self.grader_path}", timeout=20.0)

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

            if health_code == "200":
                score += 0.10
                feedback_parts.append("✓ /health returns 200 (+0.10)")
            else:
                feedback_parts.append(f"✗ /health returned {health_code}")

            if users_code == "200":
                if '"users"' in users_body:
                    score += 0.15
                    feedback_parts.append("✓ /api/users returns valid JSON (+0.15)")
                else:
                    score += 0.05
                    feedback_parts.append("~ /api/users 200 but bad body (+0.05)")
            else:
                feedback_parts.append(f"✗ /api/users returned {users_code}")

            if data_code == "200":
                if '"records"' in data_body:
                    score += 0.25
                    feedback_parts.append("✓ /api/data returns valid JSON (+0.25)")
                else:
                    score += 0.05
                    feedback_parts.append("~ /api/data 200 but bad body (+0.05)")
            else:
                feedback_parts.append(f"✗ /api/data returned {data_code}")

            if score >= 0.85:
                score = min(score + 0.15, 1.0)
                feedback_parts.append("✓ All endpoints healthy — FULL SCORE (+0.15)")

        except Exception as exc:
            logger.exception("Grader error")
            feedback_parts.append(f"Grader error (score preserved): {exc}")

        score = round(min(max(score, 0.0), 1.0), 2)
        return (score, " | ".join(feedback_parts))

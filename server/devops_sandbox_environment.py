# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Self-Healing DevOps Sandbox — Environment Implementation.

An RL environment where an AI agent is dropped into a broken Node.js Express
backend and must use bash commands to diagnose and fix production-like bugs.

Runs entirely natively on the host filesystem (Hugging Face Spaces compatible).
The agent executes bash commands to diagnose and fix 3 bugs via direct subprocesses.

Bugs injected:
  1. config.json — wrong port (9999 instead of 3000)
  2. routes/users.js — missing closing parenthesis (SyntaxError)
  3. routes/data.js — missing `await` on async DB call (broken response)

Grading:
  - File-level verification: did the agent edit the correct file?
  - HTTP endpoint testing: does the app start and respond correctly?
  - Partial credit: smooth reward progression from 0.01 to 0.99
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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

# Files that contain bugs — used for file-change tracking
BUG_FILES = {
    "config.json": "port",
    "routes/users.js": "syntax",
    "routes/data.js": "await",
}


class DevOpsSandbox(Environment):
    """
    RL environment: fix a broken Node.js backend.

    The agent operates in a Linux filesystem with a broken Express.js app.
    It must use bash commands (ls, cat, sed, grep, etc.) to find and fix bugs.

    Features:
      - 3 difficulty levels (easy/medium/hard) with progressive bug counts
      - File-change tracking for granular reward shaping
      - HTTP endpoint verification via automated grader
      - Rich metadata in observations (files_modified, bugs_found, etc.)
      - All scores strictly within (0, 1) per OpenEnv spec
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = False

    def __init__(self):
        super().__init__()
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._current_dir: str = "/app"
        self._last_score: float = 0.01
        self._current_task: str = "hard"
        self._file_hashes: Dict[str, str] = {}
        self._files_modified: List[str] = []
        self._commands_history: List[str] = []

        # Platform-specific paths
        if sys.platform == "win32":
            workspace = Path(__file__).resolve().parent.parent
            self._app_dir = str(workspace / ".app_sandbox")
            self._app_backup_dir = str(SIMULATED_APP_DIR)
            self._tmp_dir = str(workspace / ".tmp")
            os.makedirs(self._tmp_dir, exist_ok=True)
            self._current_dir = self._app_dir
        else:
            self._app_dir = "/app"
            self._app_backup_dir = "/app_backup"
            self._tmp_dir = "/tmp"
            self._current_dir = "/app"

    # ==================================================================
    #  RESET
    # ==================================================================
    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs: Any,
    ) -> TerminalObservation:
        """Reset the environment state for a new episode.

        Args:
            seed: Optional random seed (unused, bugs are deterministic).
            episode_id: Optional episode identifier.
            **kwargs: Must include task_name='easy'|'medium'|'hard'.

        Returns:
            TerminalObservation with the task prompt and initial state.
        """
        eid = episode_id or str(uuid4())
        self._state = State(episode_id=eid, step_count=0)
        self._last_score = 0.01
        self._current_dir = self._app_dir
        self._current_task = kwargs.get("task_name", "hard")
        self._files_modified = []
        self._commands_history = []

        self._reset_filesystem()
        self._snapshot_file_hashes()
        self._inject_grader_script()

        # Gather initial observation
        init_stdout = self._exec_cmd(
            f"ls -la {self._app_dir} && echo '---' && cat {os.path.join(self._app_dir, 'config.json')}"
        )

        task_prompt = self._build_task_prompt(init_stdout)

        return TerminalObservation(
            stdout=task_prompt,
            stderr="",
            current_dir=self._current_dir,
            task_id=self._current_task,
            grader_score=0.01,
            grader_feedback="Episode started. Diagnose and fix the bugs!",
            done=False,
            reward=0.01,
            metadata={
                "episode_id": eid,
                "task": self._current_task,
                "max_steps": MAX_STEPS,
                "bugs_total": self._bugs_for_task(),
                "bugs_found": 0,
                "files_modified": [],
            },
        )

    # ==================================================================
    #  STEP
    # ==================================================================
    def step(
        self,
        action: BashAction,
        timeout_s: Optional[float] = None,
        **kwargs: Any,
    ) -> TerminalObservation:
        """Execute the agent's command, run the grader, return observation.

        Args:
            action: BashAction containing the command string.
            timeout_s: Optional timeout for command execution.

        Returns:
            TerminalObservation with command output, score, and metadata.
        """
        self._state.step_count += 1
        command = action.command.strip()

        if not command:
            return TerminalObservation(
                stdout="",
                stderr="Empty command. Please provide a bash command.",
                current_dir=self._current_dir,
                task_id=self._current_task,
                grader_score=self._last_score,
                grader_feedback="No command executed.",
                done=False,
                reward=0.01,
                metadata=self._build_metadata(),
            )

        self._commands_history.append(command)

        # Handle 'cd' commands manually (subprocess is transient)
        if command.startswith("cd "):
            return self._handle_cd(command)

        # Execute normal command
        try:
            timeout = timeout_s or 30.0
            stdout, stderr = self._exec_cmd_split(command, timeout=timeout)
        except Exception as e:
            stdout, stderr = "", f"Command execution error: {e}"

        # Check for file modifications
        self._detect_file_changes()

        # Grade the current state
        score, feedback = self._grade()
        reward = max(0.01, score - self._last_score)
        self._last_score = score
        episode_done = (score >= 0.99) or (self._state.step_count >= MAX_STEPS)

        return TerminalObservation(
            stdout=stdout,
            stderr=stderr,
            current_dir=self._current_dir,
            task_id=self._current_task,
            grader_score=score,
            grader_feedback=feedback,
            done=episode_done,
            reward=reward,
            metadata=self._build_metadata(),
        )

    @property
    def state(self) -> State:
        return self._state

    def close(self) -> None:
        """Clean up: kill any Node.js servers spawned during the episode."""
        self._exec_cmd("pkill -f 'node server.js'")

    # ==================================================================
    #  TASK PROMPTS
    # ==================================================================
    def _build_task_prompt(self, init_stdout: str) -> str:
        """Build the task prompt based on the current difficulty level."""
        base = (
            "=== SELF-HEALING DEVOPS SANDBOX ===\n"
            f"You have been dropped into a container with a broken Node.js "
            f"Express backend in {self._app_dir}.\n\n"
        )

        if self._current_task == "easy":
            mission = (
                "YOUR MISSION [EASY — 1 bug]:\n"
                "  Fix the port configuration so that:\n"
                "  1. The app starts without errors on port 3000\n"
                "  2. GET /health returns HTTP 200\n\n"
                "HINTS:\n"
                "  - Check config.json for wrong settings\n"
            )
        elif self._current_task == "medium":
            mission = (
                "YOUR MISSION [MEDIUM — 2 bugs]:\n"
                "  Fix BOTH bugs so that:\n"
                "  1. The app starts without errors on port 3000\n"
                "  2. GET /health returns HTTP 200\n"
                "  3. GET /api/users returns HTTP 200 with valid JSON\n\n"
                "HINTS:\n"
                "  - Check config.json for wrong settings\n"
                "  - Look for syntax errors in routes/users.js\n"
            )
        else:
            mission = (
                "YOUR MISSION [HARD — 3 bugs]:\n"
                "  Fix ALL bugs so that:\n"
                "  1. The app starts without errors on port 3000\n"
                "  2. GET /health returns HTTP 200\n"
                "  3. GET /api/users returns HTTP 200 with valid JSON\n"
                "  4. GET /api/data returns HTTP 200 with valid JSON\n\n"
                "HINTS:\n"
                "  - Check config files for wrong settings\n"
                "  - Look for syntax errors that prevent startup\n"
                "  - Watch out for async/await issues\n"
            )

        return (
            base + mission +
            "\nUse bash commands to explore, edit files, and test.\n"
            "When you think you've fixed everything, run: npm start\n\n"
            f"--- INITIAL DIRECTORY LISTING ---\n{init_stdout}\n"
        )

    def _bugs_for_task(self) -> int:
        """Return the number of bugs for the current task difficulty."""
        return {"easy": 1, "medium": 2, "hard": 3}.get(self._current_task, 3)

    # ==================================================================
    #  CD HANDLER
    # ==================================================================
    def _handle_cd(self, command: str) -> TerminalObservation:
        """Handle cd commands manually since subprocess.run is transient."""
        target = command[3:].strip()
        if target == "" or target == "~":
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

        score, feedback = self._grade()
        reward = max(0.01, score - self._last_score)
        self._last_score = score
        episode_done = (score >= 0.99) or (self._state.step_count >= MAX_STEPS)

        return TerminalObservation(
            stdout=stdout,
            stderr=stderr,
            current_dir=self._current_dir,
            task_id=self._current_task,
            grader_score=score,
            grader_feedback=feedback,
            done=episode_done,
            reward=reward,
            metadata=self._build_metadata(),
        )

    # ==================================================================
    #  METADATA & FILE TRACKING
    # ==================================================================
    def _build_metadata(self) -> Dict[str, Any]:
        """Build rich metadata for the current observation."""
        return {
            "episode_id": self._state.episode_id,
            "step": self._state.step_count,
            "task": self._current_task,
            "max_steps": MAX_STEPS,
            "bugs_total": self._bugs_for_task(),
            "files_modified": list(self._files_modified),
            "commands_count": len(self._commands_history),
        }

    def _snapshot_file_hashes(self) -> None:
        """Take a hash snapshot of all bug-related files for change detection."""
        self._file_hashes = {}
        for relative_path in BUG_FILES:
            full_path = os.path.join(self._app_dir, relative_path)
            if os.path.isfile(full_path):
                try:
                    with open(full_path, "rb") as f:
                        self._file_hashes[relative_path] = hashlib.md5(f.read()).hexdigest()
                except OSError:
                    pass

    def _detect_file_changes(self) -> None:
        """Detect which bug files have been modified since reset."""
        for relative_path in BUG_FILES:
            if relative_path in self._files_modified:
                continue
            full_path = os.path.join(self._app_dir, relative_path)
            if os.path.isfile(full_path):
                try:
                    with open(full_path, "rb") as f:
                        current_hash = hashlib.md5(f.read()).hexdigest()
                    if current_hash != self._file_hashes.get(relative_path):
                        self._files_modified.append(relative_path)
                except OSError:
                    pass

    # ==================================================================
    #  FILESYSTEM & EXECUTION HELPERS
    # ==================================================================
    def _reset_filesystem(self) -> None:
        """Replace the working /app with the pristine backup."""
        os.makedirs(self._app_dir, exist_ok=True)

        # Clean contents of /app
        for item in os.listdir(self._app_dir):
            item_path = os.path.join(self._app_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path, ignore_errors=True)
            else:
                try:
                    os.remove(item_path)
                except OSError:
                    pass

        # Copy from backup
        if os.path.exists(self._app_backup_dir):
            for item in os.listdir(self._app_backup_dir):
                s = os.path.join(self._app_backup_dir, item)
                d = os.path.join(self._app_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
        else:
            logger.warning(
                f"Backup directory {self._app_backup_dir} not found. "
                "Ensure Dockerfile copied simulated_app here."
            )

    def _exec_cmd(self, cmd: str, timeout: float = 30.0) -> str:
        """Execute command natively; return combined output."""
        stdout, stderr = self._exec_cmd_split(cmd, timeout)
        return (stdout + "\n" + stderr).strip()

    def _exec_cmd_split(self, cmd: str, timeout: float = 30.0) -> Tuple[str, str]:
        """Execute command natively; return (stdout, stderr)."""
        kwargs = {
            "cwd": self._current_dir,
            "shell": True,
            "capture_output": True,
            "timeout": timeout,
        }
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
        """Write the grader bash script that tests the Node.js app endpoints."""
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
            '# Wait for server to start (up to 4 seconds)',
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

    def _grade(self) -> Tuple[float, str]:
        """Run the grader and return (score, feedback).

        Scoring breakdown:
          - File-level: +0.05 per correctly modified bug file
          - App starts on port 3000: +0.30
          - /health returns 200: +0.10
          - /api/users returns valid JSON: +0.15
          - /api/data returns valid JSON: +0.20
          - All endpoints pass: +0.05 bonus

        Total raw score is then scaled by task difficulty and clamped to (0, 1).
        """
        score = 0.0
        feedback_parts = []

        # --- Phase 1: File-change rewards (micro-rewards for finding bugs) ---
        files_to_check = {
            "easy": ["config.json"],
            "medium": ["config.json", "routes/users.js"],
            "hard": ["config.json", "routes/users.js", "routes/data.js"],
        }.get(self._current_task, list(BUG_FILES.keys()))

        for f in files_to_check:
            if f in self._files_modified:
                score += 0.05
                feedback_parts.append(f"✓ Modified {f} (+0.05)")

        # --- Phase 2: HTTP endpoint testing ---
        try:
            if sys.platform == "win32":
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
            has_crash = (
                has_syntax_error
                or "Cannot find module" in startup_log
                or "ReferenceError" in startup_log
            )
            app_listening = f"Server running on port {EXPECTED_PORT}" in startup_log

            if has_crash and not app_listening:
                feedback_parts.append("✗ App crashes on startup")
                if has_syntax_error:
                    feedback_parts.append("(SyntaxError detected)")
                # Fall through to clamping — NO early return
            elif not app_listening:
                feedback_parts.append("✗ App not listening on port 3000")
                # Fall through to clamping — NO early return
            else:
                # App is running — grade each endpoint
                score += 0.30
                feedback_parts.append("✓ App starts on port 3000 (+0.30)")

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
                        feedback_parts.append("~ /api/users 200 but malformed body (+0.05)")
                else:
                    feedback_parts.append(f"✗ /api/users returned {users_code}")

                if data_code == "200":
                    if '"records"' in data_body:
                        score += 0.20
                        feedback_parts.append("✓ /api/data returns valid JSON (+0.20)")
                    else:
                        score += 0.05
                        feedback_parts.append("~ /api/data 200 but malformed body (+0.05)")
                else:
                    feedback_parts.append(f"✗ /api/data returned {data_code}")

                if score >= 0.80:
                    score += 0.05
                    feedback_parts.append("✓ All endpoints healthy — bonus (+0.05)")

        except Exception as exc:
            logger.exception("Grader error")
            feedback_parts.append(f"Grader error (score preserved): {exc}")

        # --- Phase 3: Scale by difficulty and clamp ---
        if self._current_task == "easy":
            raw_target = 0.50
        elif self._current_task == "medium":
            raw_target = 0.65
        else:
            raw_target = 1.0

        final_score = min(1.0, score / raw_target)
        # Clamp strictly within (0, 1) — EVERY code path reaches here
        final_score = round(min(max(final_score, 0.01), 0.99), 2)

        return (final_score, " | ".join(feedback_parts))

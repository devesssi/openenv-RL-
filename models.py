# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Data models for the Self-Healing DevOps Sandbox Environment.

Defines the Action and Observation types used by the RL agent to interact
with a broken Node.js backend. The agent acts as a DevOps engineer, diagnosing
and fixing production-like bugs using bash commands.
"""

from typing import Any, Dict, List, Optional

from pydantic import Field

from openenv.core.env_server.types import Action, Observation


class BashAction(Action):
    """Action: a bash command to execute inside the sandbox.

    The agent sends shell commands (ls, cat, sed, grep, node, npm, etc.)
    to diagnose and repair the broken Node.js application.
    """

    command: str = Field(
        ...,
        description=(
            "The bash command to execute in the sandbox terminal "
            "(e.g., 'ls -la', 'cat server.js', "
            "'sed -i s/old/new/ file.js')."
        ),
    )


class TerminalObservation(Observation):
    """Observation returned after executing a bash command.

    Includes stdout/stderr from the command, working directory context,
    the current task identifier, grader's partial score, and episode metadata.
    """

    stdout: str = Field(
        default="",
        description="Standard output from the executed command.",
    )
    stderr: str = Field(
        default="",
        description="Standard error from the executed command, if any.",
    )
    current_dir: str = Field(
        default="/app",
        description="The current working directory inside the container.",
    )
    task_id: str = Field(
        default="devops_sandbox",
        description="Identifier for the current task scenario (easy/medium/hard).",
    )
    grader_score: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="The grader's partial reward strictly within (0, 1).",
    )
    grader_feedback: str = Field(
        default="",
        description="Human-readable feedback from the grader.",
    )
    done: bool = Field(
        default=False,
        description="Whether the episode is complete (all bugs fixed or max steps reached).",
    )
    reward: Optional[float] = Field(
        default=None,
        description="Incremental reward for this step (score delta).",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata: files_modified, commands_count, bugs_found, etc.",
    )


__all__ = ["BashAction", "TerminalObservation"]
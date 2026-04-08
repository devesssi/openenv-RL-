# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Self-Healing DevOps Sandbox Environment Client."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

from models import BashAction, TerminalObservation


class DevopsSandboxEnv(
    EnvClient[BashAction, TerminalObservation, State]
):
    """
    Client for the Self-Healing DevOps Sandbox Environment.

    Example:
        >>> with DevopsSandboxEnv(base_url="http://localhost:8000") as client:
        ...     result = client.reset()
        ...     print(result.observation.stdout)
        ...
        ...     result = client.step(BashAction(command="ls -la"))
        ...     print(result.observation.stdout)
    """

    def _step_payload(self, action: BashAction) -> Dict:
        """Convert BashAction to JSON payload for step message."""
        return {
            "command": action.command,
        }

    def _parse_result(self, payload: Dict) -> StepResult[TerminalObservation]:
        """Parse server response into StepResult[TerminalObservation]."""
        obs_data = payload.get("observation", {})
        observation = TerminalObservation(
            stdout=obs_data.get("stdout", ""),
            stderr=obs_data.get("stderr", ""),
            current_dir=obs_data.get("current_dir", "/app"),
            task_id=obs_data.get("task_id", "devops_sandbox"),
            grader_score=obs_data.get("grader_score", 0.0),
            grader_feedback=obs_data.get("grader_feedback", ""),
            done=payload.get("done", False),
            reward=payload.get("reward"),
            metadata=obs_data.get("metadata", {}),
        )

        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        """Parse server response into State object."""
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )

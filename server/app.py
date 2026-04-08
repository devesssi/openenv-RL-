# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
FastAPI application for the Self-Healing DevOps Sandbox Environment.

Endpoints:
    - POST /reset: Reset the environment (build & start container)
    - POST /step: Execute a bash command inside the container
    - GET /state: Get current environment state
    - GET /schema: Get action/observation schemas
    - WS /ws: WebSocket endpoint for persistent sessions

Usage:
    uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
"""

try:
    from openenv.core.env_server.http_server import create_app
except Exception as e:  # pragma: no cover
    raise ImportError(
        "openenv is required. Install with:\n    uv sync\n"
    ) from e

try:
    from ..models import BashAction, TerminalObservation
    from .devops_sandbox_environment import DevOpsSandbox
except (ImportError, ModuleNotFoundError):
    from models import BashAction, TerminalObservation
    from server.devops_sandbox_environment import DevOpsSandbox


# Create the app — DevOpsSandbox is passed as a class (factory mode)
app = create_app(
    DevOpsSandbox,
    BashAction,
    TerminalObservation,
    env_name="devops_sandbox",
    max_concurrent_envs=1,
)


def main(host: str = "0.0.0.0", port: int = 8000):
    """
    Entry point for direct execution.

        uv run --project . server
        python -m devops_sandbox.server.app
    """
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()

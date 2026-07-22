#!/usr/bin/env python3
"""Deploy a new backend image to the prod ECS service (ErrandBridge).

This script deliberately avoids printing the full ECS task definition because it may
contain sensitive environment variables.

It uses the AWS CLI under the hood (no boto3 dependency).

Usage:
  python3 scripts/deploy_prod_image.py \
    --cluster errandbridge-prod-cluster \
    --service errandbridge-prod-api \
    --container api \
    --image 389068786915.dkr.ecr.us-east-1.amazonaws.com/errandbridge-api:<tag>

Optional:
  --wait-stable   Wait until the service is stable
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any


def _run_aws(args: list[str]) -> str:
    env = dict(os.environ)
    env.setdefault("AWS_PAGER", "")
    # Keep output deterministic
    env.setdefault("LC_ALL", "C")

    proc = subprocess.run(
        ["aws", "--no-cli-pager", *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"aws exited {proc.returncode}")
    return proc.stdout


def _json_load(s: str) -> Any:
    return json.loads(s)


def _prune_taskdef(td: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields accepted by register-task-definition."""
    keep = [
        "family",
        "taskRoleArn",
        "executionRoleArn",
        "networkMode",
        "containerDefinitions",
        "volumes",
        "placementConstraints",
        "requiresCompatibilities",
        "cpu",
        "memory",
        "proxyConfiguration",
        "ipcMode",
        "pidMode",
        "runtimePlatform",
        "ephemeralStorage",
    ]
    return {k: td[k] for k in keep if k in td}


def _ensure_runtime_platform(td: dict[str, Any]) -> None:
    """Make the task definition explicit about the ECS/Fargate target platform.

    This repo deploys to x86_64 Linux on Fargate. Making the runtime platform
    explicit reduces ambiguity when images are built from non-Linux developer
    machines and keeps new task revisions aligned with the production service.
    """

    runtime_platform = td.get("runtimePlatform") or {}
    runtime_platform.setdefault("operatingSystemFamily", "LINUX")
    runtime_platform.setdefault("cpuArchitecture", "X86_64")
    td["runtimePlatform"] = runtime_platform


def _update_container_image(td: dict[str, Any], container_name: str, image: str) -> None:
    containers = td.get("containerDefinitions") or []
    found = False
    for c in containers:
        if c.get("name") == container_name:
            c["image"] = image
            found = True
            break
    if not found:
        raise ValueError(f"Container '{container_name}' not found in task definition")


def _wait_stable(cluster: str, service: str, timeout_s: int = 600) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        out = _run_aws(
            [
                "ecs",
                "describe-services",
                "--cluster",
                cluster,
                "--services",
                service,
                "--query",
                "services[0].{running:runningCount,desired:desiredCount,deployments:deployments[*].{status:status,rolloutState:rolloutState}}",
                "--output",
                "json",
            ]
        )
        s = _json_load(out)
        deployments = s.get("deployments") or []
        primary = next((d for d in deployments if d.get("status") == "PRIMARY"), None)
        if s.get("running") == s.get("desired") and primary and primary.get("rolloutState") == "COMPLETED":
            return
        time.sleep(10)

    raise TimeoutError("Service did not become stable within timeout")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cluster", required=True)
    ap.add_argument("--service", required=True)
    ap.add_argument("--container", default="api")
    ap.add_argument("--image", required=True)
    ap.add_argument("--wait-stable", action="store_true")

    args = ap.parse_args()

    # 1) Discover active task definition
    svc_out = _run_aws(
        [
            "ecs",
            "describe-services",
            "--cluster",
            args.cluster,
            "--services",
            args.service,
            "--query",
            "services[0].taskDefinition",
            "--output",
            "text",
        ]
    ).strip()
    if not svc_out or svc_out == "None":
        print("Could not determine active task definition", file=sys.stderr)
        return 2

    # 2) Describe task definition
    td_out = _run_aws(
        [
            "ecs",
            "describe-task-definition",
            "--task-definition",
            svc_out,
            "--query",
            "taskDefinition",
            "--output",
            "json",
        ]
    )
    td = _json_load(td_out)

    # 3) Mutate + prune
    _update_container_image(td, args.container, args.image)
    _ensure_runtime_platform(td)
    td_in = _prune_taskdef(td)

    # 4) Register new revision
    reg_out = _run_aws(
        [
            "ecs",
            "register-task-definition",
            "--cli-input-json",
            json.dumps(td_in),
            "--query",
            "taskDefinition.{arn:taskDefinitionArn,revision:revision}",
            "--output",
            "json",
        ]
    )
    reg = _json_load(reg_out)

    print(f"Registered task definition revision: {reg.get('arn')}")

    # 5) Update service
    upd_out = _run_aws(
        [
            "ecs",
            "update-service",
            "--cluster",
            args.cluster,
            "--service",
            args.service,
            "--task-definition",
            reg.get("arn"),
            "--force-new-deployment",
            "--query",
            "service.deployments[0].{status:status,rolloutState:rolloutState,taskDefinition:taskDefinition,updatedAt:updatedAt}",
            "--output",
            "json",
        ]
    )
    print(f"Update started: {upd_out.strip()}")

    if args.wait_stable:
        _wait_stable(args.cluster, args.service)
        print("Service is stable")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

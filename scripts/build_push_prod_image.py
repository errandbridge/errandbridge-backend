#!/usr/bin/env python3
"""Build and push a production backend image for ECS/Fargate.

Best practice for this repo is to publish linux/amd64 images because the
production ECS service runs on x86_64 Fargate. Building a local image from an
Apple Silicon Mac without an explicit platform can produce an arm64-only image
that ECS cannot pull.

Usage:
  python3 scripts/build_push_prod_image.py \
    --repo 389068786915.dkr.ecr.us-east-1.amazonaws.com/errandbridge-prod-api

Optional:
  --tag authsafe-20260429-001716
  --platform linux/amd64
  --context .
  --dockerfile Dockerfile
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def _default_tag() -> str:
    return f"prod-{dt.datetime.now(dt.UTC).strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="Full ECR repository URI without tag")
    ap.add_argument("--tag", default=_default_tag(), help="Image tag to publish")
    ap.add_argument("--platform", default="linux/amd64", help="Target image platform")
    ap.add_argument("--context", default=".", help="Docker build context")
    ap.add_argument("--dockerfile", default="Dockerfile", help="Path to Dockerfile")
    args = ap.parse_args()

    image = f"{args.repo}:{args.tag}"
    print(image)
    sys.stdout.flush()

    _run(["docker", "buildx", "version"])
    _run(
        [
            "docker",
            "buildx",
            "build",
            "--platform",
            args.platform,
            "-f",
            args.dockerfile,
            "-t",
            image,
            "--push",
            args.context,
        ]
    )

    print(f"Published image: {image}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

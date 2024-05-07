#!/usr/bin/env python3
# Use rsync to create stub testing files locally

import subprocess
import argparse
from pathlib import Path


def main(upstream: str, dist: Path) -> None:
    p = subprocess.run(
        ["rsync", "--no-motd", "-r", "--list-only", upstream],
        stdout=subprocess.PIPE,
        text=True,
    )
    if p.returncode != 0:
        print("Failed to run rsync")
        exit(1)
    for line in p.stdout.splitlines():
        line = line.strip()
        splitted = line.split(maxsplit=5)
        perm = splitted[0]
        path = splitted[-1]
        is_dir = perm.startswith("d")
        if is_dir:
            dist.joinpath(path).mkdir(parents=True, exist_ok=True)
        else:
            dist.joinpath(path).touch()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate stub files for testing rsync"
    )
    parser.add_argument(
        "upstream", type=str, help="Upstream URL, like rsync://example.com/ubuntu/"
    )
    parser.add_argument(
        "--dist",
        type=Path,
        default=Path("."),
        help="Path to save stub files, defaults to current directory",
    )
    args = parser.parse_args()

    main(args.upstream, args.dist)

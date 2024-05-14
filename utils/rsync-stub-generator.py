#!/usr/bin/env python3
# Use rsync to create stub testing files locally

import subprocess
import argparse
from pathlib import Path


def main(upstream: str, dist: Path) -> None:
    p = subprocess.run(
        ["rsync", "-a", "--no-motd", "-r", "--list-only", upstream],
        stdout=subprocess.PIPE,
        text=True,
    )
    if p.returncode != 0:
        print("Failed to run rsync")
        exit(1)
    for line in p.stdout.splitlines():
        line = line.strip()
        splitted = line.split(maxsplit=4)
        perm = splitted[0]
        path = splitted[-1]
        if perm.startswith("d"):
            dist.joinpath(path).mkdir(parents=True, exist_ok=True)
        elif perm.startswith("l"):
            # well that's a bit tricky
            path = path.split(" -> ", maxsplit=1)
            target = path[1]
            symlink = dist.joinpath(path[0])
            try:
                symlink.symlink_to(target)
            except FileExistsError:
                # check if the symlink is the same as the target
                if symlink.is_symlink():
                    symlink_target = symlink.readlink()
                    if str(symlink_target) == target:
                        continue
                    else:
                        print(symlink_target, target)
                print(
                    "Symlink already exists -- maybe you should nuke the dist directory first?"
                )
                print("Symlink:", symlink)
                print("Target:", target)
                exit(-1)
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

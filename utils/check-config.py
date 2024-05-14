#!/usr/bin/env python3
# check the sanity of all config files under includes/

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parents[1]))
import genisolist

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <include_path>")
        sys.exit(1)
    inc_dir = Path(sys.argv[1])

    assert inc_dir.is_dir(), f"{inc_dir} is not a directory"

    all_sections = dict()

    for ini in inc_dir.glob("**/*.ini"):
        print(f"Checking {ini}...")
        sections = genisolist.process_ini(ini)
        # each file should be able to work as a standalone config
        genisolist.gen_from_sections(sections, strict=True)
        for s in sections:
            assert (
                s not in all_sections
            ), f"Duplicated section {s} in {ini}, previously defined in {all_sections[s]['src']}"
            sections[s]["src"] = ini
        all_sections.update(sections)

    # check the whole config
    print(f"Checking merged config...")
    genisolist.gen_from_sections(all_sections, strict=True)

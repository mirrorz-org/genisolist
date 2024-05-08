#!/usr/bin/env python3
# Reference implementation of genisolist

from collections import defaultdict
from configparser import ConfigParser
import logging
from argparse import ArgumentParser
from pathlib import Path
import sys
import os
import re
import json
from urllib.parse import urljoin

from version import LooseVersion

logger = logging.getLogger(__name__)


def get_platform_priority(platform: str) -> int:
    """
    Get the priority of the platform (arch). Higher is more preferred.
    """

    platform = platform.lower()
    if platform in ["amd64", "x86_64", "64bit"]:
        return 100
    elif platform in ["arm64", "aarch64", "arm64v8"]:
        return 95
    elif platform in ["riscv64"]:
        return 95
    elif platform in ["loongson2f", "loongson3"]:
        return 95
    elif platform in ["i386", "i486", "i586", "i686", "x86", "32bit"]:
        return 90
    elif platform in ["arm32", "armhf", "armv7"]:
        return 85
    else:
        return 0


def render(template: str, result: re.Match) -> str:
    """
    Render a template string with matched result.

    A template string contains things like $1, $2, etc. which are replaced with matched groups.

    $0 is also supported, though usually it should not be used.

    BUG: This function does not support $n which n >= 10.
    """

    for i in range(len(result.groups()) + 1):
        grp = result.group(i)
        if f"${i}" in template:
            assert grp is not None, f"Group {i} is not matched with template {template}"
            template = template.replace(f"${i}", grp)
    return template


def render_list(template: str, result: re.Match) -> list:
    """
    Render a template string with matched result, but return a list.

    This function would expect input like "$1 $2 $3" and return ["$1", "$2", "$3"] with replaced values.
    Substrings not starting with "$" would be kept as is in the list
    """

    l = []
    for item in template.split():
        if not item.startswith("$"):
            l.append(item)
        else:
            grp = result.group(int(item[1:]))
            assert (
                grp is not None
            ), f"Group {int(item[1:])} is not matched with template {template}"
            l.append(grp)
    return l


def parse_section(section: dict, root: Path) -> list:
    """
    Parse a distribution section and return a list of sorted file items.

    A section is expected to have following schema:

    {
        "distro": str,
        "listvers": Optional[int] (defaults to 0xff, or 255),
        "location": str,
        "pattern": str,
        "version": str,
        "type": Optional[str] (defaults to ""),
        "platform": str,
        "category": Optional[str] (treats as "os" if not present),
        "key_by": Optional[str] (defaults to "" -- no keying),
        "sort_by": Optional[str] (defaults to sort by version, platform and type),
        "nosort": Optional[bool] (defaults to False),
    }

    Exception could be raised if any of the required fields is missing.

    A "file item" should at least have following schema:

    {
        "path": Path,
        "category": str,
        "version": str,
        "platform": str,
        "type": str,
    }
    """

    if "location" in section:
        locations = [section["location"]]
    else:
        locations = []
        i = 0
        while True:
            location = section.get(f"location_{i}", None)
            if location is None:
                break
            locations.append(location)
            i += 1
    assert locations, "No location found in section"

    pattern = section.get("pattern", "")
    assert pattern, "No pattern found in section"
    pattern = re.compile(pattern)

    listvers = int(section.get("listvers", 0xFF))
    nosort = bool(section.get("nosort", False))

    files = defaultdict(list)
    for location in locations:
        logger.debug("Location: %s", location)
        file_list = root.glob(location)
        for file_path in file_list:
            logger.debug("File: %s", file_path)
            result = pattern.search(file_path.name)

            if not result:
                logger.debug("Not matched: %s", file_path)
                continue
            logger.debug("Matched: %r", result.groups())

            file_item = {
                "path": file_path,
                "category": section.get("category", "os"),  # Default to "os"
                "distro": section["distro"],
                "version": render(section["version"], result),
                "type": render(section.get("type", ""), result),
                "platform": render(section["platform"], result),
            }

            custom_sort_by = section.get("sort_by", "")
            if not custom_sort_by:
                file_item["sort_weight"] = (
                    LooseVersion(file_item["version"]),
                    get_platform_priority(file_item["platform"]),
                    file_item["type"],
                )
            else:
                file_item["sort_weight"] = render_list(custom_sort_by, result)
            logger.debug("File item: %r", file_item)
            # To support key_by, we have to put file_item into a dict first
            key = render(section.get("key_by", ""), result)
            files[key].append(file_item)

    results = []
    for file_list in files.values():
        if not nosort:
            file_list.sort(key=lambda x: x["sort_weight"], reverse=True)

        versions = set()
        for file_item in file_list:
            versions.add(file_item["version"])
            if len(versions) > listvers:
                break
            results.append(file_item)

    return results


def parse_file(file_item: dict, urlbase: str) -> dict:
    """
    Parse a file item (see parse_section() description)
    and return a dictionary with following schema:

    {
        "name": str,
        "url": str,
    }
    """

    url = urljoin(urlbase, file_item["path"].name)
    if file_item["platform"]:
        desc = "%s (%s%s)" % (
            file_item["version"],
            file_item["platform"],
            ", %s" % file_item["type"] if file_item["type"] else "",
        )
    else:
        desc = file_item["version"]

    return {"name": desc, "url": url}


def gen_from_sections(sections: dict) -> list:
    """
    Parse sections and return a list. Each item of the list is a dictionary with following schema:

    {
        "distro": str,
        "category": str,
        "urls": [{"name": str, "url": url}]
    }
    """

    # %main% contains root path and url base
    main = sections["%main%"]
    root = Path(main["root"])
    urlbase = main["urlbase"]
    del sections["%main%"]

    dN = {}
    if sections.get("%distro%"):
        for key, value in sections["%distro%"].items():
            if key.startswith("d"):
                dN[value] = int(key[1:])
        del sections["%distro%"]

    # Following sections represent different distributions each
    # Section name would be ignored. Note that it's possible that a distribution has multiple sections.
    results = defaultdict(list)
    for section in sections.values():
        section_name = section["distro"]
        # set default category to "os", if not exists
        if "category" not in section:
            section["category"] = "os"
        section_category = section["category"]
        for file_item in parse_section(section, root):
            results[(section_name, section_category)].append(
                parse_file(file_item, urlbase)
            )

    # Convert results to output
    results = [
        {"distro": k[0], "category": k[1], "urls": v} for k, v in results.items()
    ]
    results.sort(key=lambda x: dN.get(x["distro"], 0xFFFF))

    return results


def process_ini(ini: Path) -> dict:
    """
    Read the ini, replace !include to specific ini file, and use ConfigParser
    to parse them and return a dictionary with section names as keys,
    and parsed sections (dict) as values.
    """

    def process_include(ini: Path) -> str:
        ini_contents = ""
        with open(ini) as f:
            for line in f:
                if line.startswith("!include"):
                    include_file = Path(line.split()[1])
                    ini_contents += process_include(include_file)
                else:
                    ini_contents += line
        return ini_contents

    ini_contents = process_include(ini)
    parser = ConfigParser()
    parser.read_string(ini_contents)

    return {section: dict(parser[section]) for section in parser.sections()}


if __name__ == "__main__":
    if os.getenv("DEBUG"):
        logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    parser = ArgumentParser("genisolist")
    parser.add_argument(
        "--ini",
        help="Path to the ini file.",
        type=Path,
    )
    args = parser.parse_args()
    if not args.ini:
        parser.print_help()
        sys.exit(1)
    sections = process_ini(args.ini)
    print(json.dumps(gen_from_sections(sections)))

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
from glob import glob

from version import LooseVersion

logger = logging.getLogger(__name__)
exit_with_error = False


def get_platform_priority(platform: str) -> int:
    """
    Get the priority of the platform (arch). Higher is more preferred.
    """

    architectures = {
        ("amd64", "x86_64", "64bit"): 100,
        ("arm64", "aarch64", "arm64v8"): 95,
        ("riscv64"): 95,
        ("loongson2f", "loongson3"): 95,
        ("i386", "i486", "i586", "i686", "x86", "32bit"): 90,
        ("arm32", "armhf", "armv7"): 85,
    }
    # OS priority value at thousands digit (more important than architecture)
    oses = {
        "linux": 5000,
        "win": 4000,
        "mac": 3000,
        "android": 2000,
    }

    platform = platform.lower()

    # Python would iterate this in user-defined order, so in cases like
    # "x86" and "x86_64", "x86_64" shall be put before "x86"
    score = 0
    for arches in architectures:
        for arch in arches:
            if arch in platform:
                score = architectures[arches]
                break
        if score != 0:
            break
    for os in oses:
        if os in platform:
            score += oses[os]
            break
    return score


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
            if grp is None:
                grp = ""
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
            if grp is None:
                grp = ""
            l.append(grp)
    return l


def str2bool(v: str) -> bool:
    """
    Convert a string to boolean:

    "true", "True" -> True
    "false", "False" -> False
    Otherwise -> raise ValueError
    """

    if v.lower() == "true":
        return True
    elif v.lower() == "false":
        return False
    else:
        raise ValueError(f"{v} is not a boolean value")


def parse_section(section: dict, root: Path) -> list:
    """
    Parse a distribution section and return a list of sorted file items.

    A section is expected to have following schema:

    {
        "distro": str,
        "listvers": Optional[int] (defaults to 0xff, or 255),
        "location": str,
        "pattern": str,
        "version": Optional[str] (defaults to ""),
        "type": Optional[str] (defaults to ""),
        "platform": Optional[str] (defaults to ""),
        "category": Optional[str] (treats as "os" if not present),
        "key_by": Optional[str] (defaults to "" -- no keying),
        "sort_by": Optional[str] (defaults to sort by version, platform and type),
    }

    Exception could be raised if any of the required fields is missing.

    A "file item" should at least have following schema:

    {
        "path": str (relative path to root),
        "category": str,
        "version": str,
        "platform": str,
        "type": str,
        "sort_weight": list,
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
    pattern_use_name = str2bool(section.get("pattern_use_name", "false"))

    files = defaultdict(list)
    for location in locations:
        logger.debug("Location: %s", location)
        file_list = root.glob(location)
        for file_path in file_list:
            relative_path = str(file_path.relative_to(root))
            logger.debug("File: %s", relative_path)
            if not pattern_use_name:
                result = pattern.search(relative_path)
            else:
                result = pattern.search(file_path.name)

            if not result:
                logger.debug("Not matched: %s", file_path)
                continue
            logger.debug("Matched: %r", result.groups())

            file_item = {
                "path": relative_path,
                "category": section.get("category", "os"),  # Default to "os"
                "distro": section["distro"],
                "version": render(section.get("version", ""), result),
                "type": render(section.get("type", ""), result),
                "platform": render(section.get("platform", ""), result),
            }

            custom_sort_by = section.get("sort_by", "")
            if not custom_sort_by:
                file_item["sort_weight"] = [
                    LooseVersion(file_item["version"]),
                    get_platform_priority(file_item["platform"]),
                    file_item["type"],
                ]
            else:
                file_item["sort_weight"] = render_list(custom_sort_by, result)
            logger.debug("File item: %r", file_item)
            # To support key_by, we have to put file_item into a dict first
            key = render(section.get("key_by", ""), result)
            files[key].append(file_item)

    results = []
    for file_list in files.values():
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

    url = urljoin(urlbase, file_item["path"])
    if file_item["platform"]:
        desc = "%s (%s%s)" % (
            file_item["version"],
            file_item["platform"],
            ", %s" % file_item["type"] if file_item["type"] else "",
        )
    else:
        desc = file_item["version"]

    return {"name": desc, "url": url}


def gen_from_sections(sections: dict, strict: bool = False) -> list:
    """
    Parse sections and return a list. Each item of the list is a dictionary with following schema:

    {
        "distro": str,
        "category": str,
        "urls": [{"name": str, "url": url}]
    }
    """
    global exit_with_error

    # `%main%` contains root path and url base
    main = sections.get("%main%", {})
    root = Path(main.get("root", "."))
    urlbase = main.get("urlbase", "/")

    # `%distro%` contains distribution names and their priority
    dN = {}
    if sections.get("%distro%"):
        for key, value in sections["%distro%"].items():
            if key.startswith("d"):
                dN[value] = int(key[1:])

    # Following sections represent different distributions each
    # Section name would be ignored. Note that it's possible that a distribution has multiple sections.
    results = defaultdict(list)
    for sname, section in sections.items():
        if sname.startswith("%"):
            continue
        section_name = section["distro"]
        # set default category to "os", if not exists
        if "category" not in section:
            section["category"] = "os"
        section_category = section["category"]
        try:
            for file_item in parse_section(section, root):
                results[(section_name, section_category)].append(file_item)
        except Exception as e:
            exit_with_error = True
            logger.exception(f"Error parsing section [{sname}]")
            if strict:
                raise e

    for k in results:
        v = results[k]
        v.sort(key=lambda x: x["sort_weight"], reverse=True)
        results[k] = [parse_file(file_item, urlbase) for file_item in v]

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
        root_dir = ini.parent
        with open(ini) as f:
            for line in f:
                if line.startswith("!include"):
                    include_glob = line.removeprefix("!include").strip()
                    include_paths = glob(include_glob, root_dir=root_dir)
                    assert include_paths, f"No file found for {include_glob}"
                    for include_path in include_paths:
                        include_path = Path(include_path)
                        if not include_path.is_absolute():
                            include_file = root_dir / include_path
                        else:
                            include_file = include_path
                        ini_contents += process_include(include_file)
                else:
                    ini_contents += line
            # add a newline at the end of the file, to avoid it being concatenated with the next file
            ini_contents += "\n"
        return ini_contents

    ini_contents = process_include(ini)
    parser = ConfigParser()
    parser.read_string(ini_contents)

    return {section: dict(parser[section]) for section in parser.sections()}


if __name__ == "__main__":
    if os.getenv("DEBUG"):
        logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
    else:
        logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    parser = ArgumentParser("genisolist")
    parser.add_argument("ini", help="Path to the ini file.", type=Path)
    parser.add_argument("--strict", help="Enable strict mode", action="store_true")
    args = parser.parse_args()
    if not args.ini:
        parser.print_help()
        sys.exit(1)

    sections = process_ini(args.ini)
    print(json.dumps(gen_from_sections(sections, args.strict)))
    if exit_with_error:
        sys.exit(1)

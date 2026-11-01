# /// script
# requires-python = ">=3.12"
# dependencies = ["license-expression>=30.4"]
# ///
"""Checks every entry of the catalog: plugins/<name>.json.

An entry is valid when its file name is a plugin name, it has exactly the
fields description, url, commit and license with valid values, and the
repository at that commit is a Mirai plugin called like the file with a
license file. No plugin name, of an entry or of a plugin a repository brings
in its plugins/ folder, appears twice in the catalog.

Run from the root of the catalog: uv run scripts/validate.py
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from license_expression import get_spdx_licensing

NAME = re.compile(r"[a-z][a-z0-9_]*")
COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
FIELDS = {"description", "url", "commit", "license"}
# Bytes the engine keeps of each text, without its terminating zero.
MAX_NAME, MAX_DESCRIPTION, MAX_URL, MAX_LICENSE = 63, 255, 255, 63
PLUGIN_FILE = "plugin.mirai"
LICENSE_FILES = re.compile(r"(LICENSE|LICENCE|COPYING)([-_.].*)?", re.IGNORECASE)


def git(folder: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def entry_errors(name: str, data: object) -> list[str]:
    errors = []
    if not NAME.fullmatch(name) or len(name) > MAX_NAME:
        errors.append(f"the file name must be the plugin name: lowercase letters, digits and '_' after a letter, at most {MAX_NAME} characters")
    if not isinstance(data, dict):
        return errors + ["the file must hold a JSON object with description, url, commit and license"]
    missing, extra = FIELDS - data.keys(), data.keys() - FIELDS
    if missing:
        errors.append(f"add {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"remove {', '.join(sorted(extra))}: an entry has only description, url, commit and license")
    for field in FIELDS & data.keys():
        if not isinstance(data[field], str):
            errors.append(f"{field} must be a string")
    if errors:
        return errors
    description, url, commit, license = (data[f] for f in ("description", "url", "commit", "license"))
    if not description.strip() or len(description.encode()) > MAX_DESCRIPTION:
        errors.append(f"description must say what the plugin does in at most {MAX_DESCRIPTION} bytes")
    if not url.startswith("https://") or len(url.encode()) > MAX_URL:
        errors.append(f"url must be the https address of a public git repository, at most {MAX_URL} bytes")
    if not COMMIT.fullmatch(commit):
        errors.append("commit must be the full hash of the reviewed commit: 40 lowercase hexadecimal digits (64 in a SHA-256 repository)")
    if len(license) > MAX_LICENSE or get_spdx_licensing().validate(license).errors:
        errors.append(f"license must be an SPDX license expression such as MIT or MIT OR Apache-2.0, at most {MAX_LICENSE} characters")
    return errors


def manifest_name(folder: Path, path: str) -> str:
    try:
        manifest = json.loads(git(folder, "show", f"FETCH_HEAD:{path}"))
    except json.JSONDecodeError:
        raise RuntimeError(f"{path} is not valid JSON")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("name"), str):
        raise RuntimeError(f"{path} has no name")
    return manifest["name"]


def repository_plugins(name: str, url: str, commit: str, scratch: Path) -> list[str]:
    """The plugins the repository brings at commit: its own first."""
    folder = scratch / name
    folder.mkdir()
    git(folder, "init", "--quiet")
    try:
        git(folder, "fetch", "--quiet", "--depth", "1", "--filter=blob:none", url, commit)
    except RuntimeError as error:
        raise RuntimeError(f"{url} has no commit {commit} that can be fetched: {error}")
    files = git(folder, "ls-tree", "-r", "--name-only", "FETCH_HEAD").splitlines()
    if PLUGIN_FILE not in files:
        raise RuntimeError(f"{url} at {commit[:12]} has no {PLUGIN_FILE} at its root: it is not a Mirai plugin")
    own = manifest_name(folder, PLUGIN_FILE)
    if own != name:
        raise RuntimeError(f"{url} is the plugin {own}: name the file {own}.json")
    if not any(LICENSE_FILES.fullmatch(f) for f in files):
        raise RuntimeError(f"{url} has no license file at its root: add LICENSE (or LICENSE-MIT, COPYING...)")
    plugins = [own]
    for path in files:
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == "plugins" and parts[2] == PLUGIN_FILE:
            companion = manifest_name(folder, path)
            if companion != parts[1]:
                raise RuntimeError(f"{path} names the plugin {companion}: it must carry the name of its folder")
            plugins.append(companion)
    return plugins


def main() -> int:
    root = Path(__file__).resolve().parent.parent / "plugins"
    failures: list[str] = []
    owners: dict[str, str] = {}
    entries = sorted(root.iterdir()) if root.is_dir() else []
    with tempfile.TemporaryDirectory() as scratch:
        for path in entries:
            where = f"plugins/{path.name}"
            if not path.is_file() or path.suffix != ".json":
                failures.append(f"{where}: plugins/ holds only <name>.json files")
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                failures.append(f"{where}: not valid UTF-8 JSON: {error}")
                continue
            errors = entry_errors(path.stem, data)
            if errors:
                failures += [f"{where}: {e}" for e in errors]
                continue
            try:
                plugins = repository_plugins(path.stem, data["url"], data["commit"], Path(scratch))
            except RuntimeError as error:
                failures.append(f"{where}: {error}")
                continue
            for plugin in plugins:
                if plugin in owners:
                    failures.append(f"{where}: the plugin {plugin} is already in the catalog by {owners[plugin]}; choose another name")
                else:
                    owners[plugin] = where
            print(f"ok {where}: {', '.join(plugins)}")
    for failure in failures:
        print(f"error {failure}", file=sys.stderr)
    if not entries:
        print("The catalog has no plugins yet.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

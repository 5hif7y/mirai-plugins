# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Checks every entry of the catalog: plugins/<name>.json.

An entry is valid when its file name is a plugin name, it has exactly the
fields description, url and commit with valid values, and the
repository at that commit is a Mirai plugin called like the file with a
license file. No plugin name, of an entry or of a plugin a repository brings
in its plugins/ folder, appears twice in the catalog. A companion in
plugins/<name>/ may be a git submodule: its https url and the commit the
gitlink pins are fetched and checked like a companion in the tree. An entry may have an
icon beside it, plugins/<name>.png, a PNG of at most MAX_ICON pixels a side.

Run from the root of the catalog: uv run scripts/validate.py
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

NAME = re.compile(r"[a-z][a-z0-9_]*")
COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
FIELDS = {"description", "url", "commit"}
# Bytes the engine keeps of each text, without its terminating zero.
MAX_NAME, MAX_DESCRIPTION, MAX_URL = 63, 255, 255
PLUGIN_FILE = "plugin.mirai"
LICENSE_FILES = re.compile(r"(LICENSE|LICENCE|COPYING)([-_.].*)?", re.IGNORECASE)
# Pixels a side of an icon, project.PLUGIN_ICON_MAX of the engine.
MAX_ICON = 128
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def icon_errors(path: Path) -> list[str]:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        return ["the icon must be a PNG file"]
    width, height = int.from_bytes(header[16:20]), int.from_bytes(header[20:24])
    if width > MAX_ICON or height > MAX_ICON:
        return [f"the icon is {width}x{height}: scale it to at most {MAX_ICON}x{MAX_ICON} pixels"]
    if not path.with_suffix(".json").is_file():
        return [f"the icon has no entry: add plugins/{path.stem}.json or remove it"]
    return []


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
        return errors + ["the file must hold a JSON object with description, url and commit"]
    missing, extra = FIELDS - data.keys(), data.keys() - FIELDS
    if missing:
        errors.append(f"add {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"remove {', '.join(sorted(extra))}: an entry has only description, url and commit")
    for field in FIELDS & data.keys():
        if not isinstance(data[field], str):
            errors.append(f"{field} must be a string")
    if errors:
        return errors
    description, url, commit = (data[f] for f in ("description", "url", "commit"))
    if not description.strip() or len(description.encode()) > MAX_DESCRIPTION:
        errors.append(f"description must say what the plugin does in at most {MAX_DESCRIPTION} bytes")
    if not url.startswith("https://") or len(url.encode()) > MAX_URL:
        errors.append(f"url must be the https address of a public git repository, at most {MAX_URL} bytes")
    if not COMMIT.fullmatch(commit):
        errors.append("commit must be the full hash of the reviewed commit: 40 lowercase hexadecimal digits (64 in a SHA-256 repository)")
    return errors


def manifest_name(folder: Path, path: str) -> str:
    try:
        manifest = json.loads(git(folder, "show", f"FETCH_HEAD:{path}"))
    except json.JSONDecodeError:
        raise RuntimeError(f"{path} is not valid JSON")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("name"), str):
        raise RuntimeError(f"{path} has no name")
    return manifest["name"]


def fetch(folder: Path, url: str, commit: str) -> list[str]:
    """The files of url at commit, fetched into a new folder without blobs."""
    folder.mkdir()
    git(folder, "init", "--quiet")
    try:
        git(folder, "fetch", "--quiet", "--depth", "1", "--filter=blob:none", url, commit)
    except RuntimeError as error:
        raise RuntimeError(f"{url} has no commit {commit} that can be fetched: {error}")
    return git(folder, "ls-tree", "-r", "--name-only", "FETCH_HEAD").splitlines()


def submodules(folder: Path) -> dict[str, str]:
    """The url of each submodule in .gitmodules at FETCH_HEAD, by its path."""
    try:
        lines = git(folder, "config", "--blob", "FETCH_HEAD:.gitmodules", "--get-regexp", r"^submodule\..*\.(path|url)$")
    except RuntimeError as error:
        raise RuntimeError(f".gitmodules cannot be read: {error}")
    paths: dict[str, str] = {}
    urls: dict[str, str] = {}
    for line in lines.splitlines():
        key, _, value = line.partition(" ")
        section, _, field = key.rpartition(".")
        (paths if field == "path" else urls)[section] = value
    return {path.strip("/"): urls.get(section, "") for section, path in paths.items()}


def submodule_companion(name: str, path: str, url: str, commit: str, scratch: Path) -> str:
    """The name of the plugin a submodule at plugins/<folder> brings."""
    if not url.startswith("https://"):
        raise RuntimeError(f"{path} is a submodule whose url must be the https address of a public git repository, not {url or 'missing'}")
    folder = scratch / f"{name}.{path.split('/')[1]}"
    files = fetch(folder, url, commit)
    if PLUGIN_FILE not in files:
        raise RuntimeError(f"{path} is the submodule {url} at {commit[:12]}, which has no {PLUGIN_FILE} at its root: it is not a Mirai plugin")
    companion = manifest_name(folder, PLUGIN_FILE)
    if companion != path.split("/")[1]:
        raise RuntimeError(f"{path}/{PLUGIN_FILE} names the plugin {companion}: it must carry the name of its folder")
    return companion


def repository_plugins(name: str, url: str, commit: str, scratch: Path) -> list[str]:
    """The plugins the repository brings at commit: its own first."""
    folder = scratch / name
    files = fetch(folder, url, commit)
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
    # A companion that is a submodule is a gitlink plugins/<folder> (mode 160000) in the tree.
    gitlinks = {}
    for line in git(folder, "ls-tree", "FETCH_HEAD", "plugins/").splitlines():
        info, _, path = line.partition("	")
        mode, kind, target = info.split()
        if mode == "160000" and kind == "commit":
            gitlinks[path] = target
    if gitlinks:
        urls = submodules(folder) if ".gitmodules" in files else {}
        for path, target in sorted(gitlinks.items()):
            plugins.append(submodule_companion(name, path, urls.get(path, ""), target, scratch))
    return plugins


def main() -> int:
    root = Path(__file__).resolve().parent.parent / "plugins"
    failures: list[str] = []
    owners: dict[str, str] = {}
    entries = sorted(root.iterdir()) if root.is_dir() else []
    with tempfile.TemporaryDirectory() as scratch:
        for path in entries:
            where = f"plugins/{path.name}"
            if path.is_file() and path.suffix == ".png":
                failures += [f"{where}: {e}" for e in icon_errors(path)]
                continue
            if not path.is_file() or path.suffix != ".json":
                failures.append(f"{where}: plugins/ holds only <name>.json files and their <name>.png icons")
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

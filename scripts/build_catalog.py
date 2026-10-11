#!/usr/bin/env python3
"""Build Picora's client catalog from reviewed registrations and GitHub Releases."""

import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$")
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
MAX_ZIP = 10 * 1024 * 1024
MAX_UNPACKED = 20 * 1024 * 1024
LEGACY_IDS = {"com.imgloc.picora", "dev.picora.telegraph-image"}


def fail(message):
    raise ValueError(message)


def version_key(value):
    match = VERSION_RE.fullmatch(value)
    if not match:
        fail(f"invalid SemVer: {value}")
    prerelease = match.group(4)
    parts = tuple((0, int(part)) if part.isdigit() else (1, part) for part in prerelease.split(".")) if prerelease else ()
    return tuple(int(match.group(i)) for i in (1, 2, 3)) + (0 if prerelease else 1, parts)


def normalized_permissions(program):
    permissions = program.get("permissions")
    if not isinstance(permissions, dict):
        fail("uploader.json has no permissions")
    if set(permissions) - {"network", "readSelectedFile", "allowInsecureHttp", "deleteUploadedFile"}:
        fail("uploader.json has unknown permission fields")
    network = permissions.get("network")
    if not isinstance(network, list) or not network or any(not isinstance(host, str) for host in network):
        fail("invalid network permissions")
    if permissions.get("readSelectedFile") is not True:
        fail("upload permission must read the selected file")
    return {
        "network": sorted(network),
        "readSelectedFile": permissions.get("readSelectedFile") is True,
        "allowInsecureHttp": permissions.get("allowInsecureHttp") is True,
        "deleteUploadedFile": permissions.get("deleteUploadedFile") is True,
    }


def load_registration(path):
    item = json.loads(path.read_text(encoding="utf-8"))
    plugin_id = item.get("id")
    repo = item.get("releaseRepository")
    if not isinstance(plugin_id, str) or not ID_RE.fullmatch(plugin_id):
        fail(f"{path}: invalid plugin id")
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo):
        fail(f"{path}: invalid releaseRepository")
    if path.stem != plugin_id:
        fail(f"{path}: filename must match plugin id")
    if item.get("legacy") and (plugin_id not in LEGACY_IDS or repo != "Alnitak44/picora-plugins"):
        fail(f"{path}: legacy exception is reserved for existing plugins")
    if not item.get("legacy") and not plugin_id.startswith(f"io.github.{repo.split('/')[0].lower()}."):
        fail(f"{path}: id must use the GitHub owner's io.github namespace")
    min_version = item.get("minAppVersion")
    if not isinstance(min_version, str):
        fail(f"{path}: missing minAppVersion")
    version_key(min_version)
    prefix = item.get("assetPrefix", "")
    if not isinstance(prefix, str) or "/" in prefix or "\\" in prefix:
        fail(f"{path}: invalid assetPrefix")
    approved = item.get("approvedPermissions")
    if not isinstance(approved, dict) or not isinstance(approved.get("network"), list):
        fail(f"{path}: missing approvedPermissions")
    return item


def parse_package(data, registration):
    if len(data) > MAX_ZIP:
        fail("ZIP exceeds 10 MB")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 128 or sum(entry.file_size for entry in entries) > MAX_UNPACKED:
            fail("ZIP has too many or too large entries")
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            fail("ZIP contains duplicate paths")
        if any(name.startswith("/") or "\\" in name or ".." in name.split("/") for name in names):
            fail("ZIP contains an unsafe path")
        if any("\x00" in name or ":" in name for name in names):
            fail("ZIP contains an unsafe path")
        if any((entry.external_attr >> 16) & 0o170000 == 0o120000 for entry in entries):
            fail("ZIP contains a symbolic link")
        if any(entry.flag_bits & 0x1 for entry in entries):
            fail("ZIP contains an encrypted file")
        if any(entry.file_size > 2 * 1024 * 1024 for entry in entries):
            fail("ZIP contains a file above 2 MB")
        bad_entry = archive.testzip()
        if bad_entry is not None:
            fail(f"ZIP CRC failed: {bad_entry}")
        if "plugin.json" not in names or "readme.md" not in names:
            fail("ZIP is missing required root files")
        metadata = json.loads(archive.read("plugin.json"))
        entry_path = metadata.get("entry")
        if not isinstance(entry_path, str) or not entry_path.endswith(".json") or entry_path not in names:
            fail("ZIP is missing the declared program entry")
        program = json.loads(archive.read(entry_path))
    if metadata.get("id") != registration["id"]:
        return None
    if metadata.get("packageVersion") != 1:
        fail(f"{registration['id']}: unsupported package metadata")
    runtime = metadata.get("runtime")
    if runtime not in ("http-v1", "http-v2") or program.get("schemaVersion") != (1 if runtime == "http-v1" else 2):
        fail(f"{registration['id']}: runtime and schema mismatch")
    minimum = registration["minAppVersion"]
    if runtime == "http-v2" and version_key(minimum) < version_key("1.0.1"):
        fail(f"{registration['id']}: http-v2 requires Picora 1.0.1")
    actual_permissions = normalized_permissions(program)
    approved = registration["approvedPermissions"].copy()
    approved["network"] = sorted(approved["network"])
    if actual_permissions != approved:
        fail(f"{registration['id']}: permissions changed; update registration through review")
    required = {"name": 60, "description": 160, "author": 80, "version": 30}
    for field, limit in required.items():
        value = metadata.get(field)
        if not isinstance(value, str) or not value or len(value) > limit:
            fail(f"{registration['id']}: invalid {field}")
    version_key(metadata["version"])
    repository = metadata.get("repository")
    parsed_repo = urllib.parse.urlparse(repository) if isinstance(repository, str) else None
    if not parsed_repo or parsed_repo.scheme != "https" or parsed_repo.netloc != "github.com":
        fail(f"{registration['id']}: repository must be a GitHub HTTPS URL")
    if not registration.get("legacy") and parsed_repo.path.rstrip("/").lower() != f"/{registration['releaseRepository'].lower()}":
        fail(f"{registration['id']}: package repository differs from releaseRepository")
    mark = metadata.get("mark")
    if not isinstance(mark, str) or not 1 <= len(mark) <= 3:
        mark = "P"
    return {
        "id": registration["id"],
        "name": metadata["name"],
        "description": metadata["description"],
        "author": metadata["author"],
        "repository": repository,
        "version": metadata["version"],
        "runtime": runtime,
        "packageVersion": 1,
        "minAppVersion": minimum,
        "mark": mark,
        "example": registration.get("example") is True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


class GitHub:
    def __init__(self, token=None):
        self.token = token

    def releases(self, repository):
        url = f"https://api.github.com/repos/{repository}/releases?per_page=30"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "picora-catalog"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            return json.load(response)

    def asset(self, url):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "github.com" or "/releases/download/" not in parsed.path:
            fail(f"unsupported release asset URL: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "picora-catalog"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(MAX_ZIP + 1)
        if len(data) > MAX_ZIP:
            fail("ZIP exceeds 10 MB")
        return data


def build(registrations, github):
    entries = []
    paths = sorted(registrations.glob("*.json"))
    if not paths or len(paths) > 500:
        fail("catalog must contain 1 to 500 registrations")
    for path in paths:
        registration = load_registration(path)
        candidates = []
        for release in github.releases(registration["releaseRepository"]):
            if release.get("draft") or release.get("prerelease"):
                continue
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                if not name.startswith(registration.get("assetPrefix", "")) or not name.endswith(".picora-plugin.zip"):
                    continue
                url = asset.get("browser_download_url", "")
                expected_prefix = f"https://github.com/{registration['releaseRepository']}/releases/download/"
                if not url.lower().startswith(expected_prefix.lower()):
                    fail(f"{registration['id']}: asset is not in its release repository")
                data = github.asset(url)
                entry = parse_package(data, registration)
                if entry is None:
                    continue
                entry["downloadUrl"] = url
                candidates.append(entry)
        if not candidates:
            fail(f"{registration['id']}: no matching published ZIP release")
        entries.append(max(candidates, key=lambda entry: version_key(entry["version"])))
    entries.sort(key=lambda entry: entry["id"])
    return {"schemaVersion": 1, "plugins": entries}


def update_readme(source, catalog):
    start, end = "<!-- catalog:start -->", "<!-- catalog:end -->"
    if source.count(start) != 1 or source.count(end) != 1:
        fail("README.md is missing catalog markers")
    lines = ["| 插件 | 版本 | 说明 |", "| --- | --- | --- |"]
    for entry in catalog["plugins"]:
        name = entry["name"].replace("|", "\\|")
        description = entry["description"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| [{name}]({entry['repository']}) | {entry['version']} | {description} |")
    return source.split(start)[0] + start + "\n" + "\n".join(lines) + "\n" + end + source.split(end)[1]


def guard_existing_versions(previous, catalog):
    previous_entries = {entry["id"]: entry for entry in previous.get("plugins", [])}
    for entry in catalog["plugins"]:
        old = previous_entries.get(entry["id"])
        if old and version_key(entry["version"]) < version_key(old["version"]):
            fail(f"{entry['id']}: catalog version would go backwards")
        if old and entry["version"] == old["version"] and entry["sha256"] != old["sha256"]:
            fail(f"{entry['id']}: published ZIP changed without a new version")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate without writing files")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    catalog = build(root / "registrations", GitHub(os.environ.get("GITHUB_TOKEN")))
    rendered = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    if len(rendered.encode("utf-8")) > 1024 * 1024:
        fail("generated index exceeds the client's 1 MB limit")
    index_path = root / "index.json"
    readme_path = root / "README.md"
    if index_path.exists():
        previous = json.loads(index_path.read_text(encoding="utf-8"))
        guard_existing_versions(previous, catalog)
    readme = update_readme(readme_path.read_text(encoding="utf-8"), catalog)
    if args.check:
        print(rendered)
        return
    index_path.write_text(rendered, encoding="utf-8", newline="\n")
    readme_path.write_text(readme, encoding="utf-8", newline="\n")
    print(f"Updated {len(catalog['plugins'])} plugins")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, urllib.error.URLError, zipfile.BadZipFile) as error:
        print(f"catalog build failed: {error}", file=sys.stderr)
        sys.exit(1)

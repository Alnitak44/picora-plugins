#!/usr/bin/env python3
"""Build Picora's client catalog from reviewed registrations and GitHub Releases."""

import argparse
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
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
CATALOG_REPOSITORY = "Alnitak44/picora-plugins"
PACKAGE_SUFFIX = ".picora-plugin.zip"
ACCEPTED_SUFFIXES = (
    PACKAGE_SUFFIX,
    ".picora-plugin.zip.zip",
    ".picora.plugin.zip",
)

# 目录里展示的链接只允许这些平台；插件自身声明的网络主机和登记文件
# 审核过的 allowedLinks 会额外放行。教程里的链接会被用户直接点击打开。
TRUSTED_LINK_HOSTS = {
    "github.com",
    "www.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "user-images.githubusercontent.com",
    "camo.githubusercontent.com",
}

# 只收录明显违规或诈骗用语；正常描述里会出现的词（如“免费”）不要加进来，
# 否则正常插件也会被拦下。命中即拒绝构建，不静默改写。
BANNED_WORDS = (
    "官方认证",
    "官方授权",
    "官网认证",
    "加微信",
    "加qq",
    "加群",
    "客服qq",
    "扫码进群",
    "领取红包",
    "返利",
    "刷单",
    "日赚",
    "兼职赚钱",
    "破解版",
    "激活码",
    "代充",
    "出售账号",
    "购买账号",
    "博彩",
    "赌博",
    "私彩",
)

# 名称不能被这些保留名占用，避免冒充官方。
RESERVED_NAMES = ("picora", "picora插件", "picora官方")

LINK_RE = re.compile(r"\]\(\s*<?([^)\s>]+)>?")
BARE_URL_RE = re.compile(r"https?://[^\s<>)\]}`'\"，。；！？、]+", re.IGNORECASE)

# RFC 2606 保留域名，文档里的占位地址（https://img.example.com 之类）不算外链。
PLACEHOLDER_HOSTS = {"example.com", "example.org", "example.net"}
PLACEHOLDER_SUFFIXES = (".example.com", ".example.org", ".example.net")


def fail(message):
    raise ValueError(message)


def action_escape(message):
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def warn(message):
    print(f"catalog warning: {message}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning::{action_escape(message)}", file=sys.stderr)


def accepted_asset_name(name):
    return next((suffix for suffix in ACCEPTED_SUFFIXES if name.endswith(suffix)), None)


def version_key(value):
    match = VERSION_RE.fullmatch(value)
    if not match:
        fail(f"invalid SemVer: {value}")
    prerelease = match.group(4)
    parts = tuple((0, int(part)) if part.isdigit() else (1, part) for part in prerelease.split(".")) if prerelease else ()
    return tuple(int(match.group(i)) for i in (1, 2, 3)) + (0 if prerelease else 1, parts)


def normalize_name(value):
    """Fold a plugin name so lookalikes compare equal."""
    text = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s\-_·.。:：|/\\()（）\[\]【】{}<>+&*~,，!！?？'\"]", "", text)


def edit_distance(left, right, limit=2):
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i]
        for j, right_char in enumerate(right, 1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def names_collide(left, right):
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= 3 and shorter in longer:
        return True
    return len(shorter) >= 4 and edit_distance(left, right) <= 2


def check_impersonation(entries):
    """Reject names that duplicate or imitate another plugin or the official name."""
    seen = {}
    reserved = {normalize_name(name) for name in RESERVED_NAMES}
    for entry in entries:
        normalized = normalize_name(entry["name"])
        for existing in reserved:
            if names_collide(normalized, existing):
                fail(f"{entry['id']}: 插件名 {entry['name']!r} 与 Picora 官方名称过于接近；请改用能区分来源的名称")
        for other_id, other_name, other_normalized in seen.values():
            if names_collide(normalized, other_normalized):
                fail(
                    f"{entry['id']}: 插件名 {entry['name']!r} 与已收录插件 {other_name!r}（{other_id}）"
                    "重复或过于接近；请改用能区分来源的名称"
                )
        seen[entry["id"]] = (entry["id"], entry["name"], normalized)


def check_banned_words(plugin_id, field, text):
    folded = unicodedata.normalize("NFKC", text).casefold()
    for word in BANNED_WORDS:
        if word in folded:
            fail(f"{plugin_id}: {field} 含违规内容 {word!r}；请修改后重新发布")


def base_domain(host):
    labels = host.lower().strip(".").split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host.lower()


def allowed_link_hosts(registration):
    """Trusted platforms plus the plugin's own request hosts and their domain."""
    hosts = set(TRUSTED_LINK_HOSTS)
    extra = [host for host in registration["approvedPermissions"]["network"] if host != "*"]
    extra += registration.get("allowedLinks", [])
    for host in extra:
        host = host.lower()
        hosts.add(host)
        hosts.add(base_domain(host))
    return hosts


def check_links(plugin_id, field, text, hosts):
    links = LINK_RE.findall(text) + BARE_URL_RE.findall(text)
    for link in links:
        link = link.rstrip("`'\".,;:!?，。；：！？、")
        parsed = urllib.parse.urlparse(link)
        if parsed.scheme in ("", "mailto"):
            continue
        if parsed.scheme not in ("http", "https"):
            fail(f"{plugin_id}: {field} 含不支持的链接 {link}")
        host = parsed.netloc.rsplit("@", 1)[-1].split(":")[0].lower()
        # 文档里常见「https://你的域名」这类占位写法，不是真实外链。
        if not host or not host.isascii() or not re.fullmatch(r"[a-z0-9.-]+", host):
            continue
        if host in PLACEHOLDER_HOSTS or host.endswith(PLACEHOLDER_SUFFIXES):
            continue
        if host not in hosts and base_domain(host) not in hosts:
            fail(
                f"{plugin_id}: {field} 里的链接指向 {host}，不在允许范围。"
                "教程与主页只能链接 GitHub、插件自身的请求主机，或登记文件 allowedLinks 审核过的域名"
            )


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
        if path.stem.lower() == plugin_id:
            warn(f"{path}: 文件名大小写与 id 不同；已按 id={plugin_id} 读取。建议将文件改名为 {plugin_id}.json")
        else:
            fail(f"{path}: 文件名应为 {plugin_id}.json，当前是 {path.name}")
    if "legacy" in item:
        fail(f"{path}: legacy registration is not supported")
    if repo.lower() == CATALOG_REPOSITORY.lower():
        fail(f"{path}: plugins must publish in their own repository")
    if not plugin_id.startswith(f"io.github.{repo.split('/')[0].lower()}."):
        fail(f"{path}: id must use the GitHub owner's io.github namespace")
    min_version = item.get("minAppVersion")
    if not isinstance(min_version, str):
        fail(f"{path}: missing minAppVersion")
    version_key(min_version)
    prefix = item.get("assetPrefix", "")
    if not isinstance(prefix, str) or "/" in prefix or "\\" in prefix:
        fail(f"{path}: invalid assetPrefix")
    allowed_links = item.get("allowedLinks", [])
    if not isinstance(allowed_links, list) or any(
        not isinstance(host, str) or not host.strip() or "/" in host or ":" in host
        for host in allowed_links
    ):
        fail(f"{path}: allowedLinks 必须是主机名数组，例如 [\"docs.example.com\"]")
    approved = item.get("approvedPermissions")
    if not isinstance(approved, dict) or not isinstance(approved.get("network"), list):
        fail(f"{path}: missing approvedPermissions")
    return item


def parse_package(data, registration, check_permissions=True, observed_ids=None, emit_warnings=True, check_mark=True):
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
            fail("ZIP 根目录需要 plugin.json 和 readme.md；请打包文件夹里的内容，不要再套一层文件夹或 ZIP")
        metadata = json.loads(archive.read("plugin.json"))
        entry_path = metadata.get("entry")
        if not isinstance(entry_path, str) or not entry_path.endswith(".json") or entry_path not in names:
            fail("ZIP is missing the declared program entry")
        program = json.loads(archive.read(entry_path))
        readme = archive.read("readme.md").decode("utf-8", "replace")
    if metadata.get("id") != registration["id"]:
        if observed_ids is not None:
            observed_ids.append(metadata.get("id"))
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
    if check_permissions and actual_permissions != approved:
        fail(
            f"{registration['id']}: uploader.json 的 permissions={json.dumps(actual_permissions, ensure_ascii=False)}；"
            f"登记文件 approvedPermissions={json.dumps(approved, ensure_ascii=False)}。"
            "请核对实际请求域名；若确需新权限，提交登记文件 PR 审核"
        )
    required = {"name": 60, "description": 160, "author": 80, "version": 30}
    for field, limit in required.items():
        value = metadata.get(field)
        if not isinstance(value, str) or not value or len(value) > limit:
            fail(f"{registration['id']}: invalid {field}")
    version_key(metadata["version"])
    for field in ("name", "description", "author"):
        check_banned_words(registration["id"], field, metadata[field])
    check_banned_words(registration["id"], "readme.md", readme)
    hosts = allowed_link_hosts(registration)
    check_links(registration["id"], "readme.md", readme, hosts)
    homepage = metadata.get("homepage")
    if homepage is not None:
        if not isinstance(homepage, str) or not homepage.strip():
            fail(f"{registration['id']}: plugin.json 的 homepage 必须是字符串")
        check_links(registration["id"], "homepage", homepage, hosts)
    repository = metadata.get("repository")
    if repository is None:
        repository = f"https://github.com/{registration['releaseRepository']}"
        if emit_warnings:
            warn(f"{registration['id']}: plugin.json 未写 repository；目录已使用登记仓库 {repository}")
    parsed_repo = urllib.parse.urlparse(repository) if isinstance(repository, str) else None
    if not parsed_repo or parsed_repo.scheme != "https" or parsed_repo.netloc != "github.com":
        fail(f"{registration['id']}: plugin.json 的 repository={repository!r}；应为 https://github.com/{registration['releaseRepository']}")
    if parsed_repo.path.rstrip("/").lower() != f"/{registration['releaseRepository'].lower()}":
        fail(
            f"{registration['id']}: plugin.json 的 repository={repository}，"
            f"但登记文件 releaseRepository={registration['releaseRepository']}；"
            f"请将 repository 改为 https://github.com/{registration['releaseRepository']}"
        )
    mark = metadata.get("mark")
    if mark is None:
        mark = "P"
    if check_mark:
        if not isinstance(mark, str):
            fail(f"{registration['id']}: plugin.json 的 mark 必须是字符串")
        mark = mark.strip().upper()
        # Dart String.length counts UTF-16 code units, including after uppercase.
        if not 1 <= len(mark.encode("utf-16-le", errors="surrogatepass")) // 2 <= 3:
            fail(f"{registration['id']}: plugin.json 的 mark 需要 1–3 个字符，当前为 {metadata.get('mark')!r}")
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
    seen_ids = set()
    if not registrations.is_dir():
        fail("registrations directory is missing")
    paths = sorted(registrations.glob("*.json"))
    if len(paths) > 500:
        fail("catalog must contain at most 500 registrations")
    for path in paths:
        registration = load_registration(path)
        if registration["id"] in seen_ids:
            fail(f"{path}: 插件 ID {registration['id']} 重复；每个插件只能有一份登记文件")
        seen_ids.add(registration["id"])
        candidates = []
        observed_ids = []
        published_releases = 0
        asset_names = []
        for release in github.releases(registration["releaseRepository"]):
            if release.get("draft") or release.get("prerelease"):
                continue
            published_releases += 1
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                asset_names.append(name)
                suffix = accepted_asset_name(name)
                if not name.startswith(registration.get("assetPrefix", "")) or suffix is None:
                    continue
                url = asset.get("browser_download_url", "")
                expected_prefix = f"https://github.com/{registration['releaseRepository']}/releases/download/"
                if not url.lower().startswith(expected_prefix.lower()):
                    fail(f"{registration['id']}: asset is not in its release repository")
                data = github.asset(url)
                try:
                    entry = parse_package(
                        data, registration, check_permissions=False,
                        observed_ids=observed_ids, emit_warnings=False, check_mark=False,
                    )
                except (ValueError, zipfile.BadZipFile) as error:
                    fail(f"{registration['id']}: Release 附件 {name} 校验失败：{error}")
                if entry is None:
                    continue
                entry["downloadUrl"] = url
                candidates.append((entry, data, name, suffix == PACKAGE_SUFFIX))
        if not candidates:
            if observed_ids:
                fail(
                    f"{registration['id']}: 发布的 ZIP 中 plugin.json 的 id 为 "
                    f"{', '.join(repr(value) for value in observed_ids)}；"
                    f"应与登记文件 id={registration['id']} 完全一致"
                )
            if not published_releases:
                fail(
                    f"{registration['id']}: {registration['releaseRepository']} 没有已发布的正式 Release；"
                    "请先发布 Release 并上传插件 ZIP"
                )
            preview = ", ".join(repr(name) for name in asset_names[:5]) or "无附件"
            fail(
                f"{registration['id']}: {registration['releaseRepository']} 的 Release 未找到插件 ZIP；"
                f"现有附件：{preview}。文件名应以 {PACKAGE_SUFFIX} 结尾"
                + (f"，并以 {registration['assetPrefix']} 开头" if registration.get("assetPrefix") else "")
            )
        latest, latest_data, latest_name, canonical_name = max(
            candidates, key=lambda candidate: (version_key(candidate[0]["version"]), candidate[3])
        )
        if not canonical_name:
            warn(
                f"{registration['id']}: Release 附件 {latest_name} 命名不规范，但 ZIP 校验通过，已自动收录；"
                f"以后建议使用以 {PACKAGE_SUFFIX} 结尾的文件名"
            )
        validated = parse_package(latest_data, registration)
        validated["downloadUrl"] = latest["downloadUrl"]
        if "*" in registration["approvedPermissions"]["network"]:
            warn(
                f"{registration['id']}: approvedPermissions 允许任意主机（*）；"
                "该插件可以改写请求目标，首次收录与权限变更时需人工确认"
            )
        entries.append(validated)
    check_impersonation(entries)
    entries.sort(key=lambda entry: entry["id"])
    return {"schemaVersion": 1, "plugins": entries}


def clip_width(text, limit=22):
    """Keep the author column narrow; markdown cannot set column widths."""
    width = 0
    kept = []
    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if width + char_width > limit:
            return "".join(kept).rstrip() + "…"
        width += char_width
        kept.append(char)
    return text


def update_readme(source, catalog):
    start, end = "<!-- catalog:start -->", "<!-- catalog:end -->"
    if source.count(start) != 1 or source.count(end) != 1:
        fail("README.md is missing catalog markers")
    lines = ["| 插件 | 作者 | 版本 | 说明 |", "| --- | --- | --- | --- |"]
    for entry in catalog["plugins"]:
        name = entry["name"].replace("|", "\\|")
        author = clip_width(entry["author"].replace("|", "\\|"))
        description = entry["description"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| [{name}]({entry['repository']}) | {author} | {entry['version']} | {description} |"
        )
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
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::error::{action_escape(str(error))}", file=sys.stderr)
        sys.exit(1)

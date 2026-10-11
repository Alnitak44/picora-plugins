import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_catalog import (
    build,
    guard_existing_versions,
    load_registration,
    parse_package,
    update_readme,
    version_key,
)


PLUGIN_ID = "io.github.example.picora.demo"
REPOSITORY = "example/picora-plugin-demo"
PERMISSIONS = {
    "network": ["api.example.com"],
    "readSelectedFile": True,
    "allowInsecureHttp": False,
    "deleteUploadedFile": False,
}
REGISTRATION = {
    "id": PLUGIN_ID,
    "releaseRepository": REPOSITORY,
    "minAppVersion": "1.0.1",
    "approvedPermissions": PERMISSIONS,
}


def package(version="1.0.0", network=None, metadata_changes=None):
    metadata = {
        "packageVersion": 1,
        "runtime": "http-v2",
        "entry": "uploader.json",
        "id": PLUGIN_ID,
        "name": "Demo Image Host",
        "description": "Upload images",
        "author": "Example Author",
        "repository": "https://github.com/example/picora-plugin-demo",
        "version": version,
        "mark": "DE",
        **(metadata_changes or {}),
    }
    program = {
        "schemaVersion": 2,
        "permissions": {
            **PERMISSIONS,
            "network": network or ["api.example.com"],
        },
        "config": [],
        "upload": {},
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("plugin.json", json.dumps(metadata))
        archive.writestr("uploader.json", json.dumps(program))
        archive.writestr("readme.md", "# Demo")
    return output.getvalue()


class FakeGitHub:
    def __init__(self, versions):
        self.assets = {}
        self.release_list = []
        for version in versions:
            url = f"https://github.com/{REPOSITORY}/releases/download/v{version}/demo-{version}.picora-plugin.zip"
            self.assets[url] = package(version)
            self.release_list.append({
                "draft": False,
                "prerelease": False,
                "assets": [{"name": f"demo-{version}.picora-plugin.zip", "browser_download_url": url}],
            })

    def releases(self, repository):
        assert repository == REPOSITORY
        return self.release_list

    def asset(self, url):
        return self.assets[url]


class CatalogBuilderTests(unittest.TestCase):
    def test_removed_imgloc_cannot_use_legacy_registration(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / "com.imgloc.picora.json"
            path.write_text(json.dumps({
                **REGISTRATION,
                "id": "com.imgloc.picora",
                "releaseRepository": "Alnitak44/picora-plugins",
                "legacy": True,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "legacy exception"):
                load_registration(path)

    def test_last_plugin_can_exit_without_fetching_its_releases(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            registrations = Path(temp)
            path = registrations / f"{PLUGIN_ID}.json"
            path.write_text(json.dumps(REGISTRATION), encoding="utf-8")
            previous = build(registrations, FakeGitHub(["1.0.0"]))
            path.unlink()
            catalog = build(registrations, object())
        self.assertEqual(catalog, {"schemaVersion": 1, "plugins": []})
        guard_existing_versions(previous, catalog)
        readme = update_readme(
            "before\n<!-- catalog:start -->\nDemo Image Host\n<!-- catalog:end -->\nafter",
            catalog,
        )
        self.assertNotIn("Demo Image Host", readme)
        self.assertIn("| 插件 | 版本 | 说明 |", readme)

    def test_missing_registration_directory_cannot_clear_catalog(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            with self.assertRaisesRegex(ValueError, "directory is missing"):
                build(Path(temp) / "missing", object())

    def test_package_cannot_self_assign_example_badge(self):
        data = package(metadata_changes={"example": True})
        self.assertFalse(parse_package(data, REGISTRATION)["example"])
        # Only the reviewed registry registration designates development samples.
        self.assertTrue(parse_package(data, {**REGISTRATION, "example": True})["example"])

    def test_release_produces_download_url_size_and_digest(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / f"{PLUGIN_ID}.json"
            path.write_text(json.dumps(REGISTRATION), encoding="utf-8")
            catalog = build(Path(temp), FakeGitHub(["1.0.0", "1.1.0"]))
        entry = catalog["plugins"][0]
        self.assertEqual(entry["version"], "1.1.0")
        self.assertEqual(entry["id"], PLUGIN_ID)
        self.assertEqual(entry["size"], len(package("1.1.0")))
        self.assertEqual(len(entry["sha256"]), 64)
        self.assertIn("/releases/download/v1.1.0/", entry["downloadUrl"])
        readme = update_readme("before\n<!-- catalog:start -->\nold\n<!-- catalog:end -->\nafter", catalog)
        self.assertIn("[Demo Image Host](https://github.com/example/picora-plugin-demo)", readme)
        self.assertNotIn("下载](https://", readme)

    def test_permission_change_is_not_auto_published(self):
        with self.assertRaisesRegex(ValueError, "permissions changed"):
            parse_package(package(network=["evil.example"]), REGISTRATION)

    def test_approved_update_allows_older_release_permissions(self):
        github = FakeGitHub(["1.0.0", "1.1.0"])
        old_url = next(url for url in github.assets if "/v1.0.0/" in url)
        github.assets[old_url] = package("1.0.0", network=["old.example"])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / f"{PLUGIN_ID}.json"
            path.write_text(json.dumps(REGISTRATION), encoding="utf-8")
            catalog = build(Path(temp), github)
        self.assertEqual(catalog["plugins"][0]["version"], "1.1.0")

    def test_account_namespace_and_legacy_exception(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / f"{PLUGIN_ID}.json"
            path.write_text(json.dumps({**REGISTRATION, "releaseRepository": "another/repo"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "io.github namespace"):
                load_registration(path)
            path.write_text(json.dumps({**REGISTRATION, "legacy": True}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "legacy exception"):
                load_registration(path)

    def test_semver_order(self):
        self.assertLess(version_key("1.0.0-beta.2"), version_key("1.0.0-beta.10"))
        self.assertLess(version_key("1.0.0-rc.1"), version_key("1.0.0"))
        self.assertLess(version_key("1.0.0"), version_key("1.1.0"))

    def test_published_version_is_immutable(self):
        old = {"plugins": [{"id": PLUGIN_ID, "version": "1.0.0", "sha256": "a" * 64}]}
        changed = {"plugins": [{"id": PLUGIN_ID, "version": "1.0.0", "sha256": "b" * 64}]}
        with self.assertRaisesRegex(ValueError, "changed without a new version"):
            guard_existing_versions(old, changed)


if __name__ == "__main__":
    unittest.main()

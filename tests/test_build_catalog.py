import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
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
    def test_historical_plugins_cannot_use_legacy_registration(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            for plugin_id in ["com.imgloc.picora", "dev.picora.telegraph-image"]:
                path = Path(temp) / f"{plugin_id}.json"
                path.write_text(json.dumps({
                    **REGISTRATION,
                    "id": plugin_id,
                    "releaseRepository": "Alnitak44/picora-plugins",
                    "legacy": True,
                }), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "legacy registration"):
                    load_registration(path)

    def test_catalog_repository_cannot_host_plugin_releases(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            plugin_id = "io.github.alnitak44.demo"
            path = Path(temp) / f"{plugin_id}.json"
            path.write_text(json.dumps({
                **REGISTRATION,
                "id": plugin_id,
                "releaseRepository": "Alnitak44/picora-plugins",
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "own repository"):
                load_registration(path)

    def test_repository_mismatch_cannot_be_exempted(self):
        registration = {**REGISTRATION, "releaseRepository": "example/another-repo", "legacy": True}
        with self.assertRaisesRegex(ValueError, "repository"):
            parse_package(package(), registration)

    def test_filename_case_typo_is_accepted_without_changing_plugin_id(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / "io.github.Example.picora.demo.json"
            path.write_text(json.dumps(REGISTRATION), encoding="utf-8")
            with redirect_stderr(io.StringIO()) as warnings:
                catalog = build(Path(temp), FakeGitHub(["1.0.0"]))
        self.assertEqual(catalog["plugins"][0]["id"], PLUGIN_ID)
        self.assertIn(f"{PLUGIN_ID}.json", warnings.getvalue())

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

    def test_common_release_asset_suffix_typos_are_accepted(self):
        for suffix in (".picora-plugin.zip.zip", ".picora.plugin.zip"):
            with self.subTest(suffix=suffix):
                github = FakeGitHub(["1.0.0"])
                asset = github.release_list[0]["assets"][0]
                old_url = asset["browser_download_url"]
                asset["name"] = f"demo-1.0.0{suffix}"
                asset["browser_download_url"] = old_url.rsplit("/", 1)[0] + "/" + asset["name"]
                github.assets[asset["browser_download_url"]] = github.assets.pop(old_url)
                with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
                    path = Path(temp) / f"{PLUGIN_ID}.json"
                    path.write_text(json.dumps(REGISTRATION), encoding="utf-8")
                    with redirect_stderr(io.StringIO()) as warnings:
                        catalog = build(Path(temp), github)
                self.assertEqual(catalog["plugins"][0]["version"], "1.0.0")
                self.assertTrue(catalog["plugins"][0]["downloadUrl"].endswith(suffix))
                self.assertIn("命名不规范", warnings.getvalue())

    def test_unmatched_release_explains_asset_name_or_package_id(self):
        github = FakeGitHub(["1.0.0"])
        asset = github.release_list[0]["assets"][0]
        asset["name"] = "demo-1.0.0.zip"
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / f"{PLUGIN_ID}.json"
            path.write_text(json.dumps(REGISTRATION), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"demo-1\.0\.0\.zip.*\.picora-plugin\.zip"):
                build(Path(temp), github)
            asset["name"] = "demo-1.0.0.picora-plugin.zip"
            github.assets[asset["browser_download_url"]] = package(
                metadata_changes={"id": "io.github.example.picora.other"}
            )
            with self.assertRaisesRegex(ValueError, r"plugin\.json.*io\.github\.example\.picora\.other"):
                build(Path(temp), github)

    def test_permission_change_is_not_auto_published(self):
        with self.assertRaisesRegex(ValueError, r"uploader\.json.*evil\.example.*api\.example\.com"):
            parse_package(package(network=["evil.example"]), REGISTRATION)

    def test_missing_repository_uses_reviewed_release_repository(self):
        with redirect_stderr(io.StringIO()) as warnings:
            entry = parse_package(package(metadata_changes={"repository": None}), REGISTRATION)
        self.assertEqual(entry["repository"], f"https://github.com/{REPOSITORY}")
        self.assertIn("plugin.json 未写 repository", warnings.getvalue())
        with self.assertRaisesRegex(ValueError, r"other/repo.*example/picora-plugin-demo"):
            parse_package(
                package(metadata_changes={"repository": "https://github.com/other/repo"}),
                REGISTRATION,
            )

    def test_approved_update_allows_older_release_permissions(self):
        github = FakeGitHub(["1.0.0", "1.1.0"])
        old_url = next(url for url in github.assets if "/v1.0.0/" in url)
        github.assets[old_url] = package("1.0.0", network=["old.example"])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / f"{PLUGIN_ID}.json"
            path.write_text(json.dumps(REGISTRATION), encoding="utf-8")
            catalog = build(Path(temp), github)
        self.assertEqual(catalog["plugins"][0]["version"], "1.1.0")

    def test_account_namespace_and_unsupported_legacy_field(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path = Path(temp) / f"{PLUGIN_ID}.json"
            path.write_text(json.dumps({**REGISTRATION, "releaseRepository": "another/repo"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "io.github namespace"):
                load_registration(path)
            for flag in [True, False]:
                path.write_text(json.dumps({**REGISTRATION, "legacy": flag}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "legacy registration"):
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

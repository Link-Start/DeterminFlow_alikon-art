from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import pytest

from marketplace_fixtures import SKILL_TEXT, _empty_manager, _manager, _service
from src.skill_marketplace.bundle import FORMAT, pack, unpack, read_directory
from src.skill_marketplace.catalog import verified_preview_payload
from src.skill_marketplace.errors import LocalSkillError
from src.skill_marketplace.local_skills import prepare_skill_upload, skill_identity
from test_marketplace_authoring import _signed_in
from src.skill_marketplace.service import _MARKETPLACE_TERMS_VERSION
from test_marketplace_installation import _pin
from test_marketplace_update import _publish_remote

ROOT = SKILL_TEXT.encode()


def raw_bundle(entries: list[tuple[str, bytes]]) -> bytes:
    return json.dumps({"format": FORMAT, "files": [
        {"path": name, "content": base64.b64encode(data).decode()}
        for name, data in entries
    ]}).encode()


def test_legacy_identity_and_prepared_bundle_preserve_references():
    assert pack({"SKILL.md": ROOT}) == ROOT
    assert prepare_skill_upload(b"\xef\xbb\xbf" + ROOT, name="shared-skill", version="1.2.3") == ROOT
    original = pack({"references/zh.md": "中文规则".encode(), "SKILL.md": ROOT})
    prepared = prepare_skill_upload(original, name="new-skill", version="2.0.0")
    assert skill_identity(prepared) == ("new-skill", "2.0.0")
    assert unpack(prepared)["references/zh.md"] == "中文规则".encode()
    assert skill_identity(original) == ("shared-skill", "1.2.3")


@pytest.mark.parametrize("path", [
    "../escape.md", "/tmp/escape.md", "a/../../escape.md", "a\\b.md", "a//b.md",
    "a/./b.md", "C:/b.md", "CON.md", "foo/NUL.md", "foo/a.",
    "nested/SKILL.md", "skill.md", "a.md:stream", "a/ b.md",
])
def test_unsafe_paths_rejected_even_when_type_check_off(path, monkeypatch):
    monkeypatch.setenv("MARKETPLACE_SKILL_FILE_TYPE_CHECK", "false")
    with pytest.raises(LocalSkillError):
        unpack(raw_bundle([("SKILL.md", ROOT), (path, b"test")]))


@pytest.mark.parametrize("paths", [
    ["a.md", "a.md"], ["A.md", "a.md"], ["a.md", "a.md/b.md"],
    ["Refs/a.md", "refs/b.md"],
])
def test_collisions_rejected(paths):
    with pytest.raises(LocalSkillError):
        unpack(raw_bundle([("SKILL.md", ROOT), *[(p, b"x") for p in paths]]))


def test_type_check_defaults_white_list_and_has_independent_switch(monkeypatch):
    files = {"SKILL.md": ROOT, "assets/sample.bin": b"\x00\xff"}
    with pytest.raises(LocalSkillError, match="白名单"):
        pack(files)
    monkeypatch.setenv("MARKETPLACE_SKILL_FILE_TYPE_CHECK", "false")
    assert unpack(pack(files)) == files
    monkeypatch.setenv("MARKETPLACE_SKILL_FILE_TYPE_CHECK", "true")
    monkeypatch.setenv("MARKETPLACE_SKILL_ALLOWED_EXTENSIONS", ".md,.bin")
    assert unpack(pack(files)) == files
    with pytest.raises(LocalSkillError):
        pack({"SKILL.md": ROOT, "refs/test.md": b"\xff"})


def test_limits_and_bad_base64():
    invalid = json.loads(raw_bundle([("SKILL.md", ROOT)]))
    invalid["files"][0]["content"] = "eB=="  # noncanonical padding bits
    with pytest.raises(LocalSkillError):
        unpack(json.dumps(invalid).encode())
    for files in [
        {"SKILL.md": ROOT, "large.md": b"x" * (256 * 1024 + 1)},
        {"SKILL.md": ROOT, **{f"f{i}.md": b"x" for i in range(64)}},
        {"SKILL.md": ROOT, **{f"f{i}.md": b"x" * (256 * 1024) for i in range(4)}},
    ]:
        with pytest.raises(LocalSkillError):
            pack(files)


def test_local_links_are_rejected(tmp_path):
    (tmp_path / "SKILL.md").write_bytes(ROOT)
    (tmp_path / "link.md").symlink_to(tmp_path / "SKILL.md")
    with pytest.raises(LocalSkillError):
        read_directory(tmp_path)

    (tmp_path / "link.md").unlink()
    (tmp_path / "refs").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(LocalSkillError):
        read_directory(tmp_path)


def test_unreadable_directory_is_not_silently_omitted(tmp_path, monkeypatch):
    (tmp_path / "SKILL.md").write_bytes(ROOT)
    directory = tmp_path / "references"
    directory.mkdir()
    import os
    original_scandir = os.scandir

    def unreadable(path):
        if str(path) == str(directory):
            raise PermissionError("references unavailable")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", unreadable)
    with pytest.raises(LocalSkillError):
        read_directory(tmp_path)


def test_preview_pins_all_files_and_prepare_does_not_edit_local(tmp_path):
    manager = _manager(tmp_path)
    directory = manager.local_skills_dir / "shared-skill"
    (directory / "references").mkdir()
    attachment = directory / "references/zh.md"
    attachment.write_text("中文方法", encoding="utf-8")
    service = _signed_in(tmp_path, manager=manager)
    preview = asyncio.run(service.preview_local_skill("shared-skill"))
    assert unpack(preview["content"].encode())["references/zh.md"] == attachment.read_bytes()
    assert any(s["id"] == "shared-skill" for s in asyncio.run(service.eligible_local_skills()))
    checked = verified_preview_payload(
        {**preview, "version_id": "v1"}, expected_version_id="v1", expected_sha256=preview["sha256"])
    assert checked["content"] == preview["content"]
    attachment.write_text("changed", encoding="utf-8")
    changed = asyncio.run(service.preview_local_skill("shared-skill"))
    assert changed["sha256"] != preview["sha256"]
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.publish(skill_id="shared-skill", resource_type="skill", license_id="MIT",
            rights_confirmed=True, terms_confirmed=True, terms_version=_MARKETPLACE_TERMS_VERSION,
            metadata={}, expected_sha256=preview["sha256"]))
    assert error.value.code == "local_skill_changed"


def test_install_noncanonical_wire_then_update_removes_old_attachments(tmp_path):
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    service.marketplace.content = raw_bundle([("references/old.md", b"old"), ("SKILL.md", ROOT)])
    result = asyncio.run(service.install("shared-skill", **_pin(service)))
    directory = service.skill_manager.marketplace_skills_dir / "shared-skill"
    assert (directory / "references/old.md").read_bytes() == b"old"
    assert result["provenance"]["package"]["files"]["references/old.md"] == hashlib.sha256(b"old").hexdigest()
    new = pack({"SKILL.md": ROOT.replace(b"1.2.3", b"1.2.4"), "references/new.md": b"new"})
    pin = _publish_remote(service.marketplace, text=new.decode())
    asyncio.run(service.update("shared-skill", **pin))
    assert not (directory / "references/old.md").exists()
    assert (directory / "references/new.md").read_bytes() == b"new"
    assert service.skill_manager.get_skill("shared-skill").version == "1.2.4"


def test_download_refuses_changed_attachment_with_unchanged_root(tmp_path):
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    service.marketplace.content = pack({"SKILL.md": ROOT, "references/a.md": b"original"})
    pin = _pin(service)
    original_download = service.marketplace.download_skill

    async def changed_download(slug):
        service.marketplace.content = pack({"SKILL.md": ROOT, "references/a.md": b"changed"})
        return await original_download(slug)

    service.marketplace.download_skill = changed_download
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.install("shared-skill", **pin))
    assert error.value.code == "integrity_mismatch"
    assert not (service.skill_manager.marketplace_skills_dir / "shared-skill").exists()


@pytest.mark.parametrize("mutation", ["edit", "add", "remove"])
def test_update_refuses_modified_attachment(tmp_path, mutation):
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    service.marketplace.content = pack({"SKILL.md": ROOT, "references/a.md": b"original"})
    asyncio.run(service.install("shared-skill", **_pin(service)))
    directory = service.skill_manager.marketplace_skills_dir / "shared-skill"
    attachment = directory / "references/a.md"
    if mutation == "edit":
        attachment.write_bytes(b"edited")
    elif mutation == "add":
        (directory / "extra.md").write_bytes(b"added")
    else:
        attachment.unlink()
    pin = _publish_remote(service.marketplace)
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.update("shared-skill", **pin))
    assert error.value.code == "local_modified"


def test_update_rollback_restores_whole_tree_on_reload_failure(tmp_path, monkeypatch):
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    original = pack({"SKILL.md": ROOT, "references/old.md": b"original"})
    service.marketplace.content = original
    asyncio.run(service.install("shared-skill", **_pin(service)))
    before = service.skill_manager.provenance_store.get("skill", "shared-skill")
    pin = _publish_remote(service.marketplace)
    monkeypatch.setattr(service.skill_manager, "reload", lambda: (_ for _ in ()).throw(OSError("reload")))
    with pytest.raises(OSError):
        asyncio.run(service.update("shared-skill", **pin))
    directory = service.skill_manager.marketplace_skills_dir / "shared-skill"
    assert read_directory(directory) == original
    assert service.skill_manager.provenance_store.get("skill", "shared-skill") == before

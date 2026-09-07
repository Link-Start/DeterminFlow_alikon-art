from src.extension_api.registrar import ExtensionContributions, OwnedPath
from src.extension_host.resource_validation import validate_file_resources


def test_validation_uses_writable_data_outside_bundle(tmp_path):
    bundle = tmp_path / "readonly-app"
    bundle.mkdir()
    package = tmp_path / "plugin-skills"
    package.mkdir()
    pending = ExtensionContributions()
    pending.resource_paths["skill_bundles"] = [OwnedPath(owner="demo", path=package)]
    user_data = tmp_path / "user-data"
    validate_file_resources(user_data, ExtensionContributions(), pending)
    assert (user_data / "skills").is_dir()
    assert not (bundle / "data").exists()

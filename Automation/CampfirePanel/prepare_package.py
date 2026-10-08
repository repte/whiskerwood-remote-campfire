"""Prepare the Remote Campfire cook label and package boundary."""

import json
from pathlib import Path

import unreal


BASE = "/Game/Mods/CampfirePanel"
VERSION = "0.1.1"
LABEL_NAME = "PAL_CampfirePanel"
LABEL_PATH = f"{BASE}/{LABEL_NAME}"
RUNTIME_NAMES = ("BP_MapLoad", "WBP_CampfirePanel", "WBP_CampfireRow")
RUNTIME_PATHS = {f"{BASE}/{name}" for name in RUNTIME_NAMES}
NATIVE_PACKAGES = {
    "/Script/CoreUObject", "/Script/Engine", "/Script/InputCore",
    "/Script/ProjectArco", "/Script/SystemCore", "/Script/LowCore", "/Script/UMG",
    "/Script/Slate", "/Script/SlateCore", "/Script/CommonUI",
    "/Script/CommonInput", "/Script/ApplicationCore",
}
ROOT = Path(unreal.Paths.project_dir()).resolve()
SOURCE = ROOT / "Content" / "Mods" / "CampfirePanel"

descriptor = json.loads((SOURCE / "CampfirePanel.uplugin").read_text(encoding="utf-8-sig"))
assert descriptor["Name"] == "CampfirePanel", "Unexpected mod descriptor name"
assert descriptor["Version"] == VERSION, "Unexpected mod version"
assert descriptor["EngineVersion"] == "5.8", "Unexpected engine version"
assert descriptor["Description"] and descriptor["CreatedBy"], "Incomplete mod descriptor"
assert not descriptor.get("Modules"), "CampfirePanel must not require a native DLL"
assert not descriptor.get("Plugins"), "CampfirePanel must not require another plugin"

allowed_files = {f"{name}.uasset" for name in RUNTIME_NAMES}
allowed_files.update({f"{LABEL_NAME}.uasset", "CampfirePanel.uplugin"})
for path in SOURCE.rglob("*"):
    if path.is_file():
        assert path.relative_to(SOURCE).as_posix() in allowed_files, f"Unexpected mod source file: {path}"
for asset_path in RUNTIME_PATHS:
    assert unreal.EditorAssetLibrary.does_asset_exist(asset_path), f"Missing runtime asset: {asset_path}"
    assert isinstance(unreal.load_asset(asset_path), unreal.Blueprint), f"Asset is not a Blueprint: {asset_path}"

registry = unreal.AssetRegistryHelpers.get_asset_registry()
registry.scan_paths_synchronous(["/Game/Mods"], force_rescan=True)
registry.wait_for_completion()
labels = registry.get_assets_by_class(unreal.TopLevelAssetPath("/Script/Engine", "PrimaryAssetLabel"))
used_chunks = {
    data.get_asset().get_editor_property("rules").get_editor_property("chunk_id")
    for data in labels if str(data.package_name) != LABEL_PATH
}
label = None
chunk = -1
if unreal.EditorAssetLibrary.does_asset_exist(LABEL_PATH):
    label = unreal.load_asset(LABEL_PATH)
    assert isinstance(label, unreal.PrimaryAssetLabel), "Existing cook label has the wrong class"
    chunk = label.get_editor_property("rules").get_editor_property("chunk_id")
if not 1 <= chunk <= 300 or chunk in used_chunks:
    chunk = next((value for value in range(1, 301) if value not in used_chunks), None)
    assert chunk is not None, "No unused mod chunk available"
if label is None:
    factory = unreal.DataAssetFactory()
    factory.set_editor_property("data_asset_class", unreal.PrimaryAssetLabel)
    label = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        LABEL_NAME, BASE, unreal.PrimaryAssetLabel, factory,
    )
    assert label, "Could not create CampfirePanel cook label"

rules = label.get_editor_property("rules")
rules.set_editor_property("chunk_id", chunk)
rules.set_editor_property("cook_rule", unreal.PrimaryAssetCookRule.ALWAYS_COOK)
# Native game resources must remain external to the mod chunk.
rules.set_editor_property("apply_recursively", False)
label.set_editor_property("rules", rules)
label.set_editor_property("label_assets_in_my_directory", True)
label.set_editor_property("is_runtime_label", False)
label.set_editor_property("explicit_assets", [])
label.set_editor_property("explicit_blueprints", [])
assert unreal.EditorAssetLibrary.save_loaded_asset(label), "Could not save CampfirePanel cook label"

registry.scan_paths_synchronous([BASE], force_rescan=True)
registry.wait_for_completion()
assets = registry.get_assets_by_path(BASE, recursive=True, include_only_on_disk_assets=True)
assert {str(data.package_name) for data in assets} == RUNTIME_PATHS | {LABEL_PATH}, "Unexpected CampfirePanel asset inventory"
options = unreal.AssetRegistryDependencyOptions(
    include_soft_package_references=True, include_hard_package_references=True,
    include_game_package_references=True, include_editor_only_package_references=False,
    include_searchable_names=False, include_soft_management_references=False,
    include_hard_management_references=False,
)
external_resources = set()
for asset_path in sorted(RUNTIME_PATHS):
    dependencies = registry.get_dependencies(asset_path, options)
    assert dependencies is not None, f"Missing dependency information: {asset_path}"
    for dependency in dependencies:
        path = str(dependency)
        if path in RUNTIME_PATHS or path in NATIVE_PACKAGES:
            continue
        if path == "/Engine/EditorBlueprintResources/StandardMacros":
            continue
        assert path.startswith(("/Game/", "/Engine/")) and not path.startswith("/Game/Mods/"), (
            "Unexpected runtime dependency", asset_path, path,
        )
        resource = unreal.load_asset(path)
        assert isinstance(resource, (unreal.Texture, unreal.Font, unreal.FontFace)), (
            "Only existing native game textures and fonts may remain external", asset_path, path,
        )
        external_resources.add(path)

saved = Path(unreal.Paths.project_saved_dir()).resolve()
saved.mkdir(parents=True, exist_ok=True)
(saved / "CampfirePanel-PackageSetup.json").write_text(
    json.dumps({"mod": "CampfirePanel", "version": VERSION, "chunk": chunk,
                "runtime_assets": list(RUNTIME_NAMES),
                "external_resources": sorted(external_resources)}, indent=2) + "\n",
    encoding="utf-8",
)
unreal.log(f"CAMPFIRE_PACKAGE_SETUP_PASS: isolated chunk={chunk}, editor-only label")

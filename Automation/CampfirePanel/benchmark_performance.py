"""Reproduce compiled RefreshList timings on a stable synthetic editor fixture.

Run with UnrealEditor-Cmd -ExecutePythonScript=... -unattended -nullrhi -nosound.
Optional environment:
  CAMPFIRE_BENCHMARK_MOUNT: extracted cooked asset directory; omitted uses the
      current project's generated /Game/Mods/CampfirePanel classes.
  CAMPFIRE_BENCHMARK_OUTPUT: absolute result JSON path.
  CAMPFIRE_BENCHMARK_LABEL: identifying label, e.g. baseline-shipped-0.1.1.

No assets are authored/saved, and no gameplay/refill methods run. There are no
timing-threshold assertions. This measures one real compiled Blueprint call per
sample; Python does not drive individual membership comparisons.
"""
import hashlib
import json
import os
from pathlib import Path
import statistics
import time
import traceback

import unreal


COUNTS = (10, 100, 200, 500, 1000, 2000)
WARMUPS = 2
REPEATS = 9
ROOT = "/Game/Mods/CampfirePanel/"
LABEL = os.environ.get("CAMPFIRE_BENCHMARK_LABEL", "current-generated")
OUTPUT = Path(os.environ.get(
    "CAMPFIRE_BENCHMARK_OUTPUT",
    str(Path(unreal.Paths.project_saved_dir()) / "CampfirePerformance" / "refreshlist-benchmark.json"),
)).resolve()
mount_value = os.environ.get("CAMPFIRE_BENCHMARK_MOUNT", "").strip()
mount = Path(mount_value).resolve() if mount_value else None
created = []
components = []
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
system = unreal.get_default_object(unreal.load_class(None, "/Script/Engine.KismetSystemLibrary"))
results = {
    "label": LABEL,
    "status": "running",
    "complete": False,
    "workload": "compiled RefreshList, unchanged membership; all components are supported campfires",
    "counts": list(COUNTS),
    "warmups_per_count": WARMUPS,
    "samples_per_count": REPEATS,
    "engine_version": unreal.SystemLibrary.get_engine_version(),
    "mount_directory": str(mount) if mount else None,
    "not_game_fps": True,
    "limitations": [
        "Synthetic editor-world fixture under NullRHI, not real game FPS or frame time.",
        "All FueledHeater components share one player-owned GridActor; game-specific native functionality is stubbed.",
        "Actual compiled RefreshList collection and membership work is timed; fixture setup is outside timing.",
        "One Python-to-Unreal call per sample; no per-heater Python work inside timing.",
        "Stable membership bypasses row reconstruction; rendering, full Pump/UpdateRows and refill work are excluded.",
        "Host scheduling and unrelated process load are uncontrolled; retain all samples, not only medians.",
    ],
    "asset_sha256": {},
    "samples": [],
}


def native(name):
    return unreal.load_class(None, "/Script/ProjectArco." + name)


def spawn(cls):
    assert cls, "Required reflected class is unavailable"
    obj = actors.spawn_actor_from_class(cls, unreal.Vector(0, 0, -100000))
    assert obj, "Unable to create transient editor fixture actor"
    created.append(obj)
    return obj


def set_native(obj, name, value, kind):
    system.call_method("Set" + kind + "PropertyByName", args=(obj, name, value))


def save_results():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["RefreshList synthetic editor benchmark: " + LABEL,
             "Status: " + results["status"],
             "Campfires | median ms | min ms | max ms"]
    for sample in results["samples"]:
        lines.append("{campfires} | {median_ms:.4f} | {min_ms:.4f} | {max_ms:.4f}".format(**sample))
    lines.extend(["", *results["limitations"]])
    if results.get("error"):
        lines.extend(["", results["error"]])
    OUTPUT.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


try:
    if mount:
        assert mount.is_dir(), "CAMPFIRE_BENCHMARK_MOUNT must be an existing directory"
        unreal.SystemLibrary.execute_console_command(
            None, 'PackageName.RegisterMountPoint ' + ROOT + ' "' + mount.as_posix() + '/"')
    asset_dir = mount or (Path(unreal.Paths.project_content_dir()).resolve() / "Mods" / "CampfirePanel")
    for name in ("BP_MapLoad", "WBP_CampfirePanel", "WBP_CampfireRow"):
        for extension in (".uasset", ".uexp"):
            path = asset_dir / (name + extension)
            if path.is_file():
                results["asset_sha256"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

    host_cls = unreal.load_class(None, ROOT + "BP_MapLoad.BP_MapLoad_C")
    host = spawn(host_cls)
    results["host_class"] = host.get_class().get_path_name()
    systems = spawn(native("ArcoSystems"))
    grid = spawn(native("GridActor"))
    set_native(host, "Systems", systems, "Object")
    set_native(grid, "isPlayerOwned", True, "Bool")
    assert host.get_editor_property("Systems") == systems
    meta = systems.get_editor_property("m_worldMeta")
    registry = meta.get_editor_property("m_fueledHeaters_components")
    heaters = host.get_editor_property("Heaters")
    heater_cls = native("FueledHeater")
    for i in range(max(COUNTS)):
        heater = unreal.new_object(heater_cls, outer=grid)
        components.append(heater)
        set_native(heater, "m_fuelSource", 2, "Byte")
        if i == 0:
            results["fixture_owner"] = str(heater.call_method("GetOwner"))
            assert host.call_method("IsCampfire", args=(heater,)), "Synthetic heater must pass IsCampfire"

    for count in COUNTS:
        registry.clear()
        heaters.clear()
        for heater in components[:count]:
            registry.add(heater)
            heaters.append(heater)
        assert len(systems.get_editor_property("m_worldMeta").get_editor_property("m_fueledHeaters_components")) == count
        assert len(host.get_editor_property("Heaters")) == count
        for _ in range(WARMUPS):
            assert host.call_method("RefreshList")
        assert len(host.get_editor_property("CurrentHeaters")) == count
        assert host.get_editor_property("Available"), "Stable list must bypass row rebuilding"
        timings = []
        for _ in range(REPEATS):
            start = time.perf_counter_ns()
            assert host.call_method("RefreshList")
            timings.append((time.perf_counter_ns() - start) / 1e6)
        sample = {
            "campfires": count,
            "median_ms": statistics.median(timings),
            "min_ms": min(timings),
            "max_ms": max(timings),
            "samples_ms": timings,
        }
        results["samples"].append(sample)
        save_results()
        unreal.log("CAMPFIRE_PERFORMANCE_SAMPLE " + json.dumps(sample))
    results["status"] = "complete"
    results["complete"] = True
except Exception:
    results["status"] = "failed"
    results["error"] = traceback.format_exc()
    raise
finally:
    for obj in reversed(created):
        actors.destroy_actor(obj)
    save_results()

unreal.log("CAMPFIRE_PERFORMANCE_BENCHMARK_COMPLETE " + LABEL)

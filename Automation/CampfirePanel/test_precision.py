"""Check the compiled host's numeric storage without executing game actions."""
import struct

import unreal


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


klass = unreal.load_class(None, "/Game/Mods/CampfirePanel/BP_MapLoad.BP_MapLoad_C")
assert klass, "CampfirePanel host is missing"
cdo = unreal.get_default_object(klass)
names = ("FloatScratch", "BurnScratch", "BeforeFuel")
original = {name: cdo.get_editor_property(name) for name in names}
failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}: actual={actual!r}, expected={expected!r}")
    else:
        unreal.log(f"CAMPFIRE_PRECISION_CHECK_PASS: {label}")


try:
    # These are real Blueprint properties, not a substitute implementation.
    for name in names:
        cdo.set_editor_property(name, 1123.9940342903137)
        check(name + " is single precision", cdo.get_editor_property(name), f32(1123.9940342903137))

    # Reproduce the user's first refill: 727.994019 seconds + one wood.
    cdo.set_editor_property("BeforeFuel", 727.994019)
    cdo.set_editor_property("FloatScratch", 1200 * f32(0.33))
    cdo.set_editor_property("BurnScratch", cdo.get_editor_property("BeforeFuel") + cdo.get_editor_property("FloatScratch"))
    expected = cdo.get_editor_property("BurnScratch")
    check("logged refill survives native float storage", f32(expected), expected)
    check("logged refill uses native rounding", expected, 1123.9940185546875)

    # Dirty fuel multiplies before truncation; double storage yields 1679.
    cdo.set_editor_property("FloatScratch", 1200 * f32(1.4))
    check("dirty fuel duration", int(cdo.get_editor_property("FloatScratch")), 1680)
finally:
    for name, value in original.items():
        cdo.set_editor_property(name, value)

assert not failures, "\n".join(failures)
unreal.log("CAMPFIRE_PRECISION_TESTS_PASS: 6 checks; no game actions or asset saves")

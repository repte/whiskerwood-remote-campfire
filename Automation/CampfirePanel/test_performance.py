"""Compiled refresh regressions on transient fixtures; no gameplay or asset saves.

These are behavior checks, not timings. Removing a visibility guard must change
the seeded UI/refill state; losing a reopen request must leave the polling clock
armed; mistaking equal counts for equal membership must leave a stale row.
"""
import traceback

import unreal


ROOT = "/Game/Mods/CampfirePanel/"
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
system = unreal.get_default_object(unreal.load_class(None, "/Script/Engine.KismetSystemLibrary"))
factory = unreal.get_default_object(unreal.load_class(None, "/Script/UMG.WidgetBlueprintLibrary"))
classes = {name: unreal.load_class(None, ROOT + name + "." + name + "_C")
           for name in ("BP_MapLoad", "WBP_CampfirePanel", "WBP_CampfireRow")}
assert all(classes.values()), "Compiled CampfirePanel assets must exist"
native = lambda name: unreal.load_class(None, "/Script/ProjectArco." + name)


def put(obj, name, value, kind="Bool"):
    # All writes target transient instances, never class defaults or assets.
    system.call_method("Set" + kind + "PropertyByName", args=(obj, name, value))
    # Native enum entries are not exported to Python; the real IsCampfire call
    # validates the temporary fuel-source fixture below instead.
    if kind != "Byte":
        assert obj.get_editor_property(name) == value, (name, value)


def replace_array(array, values):
    array.clear()
    for value in values:
        array.append(value)


class Fixture:
    def __init__(self):
        self.created = []
        self.components = []
        self.host = self.spawn(classes["BP_MapLoad"])
        self.panel = factory.call_method("Create", args=(world, classes["WBP_CampfirePanel"], None))
        assert self.panel
        put(self.host, "Panel", self.panel, "Object")
        put(self.panel, "Host", self.host, "Object")
        self.rows_box = self.panel.get_editor_property("RowsBox")

    def spawn(self, cls):
        obj = actors.spawn_actor_from_class(cls, unreal.Vector(0, 0, -100000))
        assert obj
        self.created.append(obj)
        return obj

    def row(self, heater=None):
        row = factory.call_method("Create", args=(world, classes["WBP_CampfireRow"], None))
        assert row
        put(row, "Host", self.host, "Object")
        put(row, "Heater", heater, "Object")
        row.call_method("Present", args=("Unchanged fixture", 37, 100, 0.37, True, "Sentinel tooltip"))
        self.host.get_editor_property("Rows").append(row)
        self.rows_box.add_child_to_vertical_box(row)
        return row

    def make_heaters(self):
        systems = self.spawn(native("ArcoSystems"))
        grid = self.spawn(native("GridActor"))
        put(self.host, "Systems", systems, "Object")
        put(grid, "isPlayerOwned", True)
        self.registry = systems.get_editor_property("m_worldMeta").get_editor_property("m_fueledHeaters_components")
        for _ in range(3):
            heater = unreal.new_object(native("FueledHeater"), outer=grid)
            self.components.append(heater)
            put(heater, "m_fuelSource", 2, "Byte")
            assert self.host.call_method("IsCampfire", args=(heater,)), "Fixture must pass the real campfire filter"
        return self.components

    def members(self, values):
        self.registry.clear()
        for value in values:
            self.registry.add(value)

    def close(self):
        self.rows_box.clear_children()
        self.host.get_editor_property("Rows").clear()
        for obj in reversed(self.created):
            actors.destroy_actor(obj)


def guarded_update(expanded=True, visible=True, shutdown=False, valid_panel=True):
    fixture = Fixture()
    try:
        host, panel = fixture.host, fixture.panel
        row = fixture.row()
        put(panel, "Expanded", expanded)
        put(panel, "GameplayVisible", visible)
        put(host, "ShuttingDown", shutdown)
        put(host, "AnyRefill", True)
        put(host, "AppliedUnits", 17, "Int")
        put(host, "RefilledHeaters", 5, "Int")
        panel.call_method("SetCanRefill", args=(True,))
        if not valid_panel:
            put(host, "Panel", None, "Object")
        before_rows = list(host.get_editor_property("Rows"))
        result = host.call_method("UpdateRows")
        assert result is False, "Hidden, closed, invalid or shutting-down panel must skip UpdateRows"
        assert host.get_editor_property("AnyRefill"), "Skipped update must preserve refill availability"
        assert host.get_editor_property("AppliedUnits") == 17
        assert host.get_editor_property("RefilledHeaters") == 5
        assert not host.get_editor_property("Busy")
        assert not host.get_editor_property("Failed")
        assert list(host.get_editor_property("Rows")) == before_rows
        assert panel.get_editor_property("AllButton").get_is_enabled(), "Skipped update must not change the bulk button"
        assert str(row.get_editor_property("TitleText").get_text()) == "Unchanged fixture"
        assert str(row.get_editor_property("FuelText").get_text()) == "37 %"
        assert abs(row.get_editor_property("FuelBar").get_editor_property("percent") - 0.37) < 0.00001
    finally:
        fixture.close()


def test_closed_panel_skips_row_update():
    guarded_update(expanded=False)


def test_hidden_gameplay_skips_row_update():
    guarded_update(visible=False)


def test_shutdown_skips_row_update():
    guarded_update(shutdown=True)


def test_invalid_panel_skips_row_update():
    guarded_update(valid_panel=False)


def test_visible_empty_panel_still_updates_availability():
    fixture = Fixture()
    try:
        put(fixture.panel, "Expanded", True)
        put(fixture.panel, "GameplayVisible", True)
        put(fixture.host, "AnyRefill", True)
        fixture.panel.call_method("SetCanRefill", args=(True,))
        assert fixture.host.call_method("UpdateRows") is True
        assert not fixture.host.get_editor_property("AnyRefill")
        assert not fixture.panel.get_editor_property("AllButton").get_is_enabled()
    finally:
        fixture.close()


def test_open_button_requests_next_poll_without_running_pump():
    fixture = Fixture()
    try:
        host, panel = fixture.host, fixture.panel
        panel.call_method("ApplyGameplayVisibility", args=(True,))
        put(host, "HasClock", True)
        before_poll = host.get_editor_property("LastPoll")
        panel.get_editor_property("ToggleButton").on_clicked.broadcast()
        assert panel.get_editor_property("Expanded")
        assert panel.get_editor_property("GameplayVisible"), "Opening must not synchronously run editor-world Pump"
        assert not host.get_editor_property("HasClock"), "Opening must request an immediate next-tick poll"
        assert host.get_editor_property("LastPoll") == before_poll, "Requesting a poll must not execute it"
        put(host, "HasClock", True)
        panel.get_editor_property("ToggleButton").on_clicked.broadcast()
        assert not panel.get_editor_property("Expanded")
        assert host.get_editor_property("HasClock"), "Closing must not request a row refresh"
    finally:
        fixture.close()


def test_restoring_expanded_panel_requests_only_one_poll():
    fixture = Fixture()
    try:
        host, panel = fixture.host, fixture.panel
        put(panel, "Expanded", True)
        put(host, "HasClock", True)
        panel.call_method("ApplyGameplayVisibility", args=(True,))
        assert panel.get_editor_property("GameplayVisible")
        assert not host.get_editor_property("HasClock"), "Restoring expanded gameplay must request the next poll"
        put(host, "HasClock", True)
        panel.call_method("ApplyGameplayVisibility", args=(True,))
        assert host.get_editor_property("HasClock"), "Unchanged visibility must not defeat the one-second throttle"
        panel.call_method("ApplyGameplayVisibility", args=(False,))
        assert host.get_editor_property("HasClock"), "Hiding must not request a row refresh"
    finally:
        fixture.close()


def test_collapsed_restore_and_hidden_open_do_not_request_poll():
    fixture = Fixture()
    try:
        host, panel = fixture.host, fixture.panel
        put(host, "HasClock", True)
        panel.call_method("ApplyGameplayVisibility", args=(True,))
        assert host.get_editor_property("HasClock"), "Restoring only the icon must preserve the polling clock"
        panel.call_method("ApplyGameplayVisibility", args=(False,))
        panel.get_editor_property("ToggleButton").on_clicked.broadcast()
        assert panel.get_editor_property("Expanded")
        assert host.get_editor_property("HasClock"), "A hidden panel must not request a presentation refresh"
    finally:
        fixture.close()


def test_panel_without_host_remains_safe():
    panel = factory.call_method("Create", args=(world, classes["WBP_CampfirePanel"], None))
    assert panel and not panel.get_editor_property("Host")
    panel.call_method("ApplyGameplayVisibility", args=(True,))
    panel.get_editor_property("ToggleButton").on_clicked.broadcast()
    assert panel.get_editor_property("Expanded")
    panel.call_method("ApplyGameplayVisibility", args=(False,))
    panel.call_method("ApplyGameplayVisibility", args=(True,))
    assert panel.get_editor_property("Expanded")
    assert panel.get_editor_property("GameplayVisible")
    assert not panel.get_editor_property("Host")


def assert_members(fixture, expected):
    host = fixture.host
    assert host.call_method("RefreshList") is True
    actual = list(host.get_editor_property("Heaters"))
    rows = list(host.get_editor_property("Rows"))
    assert len(actual) == len(expected) and set(actual) == set(expected), "RefreshList must track exact campfire membership"
    assert len(rows) == len(expected)
    assert fixture.rows_box.get_children_count() == len(expected)
    assert [row.get_editor_property("Heater") for row in rows] == actual, "Rows must stay mapped to their actual campfires"
    return actual, rows


def membership_transition(before, after):
    fixture = Fixture()
    try:
        components = fixture.make_heaters()
        fixture.members([components[i] for i in before])
        assert_members(fixture, [components[i] for i in before])
        fixture.members([components[i] for i in after])
        assert_members(fixture, [components[i] for i in after])
    finally:
        fixture.close()


def test_equal_count_replacement_rebuilds_correct_members():
    membership_transition((0, 1), (0, 2))


def test_membership_addition():
    membership_transition((0,), (0, 1))


def test_membership_removal():
    membership_transition((0, 1), (1,))


def test_removal_of_last_member_clears_rows():
    membership_transition((0,), ())


def test_empty_membership_remains_empty():
    membership_transition((), ())


def test_same_membership_preserves_old_order_and_row_instances():
    fixture = Fixture()
    try:
        components = fixture.make_heaters()
        fixture.members(components)
        # Deliberately give the existing UI the opposite order from this set.
        # This does not rely on Unreal's unspecified set enumeration order.
        old_order = list(reversed(list(fixture.registry)))
        replace_array(fixture.host.get_editor_property("Heaters"), old_order)
        old_rows = [fixture.row(heater) for heater in old_order]
        assert old_order != list(fixture.registry)
        actual, rows = assert_members(fixture, components)
        assert actual == old_order, "Unchanged membership must preserve the displayed campfire numbering/order"
        assert rows == old_rows, "Unchanged membership must reuse existing row widgets"
        actual, rows = assert_members(fixture, components)
        assert actual == old_order and rows == old_rows, "Repeated polls must remain stable"
    finally:
        fixture.close()


failures = []
tests = [value for name, value in list(globals().items()) if name.startswith("test_") and callable(value)]
for test in tests:
    try:
        test()
        unreal.log("CAMPFIRE_PERFORMANCE_PASS " + test.__name__)
    except Exception as error:
        detail = str(error) if isinstance(error, AssertionError) else traceback.format_exc()
        failures.append(test.__name__ + ": " + detail)
        unreal.log_warning("CAMPFIRE_PERFORMANCE_FAIL " + failures[-1])
assert not failures, "\n".join(failures)
unreal.log("CAMPFIRE_PERFORMANCE_TESTS_PASS: visibility guards, deferred refresh and exact stable membership; no gameplay or asset saves")

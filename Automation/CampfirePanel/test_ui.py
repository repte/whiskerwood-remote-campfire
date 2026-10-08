"""Exercise compiled UMG visibility and native HUD fixtures, without refilling."""
import unreal
from editor_toolset.toolsets.blueprint import BlueprintTools as BP

ROOT = "/Game/Mods/CampfirePanel/"
put = lambda obj, key, value: obj.set_editor_property(
    key, value, notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)


def test_panel():
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    cls = unreal.load_class(None, ROOT + "WBP_CampfirePanel.WBP_CampfirePanel_C")
    factory = unreal.get_default_object(unreal.load_class(None, "/Script/UMG.WidgetBlueprintLibrary"))
    widget = factory.call_method("Create", args=(world, cls, None))
    panel = widget.get_editor_property("PanelCanvas")
    assert panel.get_visibility() == unreal.SlateVisibility.COLLAPSED, "Initial list must be collapsed"
    assert not widget.get_editor_property("Expanded")
    assert widget.get_visibility() == unreal.SlateVisibility.COLLAPSED, "No UI before gameplay is ready"
    widget.call_method("ApplyGameplayVisibility", args=(True,))
    assert widget.get_visibility() == unreal.SlateVisibility.SELF_HIT_TEST_INVISIBLE
    assert widget.get_editor_property("ToggleButton").get_is_enabled()
    assert panel.get_visibility() == unreal.SlateVisibility.COLLAPSED
    widget.get_editor_property("ToggleButton").on_clicked.broadcast()
    assert widget.get_editor_property("Expanded"), "Actual icon click must open the list"
    assert panel.get_visibility() == unreal.SlateVisibility.SELF_HIT_TEST_INVISIBLE
    put(widget, "PanelX", 240.0)
    put(widget, "PanelY", 180.0)
    put(widget, "Dragging", True)
    widget.call_method("ApplyGameplayVisibility", args=(False,))
    assert widget.get_visibility() == unreal.SlateVisibility.COLLAPSED
    assert not widget.get_editor_property("Dragging"), "Opening a menu must release drag state"
    assert widget.get_editor_property("Expanded"), "Menu must preserve user's expanded choice"
    widget.call_method("ApplyGameplayVisibility", args=(True,))
    assert panel.get_visibility() == unreal.SlateVisibility.SELF_HIT_TEST_INVISIBLE
    assert widget.get_editor_property("PanelX") == 240.0
    assert widget.get_editor_property("PanelY") == 180.0
    widget.get_editor_property("ToggleButton").on_clicked.broadcast()
    assert not widget.get_editor_property("Expanded")
    assert panel.get_visibility() == unreal.SlateVisibility.COLLAPSED
    widget.call_method("ApplyGameplayVisibility", args=(False,))
    widget.call_method("ApplyGameplayVisibility", args=(True,))
    assert panel.get_visibility() == unreal.SlateVisibility.COLLAPSED, "Closed list must stay closed across menus"
    assert not widget.get_editor_property("Host"), "Visibility must never require or trigger refilling"


def test_native_hud():
    bp = unreal.load_asset(ROOT + "BP_MapLoad")
    assert "HudAllowsDisplay" in {str(g.get_name()) for g in BP.list_graphs(bp)}, "Gameplay HUD visibility guard is missing"
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    factory = unreal.get_default_object(unreal.load_class(None, "/Script/UMG.WidgetBlueprintLibrary"))
    panel_class = unreal.load_class(None, ROOT + "WBP_CampfirePanel.WBP_CampfirePanel_C")
    panel = factory.call_method("Create", args=(world, panel_class, None))
    panel.call_method("ApplyGameplayVisibility", args=(True,))
    actor = actors.spawn_actor_from_class(bp.generated_class(), unreal.Vector(0, 0, -100000))
    # Seed the defaults-only member on this transient fixture, without changing its CDO.
    system = unreal.get_default_object(unreal.load_class(None, "/Script/Engine.KismetSystemLibrary"))
    system.call_method("SetObjectPropertyByName", args=(actor, "Panel", panel))
    assert actor.get_editor_property("Panel") == panel, "Fixture must hold the provided native widget"
    native = lambda name: unreal.load_class(None, "/Script/ProjectArco." + name)
    transform = unreal.Transform()
    gameplay = unreal.get_default_object(unreal.GameplayStatics)
    controller = gameplay.call_method("BeginDeferredActorSpawnFromClass", args=(
        actor, native("PlayerController_Play"), transform,
        unreal.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN, None,
        unreal.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT))
    controller = gameplay.call_method("FinishSpawningActor", args=(
        controller, transform, unreal.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT))
    hud = unreal.new_object(native("PlayHud"))

    def check(h=hud, p=controller):
        return actor.call_method("HudAllowsDisplay", args=(h, p))

    def player(key, value):
        state = controller.get_editor_property("m_state")
        put(state, key, value)
        put(controller, "m_state", state)

    def state(key, value, nested=None):
        target = hud.get_editor_property("m_hudState")
        field = f"{key}={'True' if value else 'False'}"
        assert target.import_text(f"({nested}=({field}))" if nested else f"({field})")

    try:
        assert not actor.call_method("SyncPanelVisibility"), "Editor world is not a gameplay session"
        assert panel.get_visibility() == unreal.SlateVisibility.COLLAPSED, "Leaving the gameplay world must hide existing UI"
        assert not check(None, controller)
        assert not check(hud, None)
        put(hud, "m_uiHasFadedIn", True)
        player("m_showHud", True)
        player("m_dev_hideAllHud", False)
        player("m_showReplayMenu", False)
        player("activeArcoView", None)
        state("showHudRoot", True, "sectionVisibilities")
        state("showSaving", False)
        state("victoryPending", False)
        assert check(), "Normal gameplay must show the icon"
        state("IsPaused", True, "TimeHudState")
        assert check(), "Normal simulation pause must not hide the icon"
        state("isPausedByEod", True, "TimeHudState")
        state("eodPending", True)
        assert check(), "Day-end pause still allows manual campfire use"
        state("victoryPending", True)
        assert check(), "Available victory action is not an open menu"
        state("showSaving", True)
        assert not check(), "Saving overlay must hide the mod UI"
        state("showSaving", False)
        for key, blocked, allowed in (("m_showHud", False, True),
                                     ("m_dev_hideAllHud", True, False),
                                     ("m_showReplayMenu", True, False)):
            player(key, blocked)
            assert not check(), "Missing player guard: " + key
            player(key, allowed)
            assert check()
        view = unreal.new_object(native("ArcoView"))
        player("activeArcoView", view)
        assert not check(), "Open game views must hide the mod UI"
        player("activeArcoView", None)
        state("showHudRoot", False, "sectionVisibilities")
        assert not check(), "Hidden game layer must hide the mod UI"
        state("showHudRoot", True, "sectionVisibilities")
        put(hud, "m_uiHasFadedIn", False)
        assert not check(), "Loading/fading HUD must hide the mod UI"
        put(hud, "m_uiHasFadedIn", True)
        assert check()
    finally:
        actors.destroy_actor(controller)
        actors.destroy_actor(actor)


def test_fuel_presentation():
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    cls = unreal.load_class(None, ROOT + "WBP_CampfireRow.WBP_CampfireRow_C")
    factory = unreal.get_default_object(unreal.load_class(None, "/Script/UMG.WidgetBlueprintLibrary"))
    row = factory.call_method("Create", args=(world, cls, None))
    colors = []
    for percent in (0.1, 0.3, 0.9):
        assert row.call_method("Present", args=("Lagerfeuer 1", int(percent * 100), 100,
                                               percent, True, "Auffuellen"))
        bar = row.get_editor_property("FuelBar")
        fill = bar.get_editor_property("fill_color_and_opacity")
        text = row.get_editor_property("FuelText").get_editor_property("color_and_opacity").get_editor_property("specified_color")
        colors.append(tuple(round(getattr(fill, c), 5) for c in ("r", "g", "b")))
        assert all(abs(getattr(text, c) - getattr(fill, c)) < 1e-5 for c in ("r", "g", "b")), "Percentage and bar must agree about fuel warning"
        assert abs(bar.get_editor_property("percent") - percent) < 1e-5
    assert len(set(colors)) == 3, "Critical, low and healthy fuel must be distinguishable"
    row.call_method("Present", args=("Lagerfeuer 1", 100, 100, 1.2, False, "Voll"))
    assert row.get_editor_property("FuelBar").get_editor_property("percent") == 1.0
    assert not row.get_editor_property("RefreshButton").get_is_enabled()
    row.call_method("Present", args=("Lagerfeuer 1", 0, 100, -0.1, False, "Leer"))
    assert row.get_editor_property("FuelBar").get_editor_property("percent") == 0.0


failures = []
for test in (test_panel, test_native_hud, test_fuel_presentation):
    try:
        test()
        unreal.log("CAMPFIRE_UI_PASS " + test.__name__)
    except AssertionError as error:
        failures.append(test.__name__ + ": " + str(error))
        unreal.log_warning("CAMPFIRE_UI_FAIL " + failures[-1])
assert not failures, "; ".join(failures)
unreal.log("CAMPFIRE_UI_TESTS_PASS: compiled UMG toggle and native HUD visibility; no refill performed")

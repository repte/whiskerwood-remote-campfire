"""Exercise compiled translations and relabeling without refilling campfires."""
import json
from pathlib import Path

import unreal
from editor_toolset.toolsets.blueprint import BlueprintTools as BP


ROOT = "/Game/Mods/CampfirePanel/"
catalog = json.loads(Path(__file__).with_name("translations.json").read_text(encoding="utf-8"))
bp = unreal.load_asset(ROOT + "BP_MapLoad")
graphs = {str(graph.get_name()) for graph in BP.list_graphs(bp)}
assert {"Localize", "Text", "RowTitle", "SetLanguage", "RefreshLanguage", "RenderStatus"} <= graphs, (
    "Compiled campfire localization is missing", graphs)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actor = actors.spawn_actor_from_class(bp.generated_class(), unreal.Vector(0, 0, -100000))
system = unreal.get_default_object(unreal.load_class(None, "/Script/Engine.KismetSystemLibrary"))


def put(key, value):
    kind = "Bool" if isinstance(value, bool) else "Int"
    system.call_method("Set" + kind + "PropertyByName", args=(actor, key, value))
    assert actor.get_editor_property(key) == value, (key, value)


try:
    for column, language in enumerate(catalog["languages"]):
        for key, translations in catalog["strings"].items():
            actual = actor.call_method("Localize", args=(key, language))
            assert actual == translations[column], (key, language, actual)
    for language, base in (("de-AT", "de"), ("ZH_tw", "zh-tw"),
                           ("zh-TW-extra", "zh-tw"), ("es_MX", "es-mx"),
                           ("pt-BR", "pt"), ("ua", "ua"), ("unknown", "en"),
                           ("", "en"), ("nl", "en")):
        for key, translations in catalog["strings"].items():
            assert actor.call_method("Localize", args=(key, language)) == translations[catalog["languages"].index(base)], (key, language)
    assert actor.call_method("Localize", args=("unknown.key", "de")) == "unknown.key"

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    factory = unreal.get_default_object(unreal.load_class(None, "/Script/UMG.WidgetBlueprintLibrary"))
    cls = unreal.load_class(None, ROOT + "WBP_CampfirePanel.WBP_CampfirePanel_C")
    panel = factory.call_method("Create", args=(world, cls, None))
    row_cls = unreal.load_class(None, ROOT + "WBP_CampfireRow.WBP_CampfireRow_C")
    row = factory.call_method("Create", args=(world, row_cls, None))
    # The returned array references this transient instance, not its class defaults.
    rows = actor.get_editor_property("Rows")
    rows.append(row)
    assert list(actor.get_editor_property("Rows")) == [row]
    system.call_method("SetObjectPropertyByName", args=(actor, "Panel", panel))
    panel.call_method("ApplyGameplayVisibility", args=(True,))
    panel.get_editor_property("ToggleButton").on_clicked.broadcast()
    put("RefilledHeaters", 123)
    put("AppliedUnits", 456)
    actor.call_method("Status", args=("summary",))
    for column, language in enumerate(catalog["languages"]):
        actor.call_method("SetLanguage", args=(language,))
        expected = lambda key: catalog["strings"][key][column]
        assert str(panel.get_editor_property("PanelTitle").get_text()) == expected("title")
        assert str(panel.get_editor_property("RefreshAllText").get_text()) == expected("refill_all")
        assert str(panel.get_editor_property("ToggleButton").get_editor_property("tool_tip_text")) == expected("title")
        assert str(row.get_editor_property("TitleText").get_text()) == expected("row_name").format(number=1)
        assert str(row.get_editor_property("RefreshButton").get_editor_property("tool_tip_text")) == expected("refill")
        assert actor.call_method("RowTitle", args=(122,)) == expected("row_name").format(number=123)
        assert str(panel.get_editor_property("StatusText").get_text()) == expected("summary").format(count=123, wood=456)
        assert panel.get_editor_property("Expanded"), "Language changes must preserve the open list"
        assert not actor.get_editor_property("Busy"), "Relabeling must not start a refill"
        assert not actor.get_editor_property("Failed"), "Relabeling must not change refill safety"
    actor.call_method("Status", args=("failed",))
    put("Failed", True)
    actor.call_method("SetLanguage", args=("de",))
    assert str(panel.get_editor_property("StatusText").get_text()) == catalog["strings"]["failed"][catalog["languages"].index("de")]
    actor.call_method("Status", args=("",))
    assert str(panel.get_editor_property("StatusText").get_text()) == ""
    assert actor.get_editor_property("Failed"), "Relabeling must not clear a refill failure"
finally:
    actors.destroy_actor(actor)

unreal.log("CAMPFIRE_LOCALIZATION_TESTS_PASS: 17 languages, regional lookup, fallback and existing status relabeling")

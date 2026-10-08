"""Author Remote Campfire; no native runtime module ships.

Run inside the modkit editor. The editor-only bridge authors ordinary Blueprint
member writes and existing native calls, then disappears from the cooked mod.
"""
import json
from functools import lru_cache
import os
from pathlib import Path
import re
import runpy

import unreal
import toolset_registry
from editor_toolset.toolsets.blueprint import BlueprintTools as BP, ContainerType
from editor_toolset.toolsets import blueprint_dsl


ROOT = "/Game/Mods/CampfirePanel"
HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / "translations.json").read_text(encoding="utf-8"))
LANGUAGES = CATALOG["languages"]
STRINGS = CATALOG["strings"]
native = lambda name: unreal.load_class(None, "/Script/ProjectArco." + name)
g = lambda name: f"(Variables|Default|Get{name})"
put = lambda name, value: f"(Variables|Default|Set{name} {value})"
valid = lambda value: f"(CallFunction|HasObject :Object {value})"
at = lambda array, index: f'(Utilities|Array|Get(acopy) :Array {array} :"Dimension 1" {index})'
number = lambda value, kind="Integer": f"(Utilities|String|ToString({kind}) {value})"


def append(*values):
    result = values[0]
    for value in values[1:]:
        result = f"(Utilities|String|Append :A {result} :B {value})"
    return result


def clear_body(graph):
    kept_result = False
    for node in BP.find_nodes(graph):
        kind = node.get_class().get_name()
        if kind == "K2Node_FunctionEntry":
            continue
        if kind == "K2Node_FunctionResult" and not kept_result:
            kept_result = True
            for pin in BP.get_node_infos([node])[0].input_pins:
                for other in pin.connected_pins:
                    BP.break_pins(other, pin.pin_id)
            continue
        BP.delete_node(node)


with toolset_registry.tool_raising_exceptions():
    access = json.loads(unreal.CampfireAuthoringProbe.enable_authoring())
    assert access.get("success"), access
    bp = unreal.load_asset(ROOT + "/BP_MapLoad")
    if bp is None:
        bp = BP.create(ROOT, "BP_MapLoad", unreal.Actor.static_class())
    assert BP.get_parent(bp) == unreal.Actor.static_class()
    if "Log" in {str(graph.get_name()) for graph in BP.list_graphs(bp)}:
        BP.remove_function_graph(bp, "Log")
    types = {
        "Heater": native("FueledHeater"), "Systems": native("ArcoSystems"),
        "Warehouse": native("GranaryResourceBuilding"),
        "API": unreal.load_class(None, "/Script/SystemCore.ModAPI"),
    }
    for name, kind in {"API": types["API"], "Systems": types["Systems"],
                       "SelectedSource": types["Warehouse"], "SavedPrimary": types["Warehouse"]}.items():
        if name not in BP.list_variables(bp):
            BP.add_object_variable(bp, name, kind)
    for kind, names in {
        "bool": "Busy Failed ShuttingDown Initialized HasClock AnyRefill Available LastFillSuccess VersionChecked VersionAccepted",
        "real": "LastPoll BestDistance",
        "int": "AppliedUnits RefilledHeaters BaseDuration BeforeBank BeforeStock",
        "string": "LastStatus CurrentLanguage",
    }.items():
        for name in names.split():
            if name not in BP.list_variables(bp):
                BP.add_variable(bp, name, kind)
    for name in ("TextKeys", "TextValues"):
        if name not in BP.list_variables(bp):
            BP.add_variable(bp, name, "string", container_type=ContainerType.ARRAY)
    # "float" aliases to double in BlueprintTools; copy a native float pin type.
    float_type = unreal.BlueprintEditorLibrary.get_member_variable_type(
        bp, "/Script/Engine.Actor.InitialLifeSpan")
    assert float_type is not None, "Native single-precision type is unavailable"
    for name in ("FloatScratch", "BurnScratch", "BeforeFuel"):
        current = unreal.BlueprintEditorLibrary.get_member_variable_type(bp, name)
        if current is None:
            assert unreal.BlueprintEditorLibrary.add_member_variable(bp, name, float_type)
        elif current != float_type:
            unreal.BlueprintEditorLibrary.change_member_variable_type(bp, name, float_type)
    for name in ("Heaters", "CurrentHeaters"):
        if name not in BP.list_variables(bp):
            BP.add_object_variable(bp, name, types["Heater"], container_type=ContainerType.ARRAY)
    if "HeaterMembership" not in BP.list_variables(bp):
        BP.add_object_variable(bp, "HeaterMembership", types["Heater"], container_type=ContainerType.SET)

    definitions = {
        "HasObject": ([("Object", unreal.Object.static_class())], "bool"),
        "Status": ([("Message", "string")], "bool"),
        "Localize": ([("Key", "string"), ("Language", "string")], "string"),
        "Text": ([("Key", "string")], "string"),
        "RowTitle": ([("Index", "int")], "string"),
        "SetLanguage": ([("Language", "string")], "bool"),
        "RefreshLanguage": ([], "bool"), "RenderStatus": ([], "bool"),
        "Ready": ([], "bool"), "Pump": ([], "bool"), "Shutdown": ([], "bool"),
        "IsCampfire": ([("Heater", types["Heater"])], "bool"),
        "Duration": ([("Heater", types["Heater"])], "int"),
        "WoodIn": ([("Warehouse", types["Warehouse"])], "int"),
        "FindSource": ([("Heater", types["Heater"])], "bool"),
        "RefillUnit": ([("Heater", types["Heater"])], "bool"),
        "FillHeater": ([("Heater", types["Heater"])], "bool"),
        "RefillOne": ([("Heater", types["Heater"])], "bool"),
        "RefillAll": ([], "bool"), "RefreshList": ([], "bool"),
        "UpdateRows": ([], "bool"), "CreatePanel": ([], "bool"), "RequestRefresh": ([], "bool"),
        "HudAllowsDisplay": ([("InputHud", native("PlayHud")),
                              ("InputController", native("PlayerController_Play"))], "bool"),
        "SyncPanelVisibility": ([], "bool"),
    }
    graphs = {}
    existing = {str(graph.get_name()) for graph in BP.list_graphs(bp)}
    for name, (params, result) in definitions.items():
        graph = BP.get_graph(bp, name) if name in existing else BP.add_function_graph(bp, name)
        graphs[name] = graph
        if name not in existing:
            for param, kind in params:
                if isinstance(kind, str):
                    BP.add_function_param(graph, param, kind, True)
                else:
                    BP.add_object_function_param(graph, param, kind, True)
            BP.add_function_param(graph, "Result" if result == "bool" else "Value", result, False)
        # Existing getter/setter pins still carry the previous numeric type.
        clear_body(graph)
    bridge_names = {"CfSetPrimaryWarehouse", "CfSetBurnTime", "CfGrantWood",
                    "CfReadConstructionStats", "CfRestoreConstructionStats"}
    for name in existing & bridge_names:
        BP.remove_function_graph(bp, name)
    report = json.loads(unreal.CampfireAuthoringProbe.add_runtime_bridge(bp))
    assert report.get("success"), report
    BP.compile_blueprint(bp)
    assert unreal.EditorAssetLibrary.save_loaded_asset(bp)
    if os.environ.get("CAMPFIRE_REUSE_UI") != "1":
        runpy.run_path(str(HERE / "generate_ui.py"), run_name="__main__")
    panel_class = unreal.load_class(None, ROOT + "/WBP_CampfirePanel.WBP_CampfirePanel_C")
    row_class = unreal.load_class(None, ROOT + "/WBP_CampfireRow.WBP_CampfireRow_C")
    if "Panel" not in BP.list_variables(bp):
        BP.add_object_variable(bp, "Panel", panel_class)
    if "Rows" not in BP.list_variables(bp):
        BP.add_object_variable(bp, "Rows", row_class, container_type=ContainerType.ARRAY)
    BP.compile_blueprint(bp)
    context = graphs["Pump"]
    nodes = list(dict.fromkeys(BP.find_node_types(context, "", [])))
    normalize = lambda value: re.sub("[^a-z0-9]", "", str(value).lower())

    @lru_cache(maxsize=None)
    def node(method, owner=None):
        matches = [item for item in nodes
                   if normalize(item.rsplit("|", 1)[-1].split("(", 1)[0]) == normalize(method)]
        if owner:
            matches = [item for item in matches if any(
                normalize(pin.type_id) == normalize(owner) + "objectreference"
                for pin in BP.get_node_type_pins(context, item).input_pins
                if pin.name in ("self", "Target"))]
        if method == "DistanceSquared":
            matches = [item for item in matches if any(
                normalize(pin.type_id) == "vector" for pin in BP.get_node_type_pins(context, item).input_pins)]
        if method == "Truncate":
            matches = [item for item in matches if item.endswith("|Truncate")]
        preferred = [item for item in matches if not item.startswith("Class|")]
        matches = preferred or matches
        assert len(matches) == 1, (method, owner, matches)
        return matches[0]

    def invoke(method, owner, target, args=""):
        return f"({node(method, owner)} :self {target} {args})"

    def prop(owner, target, name):
        return invoke("Get" + name, owner, target)

    def setprop(owner, target, name, value):
        return invoke("Set" + name, owner, target, ":" + name + " " + value)

    def unpack(struct, value, prefix):
        kind = "Utilities|Struct|Break" + struct
        names = [prefix + str(pin.name) for pin in BP.get_node_type_pins(context, kind).output_pins]
        return f"(bind ({' '.join(names)}) ({kind} {value}))"

    def scalar(method, owner, target, value):
        kind = node(method, owner)
        pins = [pin.name for pin in BP.get_node_type_pins(context, kind).input_pins
                if pin.name not in ("self", "Target", "execute")]
        assert len(pins) == 1, (method, pins)
        return f"({kind} :self {target} :{pins[0]} {value})"

    def trunc(value):
        return f"({node('Truncate')} :A {value})"

    heater_prop = lambda name, target="Heater": prop("FueledHeater", target, "M" + name)
    systems_prop = lambda name: prop("ArcoSystems", g("Systems"), "M" + name)
    bank = systems_prop("PlayerBank")
    wood = lambda: invoke("GetResourceCount", "PlayerBank", bank, ':Resource "wood"')
    burn = lambda: heater_prop("BurnTimeRemaining")
    can_refill = lambda target="Heater": invoke("CanAddExternalFuel", "FueledHeater", target)
    owner = lambda value: invoke("GetOwner", "ActorComponent", value)
    location = lambda value: invoke("GetActorLocation", "Actor", value)
    panel_call = lambda fn, args="": invoke(fn, "WBPCampfirePanel", g("Panel"), args)
    row_call = lambda fn, target, args="": invoke(fn, "WBPCampfireRow", target, args)
    world = lambda prefix: unpack("WorldMeta", systems_prop("WorldMeta"), prefix)
    accepted_versions = [prefix + version for prefix in ("", "v", "Early Access ", "Early Access v")
                         for version in ("0.7.209", "0.7.209.0")]
    enum_patches = {}
    code = {}
    exact, regional = [], []
    for index, language in enumerate(LANGUAGES):
        value = at(g("TextValues"), f"(+ (* index {len(LANGUAGES)}) {index})")
        exact.append(f'(if (Utilities|String|EqualExactly(String) normalized "{language}") (return {value}))')
    for language in sorted(LANGUAGES, key=len, reverse=True):
        value = at(g("TextValues"), f"(+ (* index {len(LANGUAGES)}) {LANGUAGES.index(language)})")
        regional.append(f'(if (Utilities|String|StartsWith :SourceString normalized :InPrefix "{language}-") (return {value}))')
    code["Localize"] = f'''(fn Localize (Key Language)
        (bind index (Utilities|Array|FindItem {g('TextKeys')} Key))
        (if (< index 0) (return Key))
        (bind normalized (Utilities|String|Replace :SourceString (Utilities|String|ToLower Language) :From "_" :To "-" :SearchCase "CaseSensitive"))
        {' '.join(exact)} {' '.join(regional)}
        (return {at(g('TextValues'), f'(* index {len(LANGUAGES)})')}))'''
    code["Text"] = f'''(fn Text (Key)
        (bind translated (CallFunction|Localize :Key Key :Language {g('CurrentLanguage')})) (return translated))'''
    tr = lambda key: f'(CallFunction|Text :Key "{key}")'
    code["RowTitle"] = f'''(fn RowTitle (Index)
        (bind title (Utilities|String|Replace :SourceString {tr('row_name')} :From "{{number}}" :To {number('(+ Index 1)')} :SearchCase "CaseSensitive"))
        (return title))'''
    code["SetLanguage"] = f'''(fn SetLanguage (Language)
        {put('CurrentLanguage', 'Language')}
        (if {valid(g('Panel'))}
          {panel_call('ApplyLabels', ':Title ' + tr('title') + ' :RefillAll ' + tr('refill_all'))}
          (CallFunction|RenderStatus))
        (for index (range (Utilities|Array|Length {g('Rows')}))
          (bind row {at(g('Rows'), 'index')})
          (if {valid('row')}
            {row_call('SetLabels', 'row', ':Title (CallFunction|RowTitle :Index index) :Detail ' + tr('refill'))}))
        (return true))'''
    code["RefreshLanguage"] = f'''(fn RefreshLanguage ()
        (bind manager (Class|Backbone|GetLocManager))
        (if (not {valid('manager')}) (return false))
        (bind language (Utilities|String|ToString(Name) (Class|LocManager|GetActiveLanguage :self manager)))
        (if (Utilities|String|EqualExactly(String) language {g('CurrentLanguage')}) (return true))
        (CallFunction|SetLanguage :Language language) (return true))'''
    code["RenderStatus"] = f'''(fn RenderStatus ()
        (if (not {valid(g('Panel'))}) (return false))
        (bind message (CallFunction|Text :Key {g('LastStatus')}))
        (bind counts (Utilities|String|Replace :SourceString message :From "{{count}}" :To {number(g('RefilledHeaters'))} :SearchCase "CaseSensitive"))
        (bind rendered (Utilities|String|Replace :SourceString counts :From "{{wood}}" :To {number(g('AppliedUnits'))} :SearchCase "CaseSensitive"))
        {panel_call('SetStatus', ':Message rendered')} (return true))'''
    code["HasObject"] = '(fn HasObject (Object) (Utilities|IsValid Object (:"Is Valid" (return true)) (:"Is Not Valid" (return false))))'
    code["Status"] = f'''(fn Status (Message)
        {put('LastStatus', 'Message')}
        (CallFunction|RenderStatus) (return true))'''
    code["Ready"] = f'''(fn Ready ()
        (if (or {g('ShuttingDown')} {g('Failed')}) (return false))
        (if ({node('IsDevelopmentMode')}) (return false))
        (bind mode (Utilities|Casting|CastToProjectArcoGameModeBase :Object (Game|GetGameMode))
          (:then
            (bind phase (Class|ProjectArcoGameModeBase|CurrentInitPhase :self mode))
            (if (not (Utilities|Enum|Equal(Enum) :A phase)) (return false))
            (bind (found systems) (Class|ArcoSystems|GetArcoSys))
            (if (or (not found) (not {valid('systems')})) (return false))
            (if (not (Class|ArcoSystems|IsLive :self systems)) (return false))
            (if (not {g('VersionChecked')})
              (bind platform ({node('GetPlatformManager')}))
              (if (not {valid('platform')}) (return false))
              (bind version {prop('PlatformManager', 'platform', 'VersionLabel')})
              (if (Utilities|String|EqualExactly(String) version "") (return false))
              {put('VersionAccepted', 'false')}
              {' '.join('(if (Utilities|String|EqualExactly(String) version ' + json.dumps(label) + ') ' + put('VersionAccepted', 'true') + ')' for label in accepted_versions)}
              {put('VersionChecked', 'true')})
            (if (not {g('VersionAccepted')}) (return false))
            {put('Systems', 'systems')}
            (if (not {valid(bank)}) (return false))
            (bind player (Utilities|Casting|CastToPlayerController_Play :Object (Game|GetPlayerController :PlayerIndex 0))
              (:then
                {unpack('ArcoPlayerState', '(Class|PlayerControllerPlay|GetMState :self player)', 'ps_')}
                (if ps_m_showReplayMenu (return false))
                (return true))
              (:CastFailed (return false))))
          (:CastFailed (return false))))'''
    enum_patches["Ready"] = ["DONE"]
    code["HudAllowsDisplay"] = f'''(fn HudAllowsDisplay (InputHud InputController)
        (if (or (not {valid('InputHud')}) (not {valid('InputController')})) (return false))
        (if (not (Class|PlayHud|GetMUiHasFadedIn :self InputHud)) (return false))
        {unpack('ArcoPlayerState', '(Class|PlayerControllerPlay|GetMState :self InputController)', 'p_')}
        (if (or {valid('p_activeArcoView')} (or (not p_m_showHud) (or p_m_dev_hideAllHud p_m_showReplayMenu))) (return false))
        {unpack('HudState', '(Class|PlayHud|GetMHudState :self InputHud)', 'h_')}
        (if h_showSaving (return false))
        {unpack('VisibilityToggles', 'h_sectionVisibilities', 'v_')}
        (return v_showHudRoot))'''
    code["SyncPanelVisibility"] = f'''(fn SyncPanelVisibility ()
        (if (not {valid(g('Panel'))}) (return false))
        (bind mode (Utilities|Casting|CastToProjectArcoGameModeBase :Object (Game|GetGameMode))
          (:then
            (bind phase (Class|ProjectArcoGameModeBase|CurrentInitPhase :self mode))
            (if (or {g('ShuttingDown')} (not (Utilities|Enum|Equal(Enum) :A phase)))
              {panel_call('ApplyGameplayVisibility', ':Visible false')} (return false))
            (bind (found systems) (Class|ArcoSystems|GetArcoSys))
            (if (or (not found) (not {valid('systems')}))
              {panel_call('ApplyGameplayVisibility', ':Visible false')} (return false))
            (if (not (Class|ArcoSystems|IsLive :self systems))
              {panel_call('ApplyGameplayVisibility', ':Visible false')} (return false))
            (bind player (Utilities|Casting|CastToPlayerController_Play :Object (Game|GetPlayerController :PlayerIndex 0))
              (:then
                (bind visible (CallFunction|HudAllowsDisplay
                  :InputHud (Class|PlayerControllerPlay|GetMPlayHud :self player) :InputController player))
                {panel_call('ApplyGameplayVisibility', ':Visible visible')}
                (return visible))
              (:CastFailed {panel_call('ApplyGameplayVisibility', ':Visible false')} (return false))))
          (:CastFailed {panel_call('ApplyGameplayVisibility', ':Visible false')} (return false))))'''
    enum_patches["SyncPanelVisibility"] = ["DONE"]
    code["IsCampfire"] = f'''(fn IsCampfire (Heater)
        (if (not {valid('Heater')}) (return false))
        (if (not (Utilities|Enum|Equal(Enum) :A {heater_prop('FuelSource')})) (return false))
        (bind building {owner('Heater')}) (if (not {valid('building')}) (return false))
        (bind grid (Utilities|Casting|CastToGridActor :Object building)
          (:then (return {prop('GridActor', 'grid', 'IsPlayerOwned')}))
          (:CastFailed (return false))))'''
    enum_patches["IsCampfire"] = ["TEMPORARY"]
    code["Duration"] = f'''(fn Duration (Heater)
        (if (not {valid('Heater')}) (return 0))
        (bind seconds {heater_prop('FuelBurnTime')})
        (bind overdrive {heater_prop('HeatOverdrive')})
        (if (or (<= overdrive 0) (not (and (> seconds 0.0) (< seconds 10000000.0)))) (return 0))
        {put('BaseDuration', '(/ ' + trunc('seconds') + ' overdrive)')}
        (bind policies {systems_prop('Policies')})
        (if {valid('policies')}
          (for policy {prop('Policies', 'policies', 'MPolicySlots')}
            {unpack('ActivePolicySlot', 'policy', 'p_')}
            (if (== p_assignedPolicy "policy.dirtyfuel")
              {put('FloatScratch', '(* ' + g('BaseDuration') + ' 1.399999976158142)')}
              (return {trunc(g('FloatScratch'))}))))
        (return {g('BaseDuration')}))'''
    code["WoodIn"] = f'''(fn WoodIn (Warehouse)
        (if (not {valid('Warehouse')}) (return 0))
        {unpack('Stockpile', prop('ResourceBuilding', 'Warehouse', 'MStockpile'), 's_')}
        (bind (slot found) (Utilities|Map|Find s_Slots "wood"))
        (if (not found) (return 0))
        {unpack('ResourceStockpileSlot', 'slot', 'w_')}
        (return w_count))'''
    code["FindSource"] = f'''(fn FindSource (Heater)
        (Variables|Default|SetSelectedSource)
        {put('BestDistance', '1.0e30')}
        {world('w_')}
        (bind target {location(owner('Heater'))})
        (for source (Utilities|Set|ToArray w_granaryComponents)
          (if {valid('source')}
            (if {prop('ResourceBuilding', 'source', 'MAllowPlayerAccess')}
              (bind stored (CallFunction|WoodIn :Warehouse source))
              (if (> stored 0)
                (bind sourceActor {owner('source')})
                (if {valid('sourceActor')}
                  (bind distance ({node('DistanceSquared')} :V1 target :V2 {location('sourceActor')}))
                  (if (< distance {g('BestDistance')})
                    {put('BestDistance', 'distance')} {put('SelectedSource', 'source')}))))))
        (bind found {valid(g('SelectedSource'))}) (return found))'''
    code["RefillUnit"] = f'''(fn RefillUnit (Heater)
        (bind ready (CallFunction|Ready)) (if (not ready) (return false))
        (bind supported (CallFunction|IsCampfire :Heater Heater))
        (if (not supported) (return false))
        (if (not {can_refill()}) (return false))
        (bind effective (CallFunction|Duration :Heater Heater))
        {put('BeforeFuel', burn())}
        (if (or (<= effective 0) (not (and (>= {g('BeforeFuel')} 0.0) (< {g('BeforeFuel')} 10000000.0))))
          (return false))
        {put('BeforeBank', wood())} (if (< {g('BeforeBank')} 1) (return false))
        (bind sourceFound (CallFunction|FindSource :Heater Heater))
        (if (not sourceFound) (return false))
        (bind source {g('SelectedSource')})
        (bind beforeStock (CallFunction|WoodIn :Warehouse source))
        {put('BeforeStock', 'beforeStock')}
        (bind tracker {systems_prop('Statistics')})
        (if (not {valid('tracker')}) (return false))
        (bind dayIndex (- (Utilities|Array|Length {prop('StatisticsTracker', 'tracker', 'MCombinedStatsHistory')}) 1))
        (if (< dayIndex 0) (return false))
        (bind (hadConstruction savedConstruction) (CallFunction|CfReadConstructionStats :Tracker tracker :DayIndex dayIndex))
        {world('before_')}
        {put('SavedPrimary', 'before_primaryWarehouse')}
        {put('FloatScratch', '(* effective 0.33000001311302185)')}
        {put('BurnScratch', '(+ ' + g('BeforeFuel') + ' ' + g('FloatScratch') + ')')}
        (if (> {g('BurnScratch')} effective) {put('BurnScratch', 'effective')})
        (CallFunction|CfSetPrimaryWarehouse :Systems {g('Systems')} :Warehouse source)
        (CallFunction|CfGrantWood :ModApi {g('API')} :WorldContext self :Count -1)
        (CallFunction|CfSetPrimaryWarehouse :Systems {g('Systems')} :Warehouse {g('SavedPrimary')})
        (CallFunction|CfRestoreConstructionStats :Tracker tracker :DayIndex dayIndex :Found hadConstruction :Saved savedConstruction)
        (bind afterBank {wood()}) (bind afterStock (CallFunction|WoodIn :Warehouse source))
        (if (not (and (== afterBank (- {g('BeforeBank')} 1)) (or (== afterStock (- {g('BeforeStock')} 1)) (== afterStock {g('BeforeStock')}))))
          {put('Failed', 'true')}
          (CallFunction|Status :Message "failed")
          (return false))
        (CallFunction|CfSetBurnTime :Heater Heater :Remaining {g('BurnScratch')})
        (bind afterFuel {burn()})
        (if (!= afterFuel {g('BurnScratch')})
          {put('Failed', 'true')}
          (CallFunction|Status :Message "failed")
          (return false))
        {put('AppliedUnits', '(+ ' + g('AppliedUnits') + ' 1)')}
        (return true))'''
    code["FillHeater"] = f'''(fn FillHeater (Heater)
        {put('LastFillSuccess', 'false')}
        (for unit (range 4)
          (bind changed (CallFunction|RefillUnit :Heater Heater))
          (if (not changed) (return {g('LastFillSuccess')}))
          {put('LastFillSuccess', 'true')})
        (return {g('LastFillSuccess')}))'''
    for name, body in (
        ("RefillOne", f'''(bind changed (CallFunction|FillHeater :Heater Heater))
            (if changed {put('RefilledHeaters', '1')})'''),
        ("RefillAll", f'''(for heater {g('Heaters')}
            (if (not {g('Failed')})
              (bind changed (CallFunction|FillHeater :Heater heater))
              (if changed {put('RefilledHeaters', '(+ ' + g('RefilledHeaters') + ' 1)')})))'''),
    ):
        code[name] = f'''(fn {name} ({'Heater' if name == 'RefillOne' else ''})
            (if (or {g('Busy')} {g('Failed')}) (return false))
            (bind ready (CallFunction|Ready)) (if (not ready) (return false))
            {put('Busy', 'true')} {put('AppliedUnits', '0')} {put('RefilledHeaters', '0')}
            (CallFunction|UpdateRows)
            {body}
            {put('Busy', 'false')}
            (if (not {g('Failed')}) (CallFunction|Status :Message "summary"))
            (CallFunction|UpdateRows) (return (> {g('AppliedUnits')} 0)))'''
    code["CreatePanel"] = f'''(fn CreatePanel ()
        (if {valid(g('Panel'))} (return true))
        (bind player (Game|GetPlayerController :PlayerIndex 0))
        (if (not {valid('player')}) (return false))
        (bind widget (UserInterface|CreateWidget :Class "{ROOT}/WBP_CampfirePanel.WBP_CampfirePanel_C" :OwningPlayer player))
        (if (not {valid('widget')}) (return false))
        {put('Panel', 'widget')}
        {setprop('WBPCampfirePanel', 'widget', 'Host', 'self')}
        (CallFunction|SetLanguage :Language {g('CurrentLanguage')})
        {invoke('AddToViewport', 'UserWidget', 'widget', ':ZOrder 35')}
        (CallFunction|SyncPanelVisibility)
        (CallFunction|Status :Message "") (return true))'''
    # Rebuild a scratch set from the displayed list. Set lookup avoids scanning
    # the old array once per candidate, while the arrays retain row order.
    code["RefreshList"] = f'''(fn RefreshList ()
        (Utilities|Array|Clear {g('CurrentHeaters')})
        {world('w_')}
        (for heater (Utilities|Set|ToArray w_m_fueledHeaters_components)
          (bind supported (CallFunction|IsCampfire :Heater heater))
          (if supported (Utilities|Array|Add {g('CurrentHeaters')} heater)))
        {put('Available', '(== (Utilities|Array|Length ' + g('CurrentHeaters') + ') (Utilities|Array|Length ' + g('Heaters') + '))')}
        (Utilities|Set|Clear {g('HeaterMembership')})
        (Utilities|Set|AddItems {g('HeaterMembership')} {g('Heaters')})
        (for heater {g('CurrentHeaters')}
          (if (not (Utilities|Set|ContainsItem {g('HeaterMembership')} heater)) {put('Available', 'false')}))
        (if {g('Available')} (return true))
        {invoke('ClearChildren', 'PanelWidget', prop('WBPCampfirePanel', g('Panel'), 'RowsBox'))}
        (Utilities|Array|Clear {g('Rows')}) {put('Heaters', g('CurrentHeaters'))}
        (for heater {g('Heaters')}
          (bind row (UserInterface|CreateWidget :Class "{ROOT}/WBP_CampfireRow.WBP_CampfireRow_C"
            :OwningPlayer (Game|GetPlayerController :PlayerIndex 0)))
          (if {valid('row')}
            {setprop('WBPCampfireRow', 'row', 'Host', 'self')}
            {setprop('WBPCampfireRow', 'row', 'Heater', 'heater')}
            {invoke('AddChildToVerticalBox', 'VerticalBox', prop('WBPCampfirePanel', g('Panel'), 'RowsBox'), ':Content row')}
            (Utilities|Array|Add {g('Rows')} row)))
        (return true))'''
    code["UpdateRows"] = f'''(fn UpdateRows ()
        (if {g('ShuttingDown')} (return false))
        (if (not {valid(g('Panel'))}) (return false))
        (if (not (and {prop('WBPCampfirePanel', g('Panel'), 'Expanded')}
                     {prop('WBPCampfirePanel', g('Panel'), 'GameplayVisible')})) (return false))
        {put('AnyRefill', 'false')}
        (for index (range (Utilities|Array|Length {g('Rows')}))
          (bind row {at(g('Rows'), 'index')})
          (if {valid('row')}
            (bind heater {prop('WBPCampfireRow', 'row', 'Heater')})
            (if {valid('heater')}
              (bind duration (CallFunction|Duration :Heater heater))
              (bind remaining {heater_prop('BurnTimeRemaining', 'heater')})
              (bind percent (select (> duration 0) (/ remaining (select (> duration 0) duration 1)) 0.0))
              (bind enabled (and (not {g('Busy')}) (and (not {g('Failed')}) (and {can_refill('heater')} (> {wood()} 0)))))
              (if enabled {put('AnyRefill', 'true')})
              {row_call('Present', 'row', ':Title (CallFunction|RowTitle :Index index) :Fuel ' + trunc('(* percent 100.0)') +
                  ' :Capacity 100 :Percent percent :CanRefill enabled :Detail ' + tr('refill'))})))
        {panel_call('SetCanRefill', ':Enabled ' + g('AnyRefill'))}
        (return true))'''
    # UI callbacks only invalidate the timer. The next Pump tick still checks
    # Ready, without recursively entering SyncPanelVisibility from its callback.
    code["RequestRefresh"] = f'''(fn RequestRefresh ()
        {put('HasClock', 'false')} (return true))'''
    code["Pump"] = f'''(fn Pump ()
        (if {g('ShuttingDown')} (return false))
        (CallFunction|SyncPanelVisibility)
        (bind now (Utilities|Time|GetRealTimeSeconds))
        (if (and {g('HasClock')} (and (>= now {g('LastPoll')}) (< (- now {g('LastPoll')}) 1.0))) (return false))
        {put('HasClock', 'true')} {put('LastPoll', 'now')}
        (CallFunction|RefreshLanguage)
        (bind ready (CallFunction|Ready))
        (if (not ready)
          (if {valid(g('Panel'))} {panel_call('SetCanRefill', ':Enabled false')}) (return false))
        (if (not {g('Initialized')})
          {put('API', '(Class|ModAPI|GetModAPI)')}
          (if (not {valid(g('API'))}) (return false))
          {put('Initialized', 'true')})
        (bind made (CallFunction|CreatePanel)) (if (not made) (return false))
        (CallFunction|RefreshList) (CallFunction|UpdateRows) (return true))'''
    code["Shutdown"] = f'''(fn Shutdown ()
        {put('ShuttingDown', 'true')}
        (if {valid(g('Panel'))} (Widget|RemovefromParent :self {g('Panel')}))
        (return true))'''

    for name, source in code.items():
        blueprint_dsl.parse(source)
        clear_body(graphs[name])
        unreal.log("CAMPFIRE_WRITE " + name)
        BP.write_graph_dsl(graphs[name], source)
        if name in enum_patches:
            comparisons = [item for item in BP.get_node_infos(BP.find_nodes(graphs[name]))
                           if item.type_id == "Utilities|Enum|Equal(Enum)"]
            assert len(comparisons) == len(enum_patches[name])
            for comparison, literal in zip(comparisons, enum_patches[name]):
                BP.set_pin_value(next(pin.pin_id for pin in comparison.input_pins if pin.name == "B"), literal)
    BP.write_graph_dsl(BP.get_graph(bp, "EventGraph"), '''
        (event EventBeginPlay () (CallFunction|Pump))
        (event EventTick (DeltaSeconds) (CallFunction|Pump))
        (event EventEndPlay (EndPlayReason) (CallFunction|Shutdown))''')
    BP.compile_blueprint(bp, warnings_as_errors=True)
    cdo = unreal.get_default_object(bp.generated_class())
    cdo.set_editor_property("CurrentLanguage", "en")
    cdo.set_editor_property("TextKeys", list(STRINGS))
    cdo.set_editor_property("TextValues", [text for translations in STRINGS.values() for text in translations])
    cdo.set_editor_property("hidden", True)
    tick = cdo.get_editor_property("primary_actor_tick")
    tick.set_editor_property("start_with_tick_enabled", True)
    tick.set_editor_property("tick_even_when_paused", True)
    tick.set_editor_property("tick_interval", 0.0)
    cdo.set_editor_property("primary_actor_tick", tick, notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)
    assert unreal.EditorAssetLibrary.save_loaded_asset(bp)
    for asset in ("WBP_CampfirePanel", "WBP_CampfireRow"):
        widget = unreal.load_asset(ROOT + "/" + asset)
        BP.compile_blueprint(widget, warnings_as_errors=True)
        assert unreal.EditorAssetLibrary.save_loaded_asset(widget)
    descriptor_path = HERE.parents[1] / "Content" / "Mods" / "CampfirePanel" / "CampfirePanel.uplugin"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8-sig"))
    assert descriptor["Name"] == "CampfirePanel" and descriptor["Version"] == "0.1.1", descriptor
    destination = Path(unreal.Paths.project_content_dir()) / "Mods" / "CampfirePanel" / "CampfirePanel.uplugin"
    if destination.resolve() != descriptor_path.resolve():
        destination.write_bytes(descriptor_path.read_bytes())
    Path(unreal.Paths.project_saved_dir(), "CampfirePanel-Runtime.dsl").write_text("\n\n".join(code.values()), encoding="utf-8")
unreal.log("CAMPFIRE_GENERATED_PASS")

"""Check the public Blueprint boundary without executing resource operations."""
import re

import unreal
from editor_toolset.toolsets.blueprint import BlueprintTools as BP


ROOT = "/Game/Mods/CampfirePanel"
BRIDGES = {"CfSetPrimaryWarehouse", "CfSetBurnTime", "CfGrantWood",
           "CfReadConstructionStats", "CfRestoreConstructionStats"}
normalize = lambda value: re.sub("[^a-z0-9]", "", str(value).lower())
for name in ("BP_MapLoad", "WBP_CampfirePanel", "WBP_CampfireRow"):
    asset = unreal.load_asset(ROOT + "/" + name)
    assert isinstance(asset, unreal.Blueprint) and asset.generated_class(), (
        "Compiled public asset is missing", name)
    graphs = {str(graph.get_name()): graph for graph in BP.list_graphs(asset)}
    assert "Log" not in graphs, ("Runtime diagnostic function remains", name)
    calls = {}
    for graph_name, graph in graphs.items():
        # The authoring helper checks bridge bytecode directly when generating it.
        # BlueprintTools' catalog cannot describe those manually authored nodes.
        if graph_name in BRIDGES:
            continue
        calls[graph_name] = [normalize(info.type_id.rsplit("|", 1)[-1].split("(", 1)[0])
                             for info in BP.get_node_infos(BP.find_nodes(graph))]
        forbidden = {"log", "logmessage", "printstring", "printtext"} & set(calls[graph_name])
        assert not forbidden, ("Runtime logging remains", name, graph_name, forbidden)
    if name == "BP_MapLoad":
        assert BRIDGES <= graphs.keys(), "A verified native bridge is missing"
        required = {
            "RefillUnit": {"ready", "iscampfire", "duration", "findsource",
                           "cfreadconstructionstats", "cfrestoreconstructionstats",
                           "cfgrantwood", "cfsetburntime", "cfsetprimarywarehouse", "setfailed"},
            "Pump": {"getmodapi", "setapi", "ready", "syncpanelvisibility", "refreshlanguage"},
            "RefreshLanguage": {"getlocmanager", "getactivelanguage", "setlanguage"},
            "Ready": {"isdevelopmentmode", "getversionlabel", "getversionaccepted", "getfailed"},
        }
        for graph_name, required_calls in required.items():
            missing = required_calls - set(calls.get(graph_name, []))
            assert not missing, ("Public safety or native bridge is missing", graph_name, missing, calls.get(graph_name))
        assert calls["RefillUnit"].count("cfsetprimarywarehouse") == 2, (
            "Temporary warehouse selection must also be restored")
    unreal.log("CAMPFIRE_PUBLIC_ASSET_PASS " + name)

unreal.log("CAMPFIRE_PUBLIC_TESTS_PASS: no runtime diagnostics; safety and native bridges retained")

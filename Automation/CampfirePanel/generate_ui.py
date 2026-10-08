"""Generate the standalone Remote Campfire widgets in the editor.

Run after BP_MapLoad and its RefillOne and RefillAll signatures exist.
The host assigns Host/Heater references and calls row.Present and panel.SetStatus.
"""
import re

import unreal
import toolset_registry
from editor_toolset.toolsets.blueprint import BlueprintTools as BP
from editor_toolset.toolsets import blueprint_dsl


ROOT = "/Game/Mods/CampfirePanel"
UMG = unreal.get_default_object(unreal.UMGToolSet)
HOST = unreal.load_class(None, ROOT + "/BP_MapLoad.BP_MapLoad_C")
HEATER = unreal.load_class(None, "/Script/ProjectArco.FueledHeater")
assert HOST and HEATER, "Declare the CampfirePanel host first"


def color(value):
    rgb = [int(value[index:index + 2], 16) / 255.0 for index in (0, 2, 4)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return unreal.LinearColor(*linear, 1.0)


INK = color("F1F0EB")
MUTED = color("B6BCBA")
GOLD = color("D2AD62")
LOW_FUEL = color("F09A66")
CRITICAL_FUEL = color("EE786E")


def brush(fill, edge=None):
    result = unreal.SlateBrush()
    result.set_editor_property("draw_as", unreal.SlateBrushDrawType.ROUNDED_BOX)
    result.set_editor_property("tint_color", unreal.SlateColor(color(fill)))
    outline = result.get_editor_property("outline_settings")
    outline.set_editor_property("rounding_type", unreal.SlateBrushRoundingType.FIXED_RADIUS)
    outline.set_editor_property("corner_radii", unreal.Vector4(4, 4, 4, 4))
    outline.set_editor_property("color", unreal.SlateColor(color(edge or fill)))
    outline.set_editor_property("width", 1.0 if edge else 0.0)
    result.set_editor_property("outline_settings", outline)
    return result


def rectangle(slot, x, y, width, height, minimum=(0, 0), maximum=None):
    slot.set_anchors(unreal.Anchors(unreal.Vector2D(*minimum), unreal.Vector2D(*(maximum or minimum))))
    slot.set_offsets(unreal.Margin(x, y, width, height))


def style_button(widget, header=False):
    style = widget.get_editor_property("widget_style")
    for field, fill in (("normal", "242A2B" if header else "343B3C"),
                        ("hovered", "414A4A"), ("pressed", "202526"), ("disabled", "292E2E")):
        style.set_editor_property(field, brush(fill, None if header else "59605B"))
    style.set_editor_property("normal_padding", unreal.Margin(0))
    style.set_editor_property("pressed_padding", unreal.Margin(0))
    widget.set_editor_property("widget_style", style)
    widget.set_editor_property("is_focusable", False)


class Author:
    def __init__(self, name):
        path = ROOT + "/" + name
        self.bp = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
        if self.bp is None:
            self.bp = UMG.call_method("CreateWidgetBlueprint", args=(ROOT, name, unreal.UserWidget.static_class()))
        assert self.bp, name
        # Preserve public signatures when rerunning, including any host references.
        for graph in BP.list_graphs(self.bp):
            for node in BP.find_nodes(graph):
                if node.get_class().get_name() not in ("K2Node_FunctionEntry", "K2Node_FunctionResult"):
                    BP.delete_node(node)
        for item in UMG.call_method("GetWidgets", args=(self.bp,)).widgets:
            if not item.parent:
                UMG.call_method("RemoveWidget", args=(self.bp, item.widget))
        self.graphs = {}
        self.nodes = []
        self.getters = {}

    def add(self, kind, name, parent=None, variable=False):
        item = UMG.call_method("AddWidget", args=(self.bp, kind.static_class(), name, parent, -1))
        assert item.widget, name
        if variable:
            UMG.call_method("ToggleWidgetAsVariable", args=(self.bp, item.widget, True))
        return item.widget, item.widget.slot

    def label(self, name, parent, value="", size=14, tint=INK, variable=False):
        widget, slot = self.add(unreal.TextBlock, name, parent, variable)
        widget.set_text(value)
        widget.set_color_and_opacity(unreal.SlateColor(tint))
        font = widget.get_editor_property("font")
        font.set_editor_property("size", size * 0.75)
        game_font = unreal.load_asset("/Game/Assets/Fonts/Poppins/Poppins")
        if game_font:
            font.set_editor_property("font_object", game_font)
            font.set_editor_property("typeface_font_name", "Semi Bold" if size >= 16 else "Regular")
        widget.set_editor_property("font", font)
        widget.set_visibility(unreal.SlateVisibility.HIT_TEST_INVISIBLE)
        return widget, slot

    def declare(self, functions, variables=None, objects=None):
        existing = set(BP.list_variables(self.bp))
        for kind, names in (variables or {}).items():
            for name in names.split():
                if name not in existing:
                    BP.add_variable(self.bp, name, kind)
        for name, klass in {"Host": HOST, **(objects or {})}.items():
            if name not in existing:
                BP.add_object_variable(self.bp, name, klass)
        old = {str(graph.get_name()) for graph in BP.list_graphs(self.bp)}
        for name, inputs in functions.items():
            graph = BP.get_graph(self.bp, name) if name in old else BP.add_function_graph(self.bp, name)
            self.graphs[name] = graph
            if name not in old:
                for param, kind in inputs:
                    if isinstance(kind, str):
                        BP.add_function_param(graph, param, kind, True)
                    else:
                        BP.add_object_function_param(graph, param, kind, True)
                BP.add_function_param(graph, "Result", "bool", False)
        BP.compile_blueprint(self.bp)
        self.nodes = list(dict.fromkeys(BP.find_node_types(next(iter(self.graphs.values())), "", [])))
        self.getters = {node.rsplit("|Get", 1)[1]: node for node in self.nodes
                        if node.startswith("Variables|") and "|Get" in node}

    def get(self, name):
        return "(" + self.getters.get(name, "Variables|Default|Get" + name) + ")"

    def put(self, name, value):
        return f"(Variables|Default|Set{name} {value})"

    def native(self, method, owner=None):
        normalize = lambda value: re.sub("[^a-z0-9]", "", str(value).lower())
        candidates = [node for node in self.nodes
                      if normalize(node.rsplit("|", 1)[-1].split("(", 1)[0]) == normalize(method)]
        graph = next(iter(self.graphs.values()))
        if owner and len(candidates) > 1:
            alias = {"TextBlock": "Text"}.get(owner, owner)
            candidates = [node for node in candidates if any(
                normalize(pin.type_id) == normalize(alias) + "objectreference"
                for pin in BP.get_node_type_pins(graph, node).input_pins if pin.name in ("self", "Target"))]
            preferred = [node for node in candidates if not node.startswith("Class|")]
            candidates = preferred or candidates
        assert len(candidates) == 1, (method, owner, candidates)
        return candidates[0]

    def scalar(self, method, owner, target, value):
        node = self.native(method, owner)
        pins = BP.get_node_type_pins(next(iter(self.graphs.values())), node).input_pins
        args = [pin.name for pin in pins if pin.name not in ("self", "Target", "execute")]
        assert len(args) == 1, (method, args)
        return f"({node} :self {target} :{args[0]} {value})"

    def text(self, value):
        node = next(node for node in self.nodes if node.endswith("|ToText(String)"))
        return f"({node} {value})"

    def host(self, method, args=""):
        return f"({self.native(method, 'BPMapLoad')} :self {self.get('Host')} {args})"

    def emit(self, code, defaults=None):
        with toolset_registry.tool_raising_exceptions():
            for name, source in code.items():
                blueprint_dsl.parse(source)
                unreal.log("CAMPFIRE_UI_WRITE " + self.bp.get_name() + "." + name)
                BP.write_graph_dsl(self.graphs[name], source)
            BP.compile_blueprint(self.bp, warnings_as_errors=True)
            cdo = unreal.get_default_object(self.bp.generated_class())
            cdo.set_editor_property("visibility", unreal.SlateVisibility.SELF_HIT_TEST_INVISIBLE)
            for name, value in (defaults or {}).items():
                cdo.set_editor_property(name, value, notify_mode=unreal.PropertyAccessChangeNotifyMode.NEVER)

    def events(self, widget_events, lifecycle=None):
        graph = BP.get_graph(self.bp, "EventGraph")
        for node in BP.find_nodes(graph):
            BP.delete_node(node)
        for widget, event, fn in widget_events:
            old = set(str(node.get_path_name()) for node in BP.find_nodes(graph))
            assert UMG.call_method("BindToEventProperty", args=(self.bp, event, widget, unreal.Button.static_class()))
            source = next(node for node in BP.find_nodes(graph) if str(node.get_path_name()) not in old)
            self.wire_event(graph, source, fn)
        for event, fn in (lifecycle or []):
            self.wire_event(graph, BP.add_event(self.bp, event), fn)
        BP.compile_blueprint(self.bp, warnings_as_errors=True)
        assert unreal.EditorAssetLibrary.save_loaded_asset(self.bp)

    def wire_event(self, graph, event, fn):
        target = BP.create_node(graph, "CallFunction|" + fn, unreal.IntPoint(400, 0))
        source_info, target_info = BP.get_node_infos([event, target])
        BP.connect_pins(next(pin.pin_id for pin in source_info.output_pins if pin.name == "then"),
                        next(pin.pin_id for pin in target_info.input_pins if pin.name == "execute"))


VALID = '(fn HasObject (Object) (Utilities|IsValid Object (:"Is Valid" (return true)) (:"Is Not Valid" (return false))))'


def create_row():
    ui = Author("WBP_CampfireRow")
    size, _ = ui.add(unreal.SizeBox, "RowSize")
    size.set_height_override(52)
    frame, _ = ui.add(unreal.Border, "RowFrame", size)
    frame.set_editor_property("background", brush("292F30"))
    frame.set_padding(unreal.Margin(0, 0, 0, 0))
    root, _ = ui.add(unreal.CanvasPanel, "Contents", frame)
    title, slot = ui.label("TitleText", root, "Campfire", 15, variable=True)
    rectangle(slot, 10, 7, 102, 22, maximum=(1, 0))
    title.set_clipping(unreal.WidgetClipping.CLIP_TO_BOUNDS)
    fuel, slot = ui.label("FuelText", root, "0 %", 15, MUTED, True)
    rectangle(slot, -96, 7, 44, 22, minimum=(1, 0))
    fuel.set_editor_property("justification", unreal.TextJustify.RIGHT)
    progress, slot = ui.add(unreal.ProgressBar, "FuelBar", root, True)
    rectangle(slot, 10, 37, 52, 4, maximum=(1, 0))
    progress.set_fill_color_and_opacity(GOLD)
    progress.set_percent(0)
    progress.set_visibility(unreal.SlateVisibility.HIT_TEST_INVISIBLE)
    progress_style = progress.get_editor_property("widget_style")
    progress_style.set_editor_property("background_image", brush("171C1D"))
    progress_style.set_editor_property("fill_image", brush("FFFFFF"))
    progress.set_editor_property("widget_style", progress_style)
    refresh, slot = ui.add(unreal.Button, "RefreshButton", root, True)
    rectangle(slot, -42, 9, 32, 32, minimum=(1, 0))
    style_button(refresh)
    refresh.set_is_enabled(False)
    refresh.set_tool_tip_text("Auffuellen")
    icon_size, slot = ui.add(unreal.SizeBox, "RefreshIconSize", refresh)
    icon_size.set_width_override(18)
    icon_size.set_height_override(18)
    slot.set_padding(unreal.Margin(6, 6, 6, 6))
    slot.set_horizontal_alignment(unreal.HorizontalAlignment.H_ALIGN_CENTER)
    slot.set_vertical_alignment(unreal.VerticalAlignment.V_ALIGN_CENTER)
    icon, _ = ui.add(unreal.Image, "RefreshIcon", icon_size)
    texture = unreal.load_asset("/Game/Assets/Icons/BoardGameIcons/arrow_clockwise")
    assert texture, "Native refill icon unavailable"
    icon.set_brush_from_texture(texture, False)
    icon.set_color_and_opacity(GOLD)
    icon.set_visibility(unreal.SlateVisibility.HIT_TEST_INVISIBLE)
    ui.declare({"Present": [("Title", "string"), ("Fuel", "int"), ("Capacity", "int"),
                              ("Percent", "float"), ("CanRefill", "bool"), ("Detail", "string")],
                "RefillClicked": [], "HasObject": [("Object", unreal.Object.static_class())]},
               objects={"Heater": HEATER})
    g = ui.get
    fuel_string = '(Utilities|String|Append :A (Utilities|String|ToString(Integer) Fuel) :B " %")'
    make_color = ui.native("MakeLinearColor")
    make_slate = ui.native("MakeSlateColor")
    tint = lambda value: f"({make_color} :R {value.r} :G {value.g} :B {value.b} :A 1.0)"
    fuel_tint = f"(select (<= Percent 0.2) {tint(CRITICAL_FUEL)} (select (<= Percent 0.4) {tint(LOW_FUEL)} {tint(GOLD)}))"
    ui.emit({
        "HasObject": VALID,
        "Present": f'''(fn Present (Title Fuel Capacity Percent CanRefill Detail)
            {ui.scalar('SetText', 'TextBlock', g('TitleText'), ui.text('Title'))}
            {ui.scalar('SetText', 'TextBlock', g('FuelText'), ui.text(fuel_string))}
            {ui.scalar('SetColorAndOpacity', 'TextBlock', g('FuelText'), f'({make_slate} :SpecifiedColor {fuel_tint})')}
            {ui.scalar('SetPercent', 'ProgressBar', g('FuelBar'), '(select (< Percent 0.0) 0.0 (select (> Percent 1.0) 1.0 Percent))')}
            {ui.scalar('SetFillColorAndOpacity', 'ProgressBar', g('FuelBar'), fuel_tint)}
            {ui.scalar('SetIsEnabled', 'Widget', g('RefreshButton'), 'CanRefill')}
            {ui.scalar('SetToolTipText', 'Widget', g('RefreshButton'), ui.text('Detail'))}
            (return true))''',
        "RefillClicked": f'''(fn RefillClicked ()
            (if (not (CallFunction|HasObject :Object {g('Host')})) (return false))
            (if (not (CallFunction|HasObject :Object {g('Heater')})) (return false))
            (bind applied {ui.host('RefillOne', ':Heater ' + g('Heater'))}) (return applied))''',
    })
    ui.events([("RefreshButton", "OnClicked", "RefillClicked")])


def create_panel():
    ui = Author("WBP_CampfirePanel")
    root, _ = ui.add(unreal.CanvasPanel, "Root")
    root.set_visibility(unreal.SlateVisibility.SELF_HIT_TEST_INVISIBLE)
    toggle, slot = ui.add(unreal.Button, "ToggleButton", root, True)
    rectangle(slot, 16, -22, 44, 44, minimum=(0, 0.5))
    slot.set_z_order(1)
    style_button(toggle)
    toggle.set_tool_tip_text("Lagerfeuer")
    icon, slot = ui.add(unreal.Image, "CampfireIcon", toggle)
    texture = unreal.load_asset("/Game/Assets/Rendered/Icons/Building/campfire")
    assert texture, "Native campfire icon unavailable"
    icon.set_brush_from_texture(texture, False)
    icon.set_desired_size_override(unreal.Vector2D(36, 36))
    icon.set_visibility(unreal.SlateVisibility.HIT_TEST_INVISIBLE)
    slot.set_padding(unreal.Margin(4, 4, 4, 4))
    panel, slot = ui.add(unreal.CanvasPanel, "PanelCanvas", root, True)
    rectangle(slot, 72, 130, 352, 400)
    panel.set_visibility(unreal.SlateVisibility.COLLAPSED)
    background, slot = ui.add(unreal.Border, "PanelBackground", panel)
    rectangle(slot, 0, 0, 0, 0, maximum=(1, 1))
    background.set_editor_property("background", brush("202627", "5E6258"))
    header, slot = ui.add(unreal.Button, "DragHeader", panel, True)
    rectangle(slot, 8, 8, 156, 36, maximum=(1, 0))
    style_button(header, True)
    title, slot = ui.label("PanelTitle", header, "Lagerfeuer", 17, GOLD)
    slot.set_padding(unreal.Margin(8, 0, 0, 0))
    slot.set_horizontal_alignment(unreal.HorizontalAlignment.H_ALIGN_LEFT)
    slot.set_vertical_alignment(unreal.VerticalAlignment.V_ALIGN_CENTER)
    refresh, slot = ui.add(unreal.Button, "AllButton", panel, True)
    rectangle(slot, -148, 10, 138, 32, minimum=(1, 0))
    style_button(refresh)
    refresh.set_is_enabled(False)
    title, slot = ui.label("RefreshAllText", refresh, "Alle auffuellen", 13)
    slot.set_horizontal_alignment(unreal.HorizontalAlignment.H_ALIGN_CENTER)
    slot.set_vertical_alignment(unreal.VerticalAlignment.V_ALIGN_CENTER)
    scroll, slot = ui.add(unreal.ScrollBox, "RowsScroll", panel, True)
    rectangle(slot, 10, 54, 10, 40, maximum=(1, 1))
    scroll.set_editor_property("scrollbar_thickness", unreal.Vector2D(5, 5))
    scroll.set_editor_property("scrollbar_padding", unreal.Margin(3, 0, 0, 0))
    scroll.set_editor_property("allow_overscroll", False)
    ui.add(unreal.VerticalBox, "RowsBox", scroll, True)
    status, slot = ui.label("StatusText", panel, "Lagerfeuer werden gesucht...", 12, MUTED, True)
    rectangle(slot, 12, -32, 12, 26, minimum=(0, 1), maximum=(1, 1))
    status.set_clipping(unreal.WidgetClipping.CLIP_TO_BOUNDS)
    ui.declare({"SetStatus": [("Message", "string")], "SetCanRefill": [("Enabled", "bool")], "RefillAllClicked": [],
                "ApplyGameplayVisibility": [("Visible", "bool")], "TogglePanel": [],
                "BeginDrag": [], "EndDrag": [], "LayoutTick": [], "ClampPanel": [],
                "HasObject": [("Object", unreal.Object.static_class())]},
               {"bool": "Dragging Expanded GameplayVisible", "float": "PanelX PanelY PanelWidth PanelHeight ViewWidth ViewHeight DragOffsetX DragOffsetY"})
    g, put = ui.get, ui.put
    mouse = ui.native("GetMousePositionOnViewport")
    pressed = ui.native("IsPressed", "Button")
    slot_node = ui.native("SlotAsCanvasSlot")
    canvas_slot = f"({slot_node} :Widget {g('PanelCanvas')})"
    move = ui.scalar("SetPosition", "CanvasPanelSlot", canvas_slot,
                     f"(Math|Vector2D|MakeVector2D :X {g('PanelX')} :Y {g('PanelY')})")
    resize = ui.scalar("SetSize", "CanvasPanelSlot", canvas_slot,
                       f"(Math|Vector2D|MakeVector2D :X {g('PanelWidth')} :Y {g('PanelHeight')})")
    ui.emit({
        "HasObject": VALID,
        "SetStatus": f"(fn SetStatus (Message) {ui.scalar('SetText', 'TextBlock', g('StatusText'), ui.text('Message'))} (return true))",
        "SetCanRefill": f"(fn SetCanRefill (Enabled) {ui.scalar('SetIsEnabled', 'Widget', g('AllButton'), 'Enabled')} (return true))",
        "ApplyGameplayVisibility": f'''(fn ApplyGameplayVisibility (Visible)
            (if (== Visible {g('GameplayVisible')}) (return true))
            {put('GameplayVisible', 'Visible')}
            (if Visible
                {ui.scalar('SetVisibility', 'Widget', 'self', '"SelfHitTestInvisible"')}
                (CallFunction|LayoutTick) (return true))
            (CallFunction|EndDrag)
            {ui.scalar('SetVisibility', 'Widget', 'self', '"Collapsed"')}
            (return true))''',
        "TogglePanel": f'''(fn TogglePanel ()
            {put('Expanded', '(not ' + g('Expanded') + ')')}
            (if {g('Expanded')}
                {ui.scalar('SetVisibility', 'Widget', g('PanelCanvas'), '"SelfHitTestInvisible"')}
                (return true))
            (CallFunction|EndDrag)
            {ui.scalar('SetVisibility', 'Widget', g('PanelCanvas'), '"Collapsed"')}
            (return true))''',
        "RefillAllClicked": f'''(fn RefillAllClicked ()
            (if (not (CallFunction|HasObject :Object {g('Host')})) (return false))
            (bind applied {ui.host('RefillAll')}) (return applied))''',
        "BeginDrag": f'''(fn BeginDrag ()
            (if (not (and {g('GameplayVisible')} {g('Expanded')})) (return false))
            (bind (mx my) (Math|Vector2D|BreakVector2D ({mouse})))
            {put('DragOffsetX', '(- mx ' + g('PanelX') + ')')}
            {put('DragOffsetY', '(- my ' + g('PanelY') + ')')}
            {put('Dragging', 'true')} (return true))''',
        "EndDrag": f"(fn EndDrag () {put('Dragging', 'false')} (return true))",
        "ClampPanel": f'''(fn ClampPanel ()
            {put('PanelX', '(select (< ' + g('PanelX') + ' 8.0) 8.0 ' + g('PanelX') + ')')}
            {put('PanelY', '(select (< ' + g('PanelY') + ' 8.0) 8.0 ' + g('PanelY') + ')')}
            (bind maxX (- (- {g('ViewWidth')} {g('PanelWidth')}) 8.0))
            (bind maxY (- (- {g('ViewHeight')} {g('PanelHeight')}) 8.0))
            (if (> {g('PanelX')} maxX) {put('PanelX', 'maxX')})
            (if (> {g('PanelY')} maxY) {put('PanelY', 'maxY')})
            {move} (return true))''',
        "LayoutTick": f'''(fn LayoutTick ()
            (if (not {g('GameplayVisible')}) (return false))
            (bind (pixelsX pixelsY) (Math|Vector2D|BreakVector2D (Viewport|GetViewportSize)))
            (bind dpi (Viewport|GetViewportScale))
            (if (or (<= dpi 0.0) (or (<= pixelsX 0.0) (<= pixelsY 0.0))) (return false))
            (bind width (/ pixelsX dpi)) (bind height (/ pixelsY dpi))
            (if (or (< width 320.0) (< height 160.0)) (return false))
            (if (or (!= width {g('ViewWidth')}) (!= height {g('ViewHeight')}))
                {put('ViewWidth', 'width')} {put('ViewHeight', 'height')}
                {put('PanelWidth', '(select (< width 368.0) (- width 16.0) 352.0)')}
                {put('PanelHeight', '(select (< height 416.0) (- height 16.0) 400.0)')}
                {resize} (CallFunction|ClampPanel))
            (if (not {g('Dragging')}) (return true))
            (if (not ({pressed} :self {g('DragHeader')})) (CallFunction|EndDrag) (return true))
            (bind (mx my) (Math|Vector2D|BreakVector2D ({mouse})))
            {put('PanelX', '(- mx ' + g('DragOffsetX') + ')')}
            {put('PanelY', '(- my ' + g('DragOffsetY') + ')')}
            (CallFunction|ClampPanel) (return true))''',
    }, {"PanelX": 72.0, "PanelY": 130.0, "PanelWidth": 352.0, "PanelHeight": 400.0,
        "Expanded": False, "GameplayVisible": False, "Dragging": False,
        "visibility": unreal.SlateVisibility.COLLAPSED})
    # The standard button press/release state includes Slate's mouse capture.
    ui.events([("ToggleButton", "OnClicked", "TogglePanel"),
               ("AllButton", "OnClicked", "RefillAllClicked"),
               ("DragHeader", "OnPressed", "BeginDrag"), ("DragHeader", "OnReleased", "EndDrag")],
              [("Construct", "LayoutTick"), ("Tick", "LayoutTick")])


create_row()
create_panel()
unreal.log("CAMPFIRE_UI_GENERATED")

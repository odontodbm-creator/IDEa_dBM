"""Isolated subprocess harness for previewing imported Flet modules."""

from __future__ import annotations

import os
import json
import inspect
import subprocess
import sys
import tempfile
from pathlib import Path


class PreviewHarness:
    def __init__(self, source_path: str | Path, project_root: str | Path | None = None):
        self.source_path = Path(source_path).resolve()
        self.project_root = self._find_project_root(project_root)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="idea_dbm_preview_"))
        self.wrapper_path = self.temp_dir / "preview_runner.py"

    def _find_project_root(self, project_root: str | Path | None) -> Path:
        if project_root is not None:
            return Path(project_root).resolve()
        current = self.source_path.parent
        for candidate in (current, *current.parents):
            if (candidate / "components").is_dir():
                return candidate
            if any((candidate / marker).exists() for marker in ("pyproject.toml", "requirements.txt", ".git")):
                return candidate
        return current

    def create_wrapper(self) -> Path:
        source = repr(str(self.source_path))
        project_root = repr(str(self.project_root))
        code = f'''import importlib.util
from pathlib import Path
import os
import sys
import flet as ft

SOURCE_PATH = {source}
PROJECT_ROOT = Path({project_root})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SOURCE_DIR = os.path.dirname(SOURCE_PATH)
if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)
spec = importlib.util.spec_from_file_location("idea_dbm_imported_component", SOURCE_PATH)
module = importlib.util.module_from_spec(spec)
_run = ft.run
_app = getattr(ft, "app", None)
def _blocked(*args, **kwargs):
    return None
ft.run = _blocked
if _app is not None:
    ft.app = _blocked
try:
    spec.loader.exec_module(module)
finally:
    ft.run = _run
    if _app is not None:
        ft.app = _app

def _invoke(function, *args):
    run = ft.run
    app = getattr(ft, "app", None)
    ft.run = _blocked
    if app is not None:
        ft.app = _blocked
    try:
        return function(*args)
    finally:
        ft.run = run
        if app is not None:
            ft.app = app

def main(page: ft.Page):
    builder = getattr(module, "main", None)
    if callable(builder):
        _invoke(builder, page)
        return
    for name in ("build_ui", "build", "create_ui", "create_component", "component", "ui"):
        builder = getattr(module, name, None)
        if callable(builder):
            result = _invoke(builder)
            if isinstance(result, (list, tuple)):
                page.add(*result)
            elif isinstance(result, ft.Control):
                page.add(result)
            return
    for value in vars(module).values():
        if isinstance(value, ft.Control):
            page.add(value)

if __name__ == "__main__":
    ft.run(main)
'''
        self.wrapper_path.write_text(code, encoding="utf-8")
        return self.wrapper_path

    def start(self) -> subprocess.Popen:
        self.create_wrapper()
        return subprocess.Popen(
            [sys.executable, str(self.wrapper_path)],
            cwd=str(self.project_root),
            env={**os.environ, "IDEA_DBM_PREVIEW": "1"},
        )

    def render(self) -> dict:
        """Esegue il modulo in subprocess e restituisce una preview serializzata."""
        import_script = self.temp_dir / "preview_capture.py"
        import_script.write_text(self._capture_script(), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(import_script)],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
            env={**os.environ, "IDEA_DBM_PREVIEW": "1"},
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Preview subprocess terminato con errore")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Output preview non valido: {result.stdout[-500:]}") from error

    def build_preview(
        self,
        *,
        highlight_index=None,
        highlight_type=None,
        highlight_type_index=None,
        on_control_click=None,
        state_id=None,
        descriptor=None,
    ):
        """Ricostruisce nel processo IDE i controlli descritti dal subprocess."""
        import flet as ft

        descriptor = descriptor or self.render()
        preview_state = next(
            (state for state in descriptor.get("states", []) if state.get("id") == state_id),
            None,
        )
        theme_mode = {
            "dark": ft.ThemeMode.DARK,
            "light": ft.ThemeMode.LIGHT,
            "system": ft.ThemeMode.SYSTEM,
        }.get(descriptor.get("theme_mode", "system"), ft.ThemeMode.SYSTEM)
        preview_background = (
            "#121212" if theme_mode == ft.ThemeMode.DARK
            else "#FFFFFF" if theme_mode == ft.ThemeMode.LIGHT
            else None
        )
        control_index = [0]
        type_indices = {}
        type_highlighted = [False]

        def mark_selected(control, current_index, control_type, current_type_index):
            is_selected = (
                highlight_index is not None and current_index == highlight_index
            ) or (
                highlight_index is None
                and highlight_type == control_type
                and (
                    highlight_type_index is None
                    and not type_highlighted[0]
                    or current_type_index == highlight_type_index
                )
            )
            if not is_selected and on_control_click is None:
                return control
            if is_selected:
                type_highlighted[0] = True
            return ft.Container(
                content=control,
                padding=4,
                border_radius=4,
                border=ft.Border.all(2, "#F44336") if is_selected else None,
                on_click=(
                    lambda _e, name=control_type, index=current_type_index:
                        on_control_click(name, index)
                ) if on_control_click is not None else None,
            )

        def make_control(item):
            if item.get("type") == "DialogPreview":
                title = make_control(item["title"]) if item.get("title") else None
                content = make_control(item["content"]) if item.get("content") else None
                actions = [make_control(action) for action in item.get("actions", [])]
                return ft.Container(
                    width=560,
                    padding=16,
                    border_radius=8,
                    bgcolor=preview_background,
                    border=ft.Border.all(1, "#607D8B"),
                    content=ft.Column(
                        [
                            *( [title] if title is not None else [] ),
                            *( [content] if content is not None else [] ),
                            ft.Row(actions, alignment=ft.MainAxisAlignment.END) if actions else ft.Container(),
                        ],
                        tight=True,
                        spacing=12,
                    ),
                )
            if item.get("type") == "MenuPreview":
                menu_controls = [make_control(child) for child in item.get("controls", [])]
                menu_controls.extend(
                    ft.Container(
                        padding=8,
                        content=ft.Text(option.get("text") or option.get("key") or "Opzione"),
                    )
                    for option in item.get("options", [])
                )
                return ft.Container(
                    width=320,
                    padding=8,
                    border_radius=8,
                    bgcolor=preview_background,
                    content=ft.Column(menu_controls, tight=True, spacing=4),
                )
            current_index = control_index[0]
            control_index[0] += 1
            control_type = item.get("type", "Text")
            current_type_index = type_indices.get(control_type, 0)
            type_indices[control_type] = current_type_index + 1
            control_class = getattr(ft, control_type, ft.Text)
            props = {}
            for key, value in item.get("props", {}).items():
                if key == "icon" and isinstance(value, dict):
                    icon_name = value.get("__flet_icon__")
                    if isinstance(icon_name, str) and icon_name in dir(ft.Icons):
                        value = getattr(ft.Icons, icon_name)
                try:
                    signature = inspect.signature(control_class.__init__)
                    if key not in signature.parameters:
                        continue
                except (TypeError, ValueError):
                    pass
                if isinstance(value, (str, int, float, bool, type(ft.Icons.ADD))) or value is None:
                    props[key] = value
            children = [make_control(child) for child in item.get("controls", [])]
            if children:
                props["controls"] = children
            if item.get("content") is not None:
                props["content"] = make_control(item["content"])
            if item.get("title") is not None:
                props["title"] = make_control(item["title"])
            if item.get("actions"):
                props["actions"] = [make_control(action) for action in item["actions"]]
            if item.get("items"):
                props["items"] = [make_control(child) for child in item["items"]]
            if item.get("options"):
                dropdown_option = getattr(ft, "DropdownOption", None)
                if dropdown_option is None:
                    dropdown_option = ft.dropdown.Option
                props["options"] = [
                    dropdown_option(
                        key=option.get("key"),
                        text=option.get("text"),
                    )
                    for option in item["options"]
                    if option.get("key") is not None or option.get("text") is not None
                ]
            if item.get("cells"):
                props["cells"] = [make_control(cell) for cell in item["cells"]]
            if item.get("columns"):
                props["columns"] = [make_control(column) for column in item["columns"]]
            if item.get("rows"):
                props["rows"] = [make_control(row) for row in item["rows"]]
            if control_type == "IconButton" and not props.get("icon") and not props.get("content"):
                return mark_selected(
                    ft.IconButton(icon=ft.Icons.CIRCLE), current_index, control_type,
                    current_type_index,
                )
            if control_type in {"TextButton", "FilledButton", "OutlinedButton", "ElevatedButton"} and not props.get("content"):
                props["content"] = " "
            if control_type in {"AlertDialog", "CupertinoAlertDialog"} and not any(
                props.get(name) for name in ("title", "content", "actions")
            ):
                return mark_selected(
                    ft.Text("<AlertDialog senza contenuto>"), current_index, control_type,
                    current_type_index,
                )
            if control_type == "DataRow" and not props.get("cells"):
                return mark_selected(
                    ft.Text("<DataRow senza celle>"), current_index, control_type,
                    current_type_index,
                )
            try:
                control = control_class(**props)
            except Exception:
                try:
                    control = control_class()
                except Exception:
                    control = ft.Text(f"<{control_type}>")

            return mark_selected(control, current_index, control_type, current_type_index)

        source_controls = (
            [preview_state["control"]]
            if preview_state is not None and preview_state.get("control") is not None
            else descriptor.get("controls", [])
        )
        controls = [make_control(item) for item in source_controls]
        if not controls:
            controls = [ft.Text("Nessun controllo Flet individuato nella preview", selectable=True)]
        content = controls[0] if len(controls) == 1 else ft.Column(controls=controls, expand=True)
        return ft.Container(
            expand=True,
            bgcolor=preview_background,
            theme_mode=theme_mode,
            content=content,
        )

    def _capture_script(self) -> str:
        return f'''import importlib.util
import ast
import inspect
import json
from pathlib import Path
import os
import sys
import flet as ft

SOURCE_PATH = {str(self.source_path)!r}
PROJECT_ROOT = Path({str(self.project_root)!r})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SOURCE_DIR = os.path.dirname(SOURCE_PATH)
if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)

class CapturePage:
    def __init__(self):
        self.controls = []
        self.theme_mode = ft.ThemeMode.SYSTEM
        self.window = CaptureWindow()
        self.services = []
        self.overlay = []
        self.dialogs = []
    def add(self, *controls):
        self.controls.extend(controls)
    def show_dialog(self, dialog):
        self.dialogs.append(dialog)
        if dialog not in self.overlay:
            self.overlay.append(dialog)
    def update(self):
        pass
    def __getattr__(self, name):
        return lambda *args, **kwargs: None

class CaptureWindow:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None

def blocked(*args, **kwargs):
    return None

original_run = ft.run
original_app = getattr(ft, "app", None)
original_icon_button = ft.IconButton
original_text_button = ft.TextButton

def safe_icon_button(*args, **kwargs):
    if not kwargs.get("icon") and not kwargs.get("content"):
        kwargs["icon"] = ft.Icons.CIRCLE
    return original_icon_button(*args, **kwargs)

def safe_text_button(*args, **kwargs):
    if not args and not kwargs.get("content"):
        kwargs["content"] = " "
    elif args and not args[0]:
        args = (" ", *args[1:])
    return original_text_button(*args, **kwargs)

ft.IconButton = safe_icon_button
ft.TextButton = safe_text_button
ft.run = blocked
if original_app is not None:
    ft.app = blocked
spec = importlib.util.spec_from_file_location("idea_dbm_capture_source", SOURCE_PATH)
module = importlib.util.module_from_spec(spec)
source_error = None
try:
    spec.loader.exec_module(module)
except BaseException as error:
    source_error = f"{{type(error).__name__}}: {{error}}"
finally:
    ft.IconButton = original_icon_button
    ft.TextButton = original_text_button
    ft.run = original_run
    if original_app is not None:
        ft.app = original_app

def invoke(function, *args):
    run = ft.run
    app = getattr(ft, "app", None)
    icon_button = ft.IconButton
    text_button = ft.TextButton
    ft.IconButton = safe_icon_button
    ft.TextButton = safe_text_button
    ft.run = blocked
    if app is not None:
        ft.app = blocked
    try:
        return function(*args)
    except BaseException as error:
        global source_error
        source_error = f"{{type(error).__name__}}: {{error}}"
        return None
    finally:
        ft.IconButton = icon_button
        ft.TextButton = text_button
        ft.run = run
        if app is not None:
            ft.app = app

def serializable(value):
    return isinstance(value, (str, int, float, bool)) or value is None

def icon_expression(node):
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "Icons"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id in ("ft", "flet")
        and node.attr in dir(ft.Icons)
    ):
        return {{"__flet_icon__": node.attr}}
    return None

def serialize(control):
    item = {{"type": type(control).__name__, "props": {{}}}}
    for name in ("text", "value", "label", "hint_text", "width", "height", "visible", "color", "bgcolor", "icon", "icon_color", "disabled", "spacing"):
        try:
            value = getattr(control, name)
        except Exception:
            continue
        if name == "icon" and isinstance(value, type(ft.Icons.ADD)):
            item["props"][name] = {{"__flet_icon__": value.name}}
        elif serializable(value) and value is not None:
            item["props"][name] = value
    children = getattr(control, "controls", None)
    if isinstance(children, (list, tuple)):
        item["controls"] = [serialize(child) for child in children if isinstance(child, ft.Control)]
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        item["content"] = serialize(content)
    elif serializable(content) and content is not None:
        item["props"]["content"] = content
    title = getattr(control, "title", None)
    if isinstance(title, ft.Control):
        item["title"] = serialize(title)
    actions = getattr(control, "actions", None)
    if isinstance(actions, (list, tuple)):
        item["actions"] = [serialize(action) for action in actions if isinstance(action, ft.Control)]
    items = getattr(control, "items", None)
    if isinstance(items, (list, tuple)):
        item["items"] = [serialize(child) for child in items if isinstance(child, ft.Control)]
    options = getattr(control, "options", None)
    if isinstance(options, (list, tuple)):
        item["options"] = [
            {{
                "key": getattr(option, "key", None),
                "text": getattr(option, "text", None),
            }}
            for option in options
        ]
    for collection_name in ("cells", "columns", "rows"):
        collection = getattr(control, collection_name, None)
        if isinstance(collection, (list, tuple)):
            item[collection_name] = [
                serialize(child) for child in collection if isinstance(child, ft.Control)
            ]
    return item

def _control_values(value, seen):
    if isinstance(value, ft.Control):
        yield value
        return
    if isinstance(value, (list, tuple, set)):
        if id(value) in seen:
            return
        seen.add(id(value))
        for item in value:
            yield from _control_values(item, seen)
    elif isinstance(value, dict):
        if id(value) in seen:
            return
        seen.add(id(value))
        for item in value.values():
            yield from _control_values(item, seen)

def _detached_controls():
    seen = set()
    queue = list(page.controls) + list(page.overlay) + list(page.dialogs)
    queue.extend(value for value in vars(module).values() if isinstance(value, ft.Control))
    result = []
    while queue:
        control = queue.pop()
        if not isinstance(control, ft.Control) or id(control) in seen:
            continue
        seen.add(id(control))
        if isinstance(control, (ft.AlertDialog, ft.CupertinoAlertDialog, ft.PopupMenuButton, ft.Dropdown)):
            result.append(control)
        for name in ("controls", "content", "title", "actions", "items", "options", "leading", "trailing", "subtitle"):
            try:
                queue.extend(_control_values(getattr(control, name, None), seen))
            except Exception:
                pass
        for value in vars(control).get("_values", {{}}).values():
            if callable(value):
                for cell in getattr(value, "__closure__", None) or ():
                    try:
                        queue.extend(_control_values(cell.cell_contents, seen))
                    except ValueError:
                        continue
    return result

def _preview_states(controls, detached_controls):
    states = []
    state_ids = set()
    state_counts = {{}}
    visited = set()

    def next_state_id(prefix):
        index = state_counts.get(prefix, 0)
        state_counts[prefix] = index + 1
        return f"{{prefix}}:{{index}}"

    def add_state(control, path=""):
        if id(control) in visited:
            return
        visited.add(id(control))
        name = type(control).__name__
        if name in ("AlertDialog", "CupertinoAlertDialog"):
            state_id = next_state_id("dialog")
            if state_id not in state_ids:
                state_ids.add(state_id)
                states.append({{
                    "id": state_id,
                    "label": f"Dialogo: {{path or name}}",
                    "control": {{
                        "type": "DialogPreview",
                        "title": serialize(control.title) if isinstance(control.title, ft.Control) else None,
                        "content": serialize(control.content) if isinstance(control.content, ft.Control) else None,
                        "actions": [serialize(action) for action in control.actions or [] if isinstance(action, ft.Control)],
                    }},
                }})
        elif name == "PopupMenuButton":
            state_id = next_state_id("menu")
            if state_id not in state_ids:
                state_ids.add(state_id)
                states.append({{
                    "id": state_id,
                    "label": f"Menu: {{path or name}}",
                    "control": {{
                        "type": "MenuPreview",
                        "controls": [serialize(item) for item in control.items or [] if isinstance(item, ft.Control)],
                    }},
                }})
        elif name == "Dropdown":
            state_id = next_state_id("dropdown")
            if state_id not in state_ids:
                state_ids.add(state_id)
                states.append({{
                    "id": state_id,
                    "label": f"Opzioni: {{path or name}}",
                    "control": {{
                        "type": "MenuPreview",
                        "options": [
                            {{"key": getattr(option, "key", None), "text": getattr(option, "text", None)}}
                            for option in control.options or []
                        ],
                    }},
                }})
        for name in ("controls", "content", "title", "actions", "items"):
            value = getattr(control, name, None)
            for child in _control_values(value, set()):
                add_state(child, f"{{path}} / {{type(child).__name__}}".strip(" /"))

    for control in controls:
        add_state(control)
    for control in detached_controls:
        add_state(control)
    return states

def static_preview():
    """Fallback non esecutivo per moduli helper senza entry point."""
    source_text = open(SOURCE_PATH, encoding="utf-8").read()
    tree = ast.parse(source_text, filename=SOURCE_PATH)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    calls = [node for node in calls if isinstance(node.func, ast.Attribute) and getattr(node.func.value, "id", None) in ("ft", "flet")]
    nested = {{id(child) for parent in calls for child in ast.walk(parent) if child is not parent and isinstance(child, ast.Call)}}
    roots = [node for node in calls if id(node) not in nested]

    def describe(call):
        result = {{"type": call.func.attr, "props": {{}}}}
        for keyword in call.keywords:
            if keyword.arg is None:
                continue
            try:
                value = ast.literal_eval(keyword.value)
            except (ValueError, TypeError, SyntaxError):
                value = icon_expression(keyword.value) if keyword.arg == "icon" else None
            if serializable(value) or (
                isinstance(value, dict) and "__flet_icon__" in value
            ):
                result["props"][keyword.arg] = value
        children = [describe(child) for child in ast.walk(call)
                    if isinstance(child, ast.Call) and child is not call
                    and isinstance(child.func, ast.Attribute)
                    and getattr(child.func.value, "id", None) in ("ft", "flet")]
        if children:
            result["controls"] = children
        return result

    return [describe(call) for call in roots]

page = CapturePage()
if source_error is None:
    builder = getattr(module, "main", None)
    if callable(builder):
        invoke(builder, page)
    else:
        for name in ("build_ui", "build", "create_ui", "create_component", "component", "ui"):
            candidate = getattr(module, name, None)
            if callable(candidate):
                signature = inspect.signature(candidate)
                required = [p for p in signature.parameters.values() if p.default is inspect.Parameter.empty]
                invoke(candidate, page) if required else invoke(candidate)
                break
        if not page.controls:
            for value in vars(module).values():
                if isinstance(value, ft.Control):
                    page.add(value)

serialized_controls = [serialize(control) for control in page.controls]
if not serialized_controls:
    serialized_controls = static_preview()
detached_controls = _detached_controls()
serialized_detached_controls = [serialize(control) for control in detached_controls]
states = _preview_states(page.controls, detached_controls)
print(json.dumps({{
    "theme_mode": (
        "dark" if page.theme_mode == ft.ThemeMode.DARK
        else "light" if page.theme_mode == ft.ThemeMode.LIGHT
        else "system"
    ),
    "controls": serialized_controls,
    "detached": serialized_detached_controls,
    "states": states,
}}))
'''

"""Static analysis helpers for Flet modules.

The analyzer never imports or executes the inspected module.  It produces a
virtual component tree that the IDE can use when a module exposes helpers or
custom components instead of ``main(page)``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VirtualComponent:
    id: str
    type_name: str
    line: int
    column: int
    end_line: int
    end_column: int
    properties: dict[str, str] = field(default_factory=dict)
    children: list["VirtualComponent"] = field(default_factory=list)
    source_kind: str = "control"
    variable_name: str | None = None


@dataclass
class ModuleAnalysis:
    path: str
    source: str
    tree: ast.Module
    has_main_page: bool
    functions: list[str]
    classes: list[str]
    components: list[VirtualComponent]


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _literal_or_source(source: str, node: ast.AST) -> str:
    try:
        return repr(ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError):
        segment = ast.get_source_segment(source, node)
        return segment if segment is not None else ""


def _is_flet_call(node: ast.Call) -> bool:
    function = _name(node.func)
    if not function:
        return False
    if isinstance(node.func, ast.Attribute):
        owner = _name(node.func.value)
        if owner in {"ft", "flet"}:
            return True
        return (
            isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "dropdown"
            and _name(node.func.value.value) in {"ft", "flet"}
        )
    # Bare Flet controls and user-defined component classes/functions are
    # useful virtual nodes.  Lowercase utility calls (datetime.now, len, ...)
    # are deliberately excluded.
    return function in {
        "Text", "Container", "Column", "Row", "Card", "ListView",
        "TextField", "TextButton", "ElevatedButton", "IconButton",
        "Dropdown", "Checkbox", "Switch", "Image", "ProgressRing",
    } or function[:1].isupper()


_CONTROLS_ARGUMENTS = {
    "Column", "Row", "ListView", "GridView", "Stack", "ResponsiveRow",
    "ReorderableListView", "Tabs", "NavigationBar", "NavigationRail",
    "MenuBar", "SubmenuButton",
}
_CONTENT_ARGUMENTS = {
    "Container", "Card", "SafeArea", "Dismissible", "GestureDetector",
    "ConstrainedBox", "AnimatedSwitcher", "Tooltip", "Banner", "View",
    "PopupMenuItem", "DropdownOption", "Option",
}
_MULTI_CHILD_ARGUMENTS = {
    "ListTile": ("leading", "title", "subtitle", "trailing"),
    "DataRow": ("cells",),
    "DataTable": ("columns", "rows"),
    "AlertDialog": ("title", "content", "actions"),
    "CupertinoAlertDialog": ("title", "content", "actions"),
    "PopupMenuButton": ("content", "items"),
    "Dropdown": ("options",),
}


def _resolved_expression(
    expression: ast.AST, assignments: dict[str, list[ast.AST]]
) -> ast.AST:
    if isinstance(expression, ast.Name):
        values = assignments.get(expression.id, [])
        if values:
            return values[-1]
    return expression


def _argument_values(
    call: ast.Call,
    names: tuple[str, ...],
    assignments: dict[str, list[ast.AST]],
) -> list[ast.AST]:
    """Restituisce gli argomenti che possono contenere controlli figli."""
    values: list[ast.AST] = []
    keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
    for name in names:
        if name in keywords:
            values.append(_resolved_expression(keywords[name], assignments))
    # Column([..]), Row([..]) e ListView([..]) sono forme posizionali valide.
    if not values and names == ("controls",) and call.args:
        values.append(call.args[0])
    # Container(control) e Card(control) possono usare content posizionale.
    if not values and names == ("content",) and call.args:
        values.append(call.args[0])
    return values


def _child_argument_values(
    call: ast.Call, assignments: dict[str, list[ast.AST]]
) -> list[ast.AST]:
    type_name = _name(call.func) or ""
    if type_name in _CONTROLS_ARGUMENTS:
        return _argument_values(call, ("controls",), assignments)
    if type_name in _CONTENT_ARGUMENTS:
        return _argument_values(call, ("content",), assignments)
    if type_name in _MULTI_CHILD_ARGUMENTS:
        return _argument_values(call, _MULTI_CHILD_ARGUMENTS[type_name], assignments)
    return []


def _root_component_calls(
    expression: ast.AST, assignments: dict[str, list[ast.AST]]
) -> list[ast.Call]:
    calls = [node for node in ast.walk(expression) if isinstance(node, ast.Call) and _is_flet_call(node)]
    nested_ids = {
        id(child)
        for parent in calls
        for child in ast.walk(parent)
        if child is not parent and isinstance(child, ast.Call) and _is_flet_call(child)
    }
    return [call for call in calls if id(call) not in nested_ids]


def _component_from_call(
    source: str,
    call: ast.Call,
    index: int,
    assignments: dict[str, list[ast.AST]],
    variable_names: dict[int, str],
) -> VirtualComponent:
    properties = {
        keyword.arg: _literal_or_source(source, keyword.value)
        for keyword in call.keywords
        if keyword.arg is not None
    }
    children: list[VirtualComponent] = []
    child_index = 0
    for argument in _child_argument_values(call, assignments):
        for child in _root_component_calls(argument, assignments):
            children.append(
                _component_from_call(
                    source, child, index + child_index + 1, assignments, variable_names
                )
            )
            child_index += 1
    return VirtualComponent(
        id=f"ast_{index}_{call.lineno}_{call.col_offset}",
        type_name=_name(call.func) or "Control",
        line=call.lineno,
        column=call.col_offset,
        end_line=getattr(call, "end_lineno", call.lineno),
        end_column=getattr(call, "end_col_offset", call.col_offset),
        properties=properties,
        children=children,
        variable_name=variable_names.get(id(call)),
    )


def analyze_module(path: str | Path) -> ModuleAnalysis:
    source_path = Path(path).resolve()
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    assignments: dict[str, list[ast.AST]] = {}
    variable_names: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(value)
                    if isinstance(value, ast.Call) and _is_flet_call(value):
                        variable_names[id(value)] = target.id
    functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    has_main_page = any(
        name == "main" and len(node.args.args) >= 1
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for name in [node.name]
    )
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _is_flet_call(node)]
    nested_ids = {
        id(child)
        for parent in calls
        for argument in _child_argument_values(parent, assignments)
        for child in ast.walk(argument)
        if isinstance(child, ast.Call) and _is_flet_call(child)
    }
    roots = [node for node in calls if id(node) not in nested_ids]
    roots.sort(key=lambda node: (node.lineno, node.col_offset))
    components = [
        _component_from_call(source, node, index, assignments, variable_names)
        for index, node in enumerate(roots)
    ]
    return ModuleAnalysis(
        path=str(source_path),
        source=source,
        tree=tree,
        has_main_page=has_main_page,
        functions=functions,
        classes=classes,
        components=components,
    )


def flatten_components(components: list[VirtualComponent]) -> list[VirtualComponent]:
    result: list[VirtualComponent] = []

    def visit(component: VirtualComponent) -> None:
        result.append(component)
        for child in component.children:
            visit(child)

    for component in components:
        visit(component)
    return result

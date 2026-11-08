"""LibCST based, formatting-preserving edits for imported Python modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


def text_offsets(source: str, start_line: int, start_column: int,
                 end_line: int, end_column: int) -> tuple[int, int]:
    """Converte una posizione LibCST/AST in offset per TextField.selection."""
    lines = source.splitlines(keepends=True)

    def offset(line: int, column: int) -> int:
        return sum(len(item) for item in lines[:line - 1]) + column

    return offset(start_line, start_column), offset(end_line, end_column)


def _expression(value: Any, *, is_expression: bool = False) -> cst.BaseExpression:
    return cst.parse_expression(value if is_expression else repr(value))


def _libcst_column(source: str, line: int, ast_column: int) -> int:
    source_lines = source.splitlines()
    if line < 1 or line > len(source_lines):
        return ast_column
    return len(source_lines[line - 1].encode("utf-8")[:ast_column].decode("utf-8"))


class _CallEditor(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        line: int,
        column: int,
        property_name: str,
        value: Any,
        remove: bool = False,
        expression: bool = False,
    ):
        self.line = line
        self.column = column
        self.property_name = property_name
        self.value = value
        self.remove = remove
        self.expression = expression
        self.changed = False

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        position = self.get_metadata(PositionProvider, original_node)
        if position.start.line != self.line or position.start.column != self.column:
            return updated_node

        arguments = list(updated_node.args)
        matches = [index for index, argument in enumerate(arguments) if argument.keyword and argument.keyword.value == self.property_name]
        if self.remove:
            if matches:
                del arguments[matches[0]]
                self.changed = True
            return updated_node.with_changes(args=tuple(arguments))

        new_value = _expression(self.value, is_expression=self.expression)
        if matches:
            index = matches[0]
            arguments[index] = arguments[index].with_changes(value=new_value)
        else:
            arguments.append(cst.Arg(keyword=cst.Name(self.property_name), value=new_value))
        self.changed = True
        return updated_node.with_changes(args=tuple(arguments))


class _CallRemover(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, line: int, column: int):
        self.line = line
        self.column = column
        self.changed = False

    def _is_target(self, node: cst.CSTNode) -> bool:
        if not isinstance(node, cst.Call):
            return False
        position = self.get_metadata(PositionProvider, node)
        return position.start.line == self.line and position.start.column == self.column

    def _contains_target(self, node: cst.CSTNode) -> bool:
        if self._is_target(node):
            return True
        return any(self._contains_target(child) for child in node.children)

    def leave_List(self, original_node: cst.List, updated_node: cst.List) -> cst.List:
        elements = tuple(
            updated for original, updated in zip(original_node.elements, updated_node.elements)
            if not self._is_target(original.value)
        )
        if len(elements) != len(updated_node.elements):
            self.changed = True
            return updated_node.with_changes(elements=elements)
        return updated_node

    def leave_Tuple(self, original_node: cst.Tuple, updated_node: cst.Tuple) -> cst.Tuple:
        elements = tuple(
            updated for original, updated in zip(original_node.elements, updated_node.elements)
            if not self._is_target(original.value)
        )
        if len(elements) != len(updated_node.elements):
            self.changed = True
            return updated_node.with_changes(elements=elements)
        return updated_node

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        arguments = tuple(
            updated for original, updated in zip(original_node.args, updated_node.args)
            if not self._is_target(original.value)
        )
        if len(arguments) != len(updated_node.args):
            self.changed = True
            return updated_node.with_changes(args=arguments)
        return updated_node

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.BaseStatement | cst.RemovalSentinel:
        for original, updated in zip(original_node.body, updated_node.body):
            if isinstance(original, cst.Assign) and self._is_target(original.value):
                self.changed = True
                return cst.RemoveFromParent()
            if isinstance(original, cst.Expr) and self._is_target(original.value):
                self.changed = True
                return cst.RemoveFromParent()
            if (
                isinstance(original, cst.Expr)
                and isinstance(original.value, cst.Call)
                and isinstance(updated, cst.Expr)
                and isinstance(updated.value, cst.Call)
                and updated.value.args == ()
                and self._contains_target(original.value)
                and isinstance(original.value.func, cst.Attribute)
                and original.value.func.attr.value == "add"
            ):
                self.changed = True
                return cst.RemoveFromParent()
        return updated_node


class _CollectionAssignments(cst.CSTVisitor):
    def __init__(self) -> None:
        self.values: dict[str, cst.List | cst.Tuple] = {}

    def visit_Assign(self, node: cst.Assign) -> None:
        if isinstance(node.value, (cst.List, cst.Tuple)):
            for target in node.targets:
                if isinstance(target.target, cst.Name):
                    self.values[target.target.value] = node.value

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        if isinstance(node.value, (cst.List, cst.Tuple)) and isinstance(node.target, cst.Name):
            self.values[node.target.value] = node.value


class _ListPropertyReference(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, line: int, column: int, property_name: str) -> None:
        self.line = line
        self.column = column
        self.property_name = property_name
        self.variable_name: str | None = None

    def visit_Call(self, node: cst.Call) -> bool:
        position = self.get_metadata(PositionProvider, node)
        if position.start.line == self.line and position.start.column == self.column:
            for argument in node.args:
                if (
                    argument.keyword is not None
                    and argument.keyword.value == self.property_name
                    and isinstance(argument.value, cst.Name)
                ):
                    self.variable_name = argument.value.value
                    break
        return True


class _ListItemPropertyEditor(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        line: int,
        column: int,
        collection_property: str,
        index: int,
        item_property: str,
        value: str,
    ) -> None:
        self.line = line
        self.column = column
        self.collection_property = collection_property
        self.index = index
        self.item_property = item_property
        self.value = value
        self.collection_assignments: dict[str, cst.List | cst.Tuple] = {}
        self.item_position: tuple[int, int] | None = None
        self.changed = False

    def visit_Module(self, node: cst.Module) -> bool:
        assignments = _CollectionAssignments()
        node.visit(assignments)
        self.collection_assignments = assignments.values
        return True

    def visit_Call(self, node: cst.Call) -> bool:
        position = self.get_metadata(PositionProvider, node)
        if position.start.line != self.line or position.start.column != self.column:
            return True
        collection = next(
            (
                argument.value for argument in node.args
                if argument.keyword is not None
                and argument.keyword.value == self.collection_property
            ),
            None,
        )
        if isinstance(collection, cst.Name):
            collection = self.collection_assignments.get(collection.value)
        if not isinstance(collection, (cst.List, cst.Tuple)):
            raise ValueError(
                f"La proprietà {self.collection_property} non contiene una lista modificabile."
            )
        if self.index < 0 or self.index >= len(collection.elements):
            raise IndexError(
                f"Indice {self.index} fuori dai limiti della proprietà "
                f"{self.collection_property}."
            )
        item = collection.elements[self.index].value
        if not isinstance(item, cst.Call):
            raise ValueError("La voce selezionata non è un costruttore modificabile.")
        item_position = self.get_metadata(PositionProvider, item)
        self.item_position = (item_position.start.line, item_position.start.column)
        return True

    def leave_Call(self, _original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        return updated_node

    def leave_Module(
        self, _original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        if self.item_position is None:
            return updated_node
        editor = _CallKeywordValueEditor(
            self.item_position, self.item_property, self.value
        )
        edited = MetadataWrapper(updated_node).visit(editor)
        self.changed = editor.changed
        return edited


class _CallKeywordValueEditor(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        position: tuple[int, int],
        property_name: str,
        value: str,
    ) -> None:
        self.position = position
        self.property_name = property_name
        self.value = value
        self.changed = False

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        position = self.get_metadata(PositionProvider, original_node)
        if (position.start.line, position.start.column) != self.position:
            return updated_node
        arguments = list(updated_node.args)
        matching = next(
            (
                index for index, argument in enumerate(arguments)
                if argument.keyword is not None
                and argument.keyword.value == self.property_name
            ),
            None,
        )
        new_value = cst.parse_expression(self.value)
        if matching is None:
            arguments.append(
                cst.Arg(keyword=cst.Name(self.property_name), value=new_value)
            )
        else:
            arguments[matching] = arguments[matching].with_changes(value=new_value)
        self.changed = True
        return updated_node.with_changes(args=tuple(arguments))


class _ContentChildEditor(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, line: int, column: int, child_expression: str) -> None:
        self.line = line
        self.column = column
        self.child_expression = child_expression
        self.changed = False

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        position = self.get_metadata(PositionProvider, original_node)
        if position.start.line != self.line or position.start.column != self.column:
            return updated_node
        child = _expression(self.child_expression, is_expression=True)
        content_index = next(
            (
                index for index, argument in enumerate(updated_node.args)
                if argument.keyword is not None
                and argument.keyword.value == "content"
            ),
            None,
        )
        if content_index is not None:
            current = updated_node.args[content_index].value
            if isinstance(current, cst.Name) and current.value == "None":
                replacement = child
            else:
                replacement = cst.Call(
                    func=cst.Attribute(value=cst.Name("ft"), attr=cst.Name("Column")),
                    args=[
                        cst.Arg(
                            keyword=cst.Name("controls"),
                            value=cst.List(
                                elements=[
                                    cst.Element(value=current),
                                    cst.Element(value=child),
                                ]
                            ),
                        )
                    ],
                )
            arguments = list(updated_node.args)
            arguments[content_index] = arguments[content_index].with_changes(
                value=replacement
            )
        else:
            positional = next(
                (
                    index for index, argument in enumerate(updated_node.args)
                    if argument.keyword is None and argument.star == ""
                ),
                None,
            )
            arguments = list(updated_node.args)
            if positional is not None:
                current = arguments[positional].value
                if isinstance(current, cst.Name) and current.value == "None":
                    replacement = child
                else:
                    replacement = cst.Call(
                        func=cst.Attribute(
                            value=cst.Name("ft"), attr=cst.Name("Column")
                        ),
                        args=[
                            cst.Arg(
                                keyword=cst.Name("controls"),
                                value=cst.List(
                                    elements=[
                                        cst.Element(value=current),
                                        cst.Element(value=child),
                                    ]
                                ),
                            )
                        ],
                    )
                arguments[positional] = arguments[positional].with_changes(
                    value=replacement
                )
            else:
                arguments.append(
                    cst.Arg(keyword=cst.Name("content"), value=child)
                )
        self.changed = True
        return updated_node.with_changes(args=tuple(arguments))


class _CallExpressionReplacer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, line: int, column: int, expression: str) -> None:
        self.line = line
        self.column = column
        self.expression = expression
        self.changed = False

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        position = self.get_metadata(PositionProvider, original_node)
        if position.start.line != self.line or position.start.column != self.column:
            return updated_node
        self.changed = True
        return _expression(self.expression, is_expression=True)


class _PageThemeSetter(cst.CSTTransformer):
    def __init__(self, theme_mode: str) -> None:
        self.theme_mode = theme_mode
        self.found_main = False
        self.changed = False

    @staticmethod
    def _is_theme_target(target: cst.BaseExpression, page_name: str) -> bool:
        return (
            isinstance(target, cst.Attribute)
            and target.attr.value == "theme_mode"
            and isinstance(target.value, cst.Name)
            and target.value.value == page_name
        )

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        if original_node.name.value != "main":
            return updated_node
        parameters = (*updated_node.params.posonly_params, *updated_node.params.params)
        if not parameters or not isinstance(parameters[0].name, cst.Name):
            return updated_node

        self.found_main = True
        page_name = parameters[0].name.value
        assignment = cst.SimpleStatementLine(
            body=(
                cst.Assign(
                    targets=(
                        cst.AssignTarget(
                            target=cst.Attribute(
                                value=cst.Name(page_name),
                                attr=cst.Name("theme_mode"),
                            )
                        ),
                    ),
                    value=_expression(f"ft.ThemeMode.{self.theme_mode}", is_expression=True),
                ),
            )
        )
        if isinstance(updated_node.body, cst.SimpleStatementSuite):
            statements = (
                assignment,
                cst.SimpleStatementLine(body=updated_node.body.body),
            )
            body = cst.IndentedBlock(body=statements)
            self.changed = True
            return updated_node.with_changes(body=body)

        statements = list(updated_node.body.body)
        for index, statement in enumerate(statements):
            small_statements = (
                statement.body
                if isinstance(statement, cst.SimpleStatementLine)
                else ()
            )
            for small_statement in small_statements:
                if isinstance(small_statement, cst.Assign):
                    target_matches = any(
                        self._is_theme_target(target.target, page_name)
                        for target in small_statement.targets
                    )
                    current_value = small_statement.value
                elif isinstance(small_statement, cst.AnnAssign):
                    target_matches = self._is_theme_target(
                        small_statement.target, page_name
                    )
                    current_value = small_statement.value
                else:
                    continue
                if not target_matches:
                    continue
                if (
                    current_value is not None
                    and cst.Module(body=[]).code_for_node(current_value)
                    == f"ft.ThemeMode.{self.theme_mode}"
                ):
                    return updated_node
                statements[index] = assignment
                self.changed = True
                break
            if self.changed:
                break
        else:
            insertion_index = 0
            if statements and isinstance(statements[0], cst.SimpleStatementLine):
                first = statements[0].body
                if first and isinstance(first[0], cst.Expr) and isinstance(
                    first[0].value, cst.SimpleString
                ):
                    insertion_index = 1
            statements.insert(insertion_index, assignment)
            self.changed = True
        return updated_node.with_changes(body=updated_node.body.with_changes(body=tuple(statements)))


class _PageWindowPropertySetter(cst.CSTTransformer):
    def __init__(
        self,
        property_name: str,
        value: str | None,
    ) -> None:
        self.property_name = property_name
        self.value = value
        self.found_main = False
        self.changed = False

    @staticmethod
    def _is_target(
        target: cst.BaseExpression, page_name: str, property_name: str
    ) -> bool:
        if property_name == "center":
            return False
        if property_name in {"title", "theme_mode"}:
            return (
                isinstance(target, cst.Attribute)
                and target.attr.value == property_name
                and isinstance(target.value, cst.Name)
                and target.value.value == page_name
            )
        return (
            isinstance(target, cst.Attribute)
            and target.attr.value == property_name
            and isinstance(target.value, cst.Attribute)
            and target.value.attr.value == "window"
            and isinstance(target.value.value, cst.Name)
            and target.value.value.value == page_name
        )

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        if original_node.name.value != "main":
            return updated_node
        parameters = (*updated_node.params.posonly_params, *updated_node.params.params)
        if not parameters or not isinstance(parameters[0].name, cst.Name):
            return updated_node

        self.found_main = True
        page_name = parameters[0].name.value
        if isinstance(updated_node.body, cst.SimpleStatementSuite):
            updated_node = updated_node.with_changes(
                body=cst.IndentedBlock(
                    body=(
                        cst.SimpleStatementLine(body=updated_node.body.body),
                    )
                )
            )
        if self.property_name == "center":
            center_call = cst.Expr(
                value=cst.Call(
                    func=cst.Attribute(
                        value=cst.Attribute(
                            value=cst.Name(page_name), attr=cst.Name("window")
                        ),
                        attr=cst.Name("center"),
                    )
                )
            )
            center_statement = cst.SimpleStatementLine(body=(center_call,))

            def is_center_statement(statement: cst.BaseStatement) -> bool:
                return (
                    isinstance(statement, cst.SimpleStatementLine)
                    and any(
                        isinstance(item, cst.Expr)
                        and isinstance(item.value, cst.Call)
                        and isinstance(item.value.func, cst.Attribute)
                        and item.value.func.attr.value == "center"
                        and isinstance(item.value.func.value, cst.Attribute)
                        and item.value.func.value.attr.value == "window"
                        and isinstance(item.value.func.value.value, cst.Name)
                        and item.value.func.value.value.value == page_name
                        for item in statement.body
                    )
                )

            statements = list(updated_node.body.body)
            for index, statement in enumerate(statements):
                if not is_center_statement(statement):
                    continue
                if self.value is None or self.value.strip() in {"False", "None", "0"}:
                    del statements[index]
                    if not statements:
                        statements.append(
                            cst.SimpleStatementLine(body=(cst.Pass(),))
                        )
                else:
                    return updated_node
                self.changed = True
                return updated_node.with_changes(
                    body=updated_node.body.with_changes(body=tuple(statements))
                )
            if self.value is None or self.value.strip() in {"False", "None", "0"}:
                return updated_node
            insertion_index = next(
                (
                    index for index, statement in enumerate(statements)
                    if isinstance(statement, cst.SimpleStatementLine)
                    and any(
                        isinstance(item, cst.Expr)
                        and isinstance(item.value, cst.Call)
                        and isinstance(item.value.func, cst.Attribute)
                        and isinstance(item.value.func.value, cst.Name)
                        and item.value.func.value.value == page_name
                        and item.value.func.attr.value == "add"
                        for item in statement.body
                    )
                ),
                len(statements),
            )
            statements.insert(insertion_index, center_statement)
            self.changed = True
            return updated_node.with_changes(
                body=updated_node.body.with_changes(body=tuple(statements))
            )

        target: cst.BaseExpression = cst.Attribute(
            value=cst.Name(page_name),
            attr=cst.Name(
                self.property_name
                if self.property_name in {"title", "theme_mode"}
                else "window"
            ),
        )
        if self.property_name not in {"title", "theme_mode"}:
            target = cst.Attribute(value=target, attr=cst.Name(self.property_name))
        assignment = (
            None
            if self.value is None
            else cst.SimpleStatementLine(
                body=(
                    cst.Assign(
                        targets=(cst.AssignTarget(target=target),),
                        value=_expression(self.value, is_expression=True),
                    ),
                )
            )
        )

        statements = list(updated_node.body.body)
        for index, statement in enumerate(statements):
            if not isinstance(statement, cst.SimpleStatementLine):
                continue
            for small_index, small_statement in enumerate(statement.body):
                if isinstance(small_statement, cst.Assign):
                    matches = any(
                        self._is_target(
                            assign_target.target, page_name, self.property_name
                        )
                        for assign_target in small_statement.targets
                    )
                elif isinstance(small_statement, cst.AnnAssign):
                    matches = self._is_target(
                        small_statement.target, page_name, self.property_name
                    )
                else:
                    matches = False
                if not matches:
                    continue
                if assignment is None:
                    remaining = (
                        statement.body[:small_index]
                        + statement.body[small_index + 1:]
                    )
                    if remaining:
                        statements[index] = statement.with_changes(body=remaining)
                    else:
                        del statements[index]
                        if not statements:
                            statements.append(
                                cst.SimpleStatementLine(body=(cst.Pass(),))
                            )
                else:
                    statements[index] = statement.with_changes(
                        body=(
                            statement.body[:small_index]
                            + assignment.body
                            + statement.body[small_index + 1:]
                        )
                    )
                self.changed = True
                return updated_node.with_changes(
                    body=updated_node.body.with_changes(body=tuple(statements))
                )

        if assignment is None:
            return updated_node
        insertion_index = 0
        if statements and isinstance(statements[0], cst.SimpleStatementLine):
            first = statements[0].body
            if first and isinstance(first[0], cst.Expr) and isinstance(
                first[0].value, cst.SimpleString
            ):
                insertion_index = 1
        for index, statement in enumerate(statements):
            if isinstance(statement, cst.SimpleStatementLine) and any(
                isinstance(item, cst.Expr)
                and isinstance(item.value, cst.Call)
                and isinstance(item.value.func, cst.Attribute)
                and isinstance(item.value.func.value, cst.Name)
                and item.value.func.value.value == page_name
                and item.value.func.attr.value == "add"
                for item in statement.body
            ):
                insertion_index = index
                break
        statements.insert(insertion_index, assignment)
        self.changed = True
        return updated_node.with_changes(
            body=updated_node.body.with_changes(body=tuple(statements))
        )


class _ListPropertyEditor(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        line: int,
        column: int,
        property_name: str,
        action: str,
        value: Any,
        index: int | None,
        expression: bool,
        minimum_items: int,
        assignments: dict[str, cst.List | cst.Tuple],
        target_variable: str | None,
        target_collection_position: tuple[int, int] | None,
    ) -> None:
        if action not in {"add", "remove", "update"}:
            raise ValueError(f"Azione lista non supportata: {action}")
        if action in {"remove", "update"} and index is None:
            raise ValueError(f"L'azione {action} richiede un indice.")
        self.line = line
        self.column = column
        self.property_name = property_name
        self.action = action
        self.value = value
        self.index = index
        self.expression = expression
        self.minimum_items = minimum_items
        self.assignments = assignments
        self.target_variable = target_variable
        self.target_collection_position = target_collection_position
        self.target_collection: cst.List | cst.Tuple | None = None
        self.collection_position: tuple[int, int] | None = None
        self.changed = False

    def visit_Call(self, node: cst.Call) -> bool:
        position = self.get_metadata(PositionProvider, node)
        if position.start.line != self.line or position.start.column != self.column:
            return True
        argument = next(
            (
                item for item in node.args
                if item.keyword is not None
                and item.keyword.value == self.property_name
            ),
            None,
        )
        if argument is None:
            return True
        value_node = argument.value
        if isinstance(value_node, cst.Name):
            if value_node.value in self.assignments:
                self.target_variable = value_node.value
                return True
        if not isinstance(value_node, (cst.List, cst.Tuple)):
            raise ValueError(
                f"La proprietà {self.property_name} non contiene una lista modificabile."
            )
        self.target_collection = value_node
        collection_position = self.get_metadata(PositionProvider, value_node)
        self.collection_position = (
            collection_position.start.line,
            collection_position.start.column,
        )
        return True

    def _is_target_assignment(self, targets, value_node) -> bool:
        position = self.get_metadata(PositionProvider, value_node)
        return (
            self.target_variable is not None
            and self.target_collection_position
            == (position.start.line, position.start.column)
            and any(
                isinstance(
                    target.target if isinstance(target, cst.AssignTarget) else target,
                    cst.Name,
                )
                and (
                    target.target if isinstance(target, cst.AssignTarget) else target
                ).value
                == self.target_variable
                for target in targets
            )
        )

    def leave_Assign(self, original_node: cst.Assign, updated_node: cst.Assign) -> cst.Assign:
        if (
            self._is_target_assignment(original_node.targets, original_node.value)
            and isinstance(original_node.value, (cst.List, cst.Tuple))
            and isinstance(updated_node.value, (cst.List, cst.Tuple))
        ):
            return updated_node.with_changes(
                value=self._edit_elements(updated_node.value)
            )
        return updated_node

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.AnnAssign:
        if (
            original_node.value is not None
            and self._is_target_assignment((original_node.target,), original_node.value)
            and isinstance(original_node.value, (cst.List, cst.Tuple))
            and isinstance(updated_node.value, (cst.List, cst.Tuple))
        ):
            return updated_node.with_changes(
                value=self._edit_elements(updated_node.value)
            )
        return updated_node

    def _edit_elements(self, updated):
        elements = list(updated.elements)
        if self.action == "add":
            new_element = cst.Element(value=_expression(self.value, is_expression=self.expression))
            if elements:
                last = elements[-1]
                if last.comma is cst.MaybeSentinel.DEFAULT:
                    separator_whitespace = next(
                        (
                            element.comma.whitespace_after
                            for element in elements
                            if isinstance(element.comma, cst.Comma)
                        ),
                        cst.SimpleWhitespace(""),
                    )
                    elements[-1] = last.with_changes(
                        comma=cst.Comma(whitespace_after=separator_whitespace)
                    )
            elif isinstance(updated, cst.Tuple):
                new_element = new_element.with_changes(comma=cst.Comma())
            elements.append(new_element)
        else:
            assert self.index is not None
            if self.index < 0 or self.index >= len(elements):
                raise IndexError(f"Indice {self.index} fuori dai limiti della proprietà {self.property_name}.")
            if self.action == "remove":
                if len(elements) <= self.minimum_items:
                    raise ValueError(
                        f"La proprietà {self.property_name} deve contenere almeno "
                        f"{self.minimum_items} elemento."
                    )
                del elements[self.index]
            else:
                elements[self.index] = elements[self.index].with_changes(
                    value=_expression(self.value, is_expression=self.expression)
                )
        self.changed = True
        return updated.with_changes(elements=tuple(elements))

    def leave_List(self, original_node: cst.List, updated_node: cst.List) -> cst.List:
        position = self.get_metadata(PositionProvider, original_node)
        if (position.start.line, position.start.column) == self.collection_position:
            return self._edit_elements(updated_node)
        return updated_node

    def leave_Tuple(self, original_node: cst.Tuple, updated_node: cst.Tuple) -> cst.Tuple:
        position = self.get_metadata(PositionProvider, original_node)
        if (position.start.line, position.start.column) == self.collection_position:
            return self._edit_elements(updated_node)
        return updated_node

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        position = self.get_metadata(PositionProvider, original_node)
        if position.start.line != self.line or position.start.column != self.column:
            return updated_node
        if any(
            argument.keyword is not None
            and argument.keyword.value == self.property_name
            for argument in updated_node.args
        ):
            return updated_node
        if self.action != "add":
            raise ValueError(f"La proprietà {self.property_name} non esiste.")
        collection = cst.List(
            elements=[
                cst.Element(value=_expression(self.value, is_expression=self.expression))
            ]
        )
        self.changed = True
        return updated_node.with_changes(
            args=updated_node.args
            + (
                cst.Arg(
                    keyword=cst.Name(self.property_name),
                    value=collection,
                ),
            )
        )


def edit_property(path: str | Path, line: int, column: int, property_name: str,
                  value: Any = None, *, remove: bool = False,
                  expression: bool = False) -> bool:
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    module = cst.parse_module(source)
    wrapper = MetadataWrapper(module)
    column = _libcst_column(source, line, column)
    transformer = _CallEditor(
        line, column, property_name, value, remove=remove, expression=expression
    )
    edited = wrapper.visit(transformer)
    if not transformer.changed:
        return False
    source_path.write_text(edited.code, encoding="utf-8")
    return True


def edit_list_property(
    path: str | Path,
    line: int,
    column: int,
    property_name: str,
    action: str,
    value: Any = None,
    *,
    index: int | None = None,
    expression: bool = False,
    minimum_items: int = 0,
) -> bool:
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    module = cst.parse_module(source)
    wrapper = MetadataWrapper(module)
    column = _libcst_column(source, line, column)
    reference = _ListPropertyReference(line, column, property_name)
    wrapper.visit(reference)
    collection_assignments = _CollectionAssignments()
    wrapper.module.visit(collection_assignments)
    if reference.variable_name and reference.variable_name not in collection_assignments.values:
        raise ValueError(
            f"La lista {reference.variable_name} non è assegnata direttamente a una lista o tupla."
        )
    target_collection_position = None
    if reference.variable_name:
        target_collection = collection_assignments.values[reference.variable_name]
        target_position = wrapper.resolve(PositionProvider)[target_collection]
        target_collection_position = (
            target_position.start.line,
            target_position.start.column,
        )
    transformer = _ListPropertyEditor(
        line,
        column,
        property_name,
        action,
        value,
        index,
        expression,
        minimum_items,
        collection_assignments.values,
        reference.variable_name,
        target_collection_position,
    )
    edited = wrapper.visit(transformer)
    if not transformer.changed:
        return False
    source_path.write_text(edited.code, encoding="utf-8")
    return True


def edit_list_item_property(
    path: str | Path,
    line: int,
    column: int,
    collection_property: str,
    index: int,
    item_property: str,
    value_expression: str,
) -> bool:
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    module = cst.parse_module(source)
    wrapper = MetadataWrapper(module)
    column = _libcst_column(source, line, column)
    transformer = _ListItemPropertyEditor(
        line, column, collection_property, index, item_property, value_expression
    )
    edited = wrapper.visit(transformer)
    if not transformer.changed:
        return False
    source_path.write_text(edited.code, encoding="utf-8")
    return True


def replace_control_call(
    path: str | Path, line: int, column: int, expression: str
) -> bool:
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    module = cst.parse_module(source)
    wrapper = MetadataWrapper(module)
    transformer = _CallExpressionReplacer(
        line, _libcst_column(source, line, column), expression
    )
    edited = wrapper.visit(transformer)
    if not transformer.changed:
        return False
    source_path.write_text(edited.code, encoding="utf-8")
    return True


def set_page_theme_mode(path: str | Path, theme_mode: str) -> bool:
    if theme_mode not in {"DARK", "LIGHT", "SYSTEM"}:
        raise ValueError(f"Tema Flet non supportato: {theme_mode}")
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    module = cst.parse_module(source)
    transformer = _PageThemeSetter(theme_mode)
    edited = module.visit(transformer)
    if not transformer.found_main:
        raise ValueError("Il file non contiene una funzione main(page) modificabile.")
    if not transformer.changed:
        return False
    source_path.write_text(edited.code, encoding="utf-8")
    return True


def set_page_window_property(
    path: str | Path,
    property_name: str,
    value_expression: str | None,
) -> bool:
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    module = cst.parse_module(source)
    transformer = _PageWindowPropertySetter(property_name, value_expression)
    edited = module.visit(transformer)
    if not transformer.found_main:
        raise ValueError("Il file non contiene una funzione main(page) modificabile.")
    if not transformer.changed:
        return False
    source_path.write_text(edited.code, encoding="utf-8")
    return True


def add_content_child(
    path: str | Path, line: int, column: int, child_expression: str
) -> bool:
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    module = cst.parse_module(source)
    wrapper = MetadataWrapper(module)
    transformer = _ContentChildEditor(
        line,
        _libcst_column(source, line, column),
        child_expression,
    )
    edited = wrapper.visit(transformer)
    if not transformer.changed:
        return False
    source_path.write_text(edited.code, encoding="utf-8")
    return True


def remove_component(path: str | Path, line: int, column: int) -> bool:
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    if line < 1 or line > len(source_lines):
        return False
    cst_column = _libcst_column(source, line, column)
    module = cst.parse_module(source)
    wrapper = MetadataWrapper(module)
    transformer = _CallRemover(line, cst_column)
    edited = wrapper.visit(transformer)
    if not transformer.changed:
        return False
    source_path.write_text(edited.code, encoding="utf-8")
    return True

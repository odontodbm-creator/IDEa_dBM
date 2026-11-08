import flet as ft
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
import zipfile
import inspect
import importlib.util
import ast
import re
import typing
from pathlib import Path
from flet_static_analysis import analyze_module, flatten_components  # type: ignore[import-not-found]
from flet_code_editor import (
    add_content_child as add_source_content_child,
    edit_property as edit_source_property,
    edit_list_property as edit_source_list_property,
    edit_list_item_property as edit_source_list_item_property,
    remove_component as remove_source_component,
    replace_control_call as replace_source_control_call,
    set_page_theme_mode as set_source_theme_mode,
    set_page_window_property as set_source_window_property,
    text_offsets,
)  # type: ignore[import-not-found]
from flet_preview_harness import PreviewHarness  # type: ignore[import-not-found]

ICON_CATEGORY_RULES = (
    ("Comunicazione", ("CALL", "CHAT", "COMMENT", "CONTACT", "EMAIL", "FORUM", "MAIL", "MESSAGE", "PHONE", "SMS", "VOICEMAIL")),
    ("Persone e accessibilità", ("ACCESSIBILITY", "ACCOUNT", "FACE", "FAMILY", "GROUP", "PERSON", "PEOPLE", "SUPERVISOR", "WOMAN", "MAN", "BOY", "GIRL", "CHILD")),
    ("File e cartelle", ("ATTACH", "CLOUD_UPLOAD", "CLOUD_DOWNLOAD", "DOWNLOAD", "FILE", "FOLDER", "UPLOAD", "DRIVE_FILE", "INSERT_DRIVE_FILE")),
    ("Media", ("AUDIO", "ALBUM", "CAMERA", "MIC", "MOVIE", "MUSIC", "PAUSE", "PLAY", "PODCAST", "STOP", "VIDEO", "VOLUME", "SPEAKER")),
    ("Dispositivi e rete", ("BATTERY", "BLUETOOTH", "CAST", "COMPUTER", "DEVICES", "DEVICE", "HEADPHONES", "KEYBOARD", "LAPTOP", "MOBILE", "MONITOR", "MOUSE", "ROUTER", "SIM_CARD", "SMARTPHONE", "USB", "WATCH", "WIFI")),
    ("Luoghi e mappe", ("COMPASS", "HOME", "LOCATION", "MAP", "MY_LOCATION", "PIN_DROP", "PLACE", "ROUTE", "TERRAIN")),
    ("Trasporti e viaggi", ("AIR", "BOAT", "BUS", "CAR", "COMMUTE", "DIRECTIONS", "FLIGHT", "LOCAL_TAXI", "PARKING", "RAILWAY", "TRAIN", "TRAM")),
    ("Acquisti e pagamenti", ("CART", "CURRENCY", "CREDIT_CARD", "LOCAL_MALL", "PAYMENT", "PRICE", "RECEIPT", "SELL", "SHOP", "STORE")),
    ("Salute", ("BLOOD", "CORONAVIRUS", "DENTAL", "HEALING", "HEALTH", "HOSPITAL", "MEDICAL", "MONITOR_HEART", "VACCINE")),
    ("Cibo e bevande", ("BREAKFAST", "CAKE", "COFFEE", "DINNER", "FASTFOOD", "FOOD", "KITCHEN", "LUNCH", "PIZZA", "RESTAURANT")),
    ("Natura e meteo", ("BEACH", "CLOUD", "ECO", "FOREST", "GRASS", "LANDSCAPE", "NATURE", "PETS", "RAIN", "SUNNY", "THUNDERSTORM", "WATER", "WEATHER", "WIND")),
    ("Grafici e dati", ("ANALYTICS", "ASSESSMENT", "BAR_CHART", "DATA", "GRAPH", "INSIGHTS", "PIE_CHART", "POLL", "QUERY_STATS", "SHOW_CHART", "TIMELINE", "TRENDING")),
    ("Editor e immagini", ("BRUSH", "COLOR", "CROP", "DRAW", "EDIT", "EDITOR", "FORMAT", "IMAGE", "PALETTE", "PHOTO", "TEXT_FIELDS", "TITLE", "TRANSFORM")),
    ("Sicurezza", ("ADMIN_PANEL", "FINGERPRINT", "KEY", "LOCK", "PASSWORD", "POLICY", "PRIVACY", "SECURITY", "SHIELD", "VPN")),
    ("Data e orario", ("CALENDAR", "DATE", "EVENT", "HISTORY", "SCHEDULE", "TIME", "TIMER", "TODAY", "WATCH_LATER")),
    ("Notifiche", ("ALARM", "NOTIFICATION", "RINGTONE", "VIBRATION")),
    ("Azioni e stato", ("ADD", "ARROW", "BLOCK", "BUILD", "CANCEL", "CHECK", "CLEAR", "CLOSE", "DELETE", "DONE", "ERROR", "EXPAND", "FILTER", "FAVORITE", "HELP", "INFO", "LINK", "MENU", "MORE", "REFRESH", "REMOVE", "SAVE", "SEARCH", "SETTINGS", "SHARE", "SORT", "STAR", "UNDO", "REDO", "UPDATE", "WARNING")),
)


def icon_category_for_name(icon_name):
    for category, prefixes in ICON_CATEGORY_RULES:
        if icon_name.startswith(prefixes):
            return category
    return "Altro"


def main(page: ft.Page):
    page.title = "IDEa dBM - Flet 1.0.1 IDE"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0

    # --- ISPEZIONE DINAMICA DI FLET 1.0.1 ---
    def get_flet_controls_schema():
        schema = {}
        non_addable_controls = {
            "ActionControl", "AdaptiveControl", "BasePage",
            "DataCell", "DataColumn", "DataRow", "DialogControl",
            "DropdownOption", "FletApp", "FormFieldControl", "LayoutControl",
            "MultiView", "NavigationBarDestination", "NavigationDrawerDestination",
            "Page", "PageView", "PopupMenuItem", "ScrollableControl", "Segment",
            "FilePicker", "SnackBarAction", "TextSpan", "View",
        }

        for name, cls in inspect.getmembers(ft, inspect.isclass):
            if (
                name.startswith("_")
                or name in non_addable_controls
                or cls.__module__.split(".")[0] != "flet"
                or inspect.isabstract(cls)
            ):
                continue

            try:
                if not issubclass(cls, ft.Control):
                    continue
                sig = inspect.signature(cls.__init__)
                schema[name] = [
                    param_name
                    for param_name in sig.parameters
                    if param_name not in {"self", "kwargs", "args", "controls", "content"}
                ]
            except (TypeError, ValueError):
                schema[name] = ["value", "label", "width", "height", "visible"]

        return schema

    FLET_SCHEMA = get_flet_controls_schema()
    WINDOW_SCHEMA = list(dict.fromkeys([
        "title",
        "theme_mode",
        "center",
        *[
            name
            for name in inspect.signature(ft.Window.__init__).parameters
            if name not in {"self", "data", "key", "ref"}
        ],
    ]))
    FLET_ICON_NAMES = set(dir(ft.Icons))
    CONTAINER_TYPES = {
        "Column", "Row", "Container", "Card", "ListView", "GridView", "Stack",
        "ResponsiveRow", "SafeArea", "Wrap", "Tabs", "View", "PopupMenuButton",
        "MenuBar", "SubmenuButton",
    }
    CONTROL_COLLECTION_PROPERTIES = {
        "Column": "controls",
        "Row": "controls",
        "ListView": "controls",
        "GridView": "controls",
        "Stack": "controls",
        "ResponsiveRow": "controls",
        "View": "controls",
        "PopupMenuButton": "items",
        "MenuBar": "controls",
        "SubmenuButton": "controls",
    }
    BUTTON_TYPES = {
        "Button", "ElevatedButton", "TextButton", "OutlinedButton",
        "FilledButton", "FilledTonalButton",
    }

    # --- CARTELLA DI LAVORO SICURA ---
    WORK_DIR = os.path.join(tempfile.gettempdir(), "idea_dbm_workspace")
    os.makedirs(WORK_DIR, exist_ok=True)
    os.chdir(WORK_DIR)
    project_folder = [WORK_DIR]
    project_base_name = ["idea_dbm"]
    project_ui_file = [None]
    project_logic_file = [None]
    single_file_mode = [False]
    project_code_authoritative = [False]
    project_display_name = [None]
    active_code_view = ["ui"]
    imported_preview_controls = [[]]
    imported_preview_error = [None]
    selected_imported_control = [None]
    imported_control_nodes = {}
    imported_analysis = [None]
    imported_harness = [None]
    imported_preview_descriptor = [None]
    imported_preview_state_id = [None]
    file_open = [True]
    imported_wrapper_path = [None]
    top_bar_ref = [None]

    def python_module_name(name):
        cleaned = "".join(char if (char.isalnum() or char == "_") else "_" for char in name)
        if not cleaned:
            cleaned = "idea_dbm"
        if cleaned[0].isdigit():
            cleaned = f"project_{cleaned}"
        return cleaned

    def project_file_path(suffix):
        if suffix == "ui" and project_ui_file[0]:
            return project_ui_file[0]
        if suffix == "logic" and project_logic_file[0]:
            return project_logic_file[0]
        if suffix == "logic" and single_file_mode[0]:
            return None
        return os.path.join(project_folder[0], f"{project_base_name[0]}_{suffix}.py")

    def project_module_name(suffix):
        return python_module_name(f"{project_base_name[0]}_{suffix}")

    # --- STATO GLOBALE DEL PROGETTO ---
    layout_data = {
        "id": "root",
        "type": "Column",
        "props": {"alignment": "center", "spacing": 20},
        "window_props": {},
        "children": [
            {
                "id": "main_card",
                "type": "Card",
                "props": {"elevation": 4},
                "children": [
                    {
                        "id": "card_col",
                        "type": "Column",
                        "props": {"alignment": "center", "spacing": 15},
                        "children": [
                            {"id": "txt_title", "type": "Text", "props": {"value": "Prova IDE", "size": 18}, "children": []},
                            {"id": "input_user", "type": "TextField", "props": {"label": "Cerca dati / dati", "width": 280}, "children": []},
                            {"id": "btn_save", "type": "TextButton", "props": {"text": "Esegui Ricerca", "on_click": "esegui_ricerca"}, "children": []}
                        ]
                    }
                ]
            }
        ]
    }

    selected_node = [layout_data]
    pending_property_values = {}
    property_editor_controls = {}
    property_action_buttons = {}
    preview_select_enabled = [False]
    project_theme_mode = [ft.ThemeMode.SYSTEM]
    running_process = [None]
    running_preview_directory = [None]
    project_dependencies = ["flet", "firebirdsql"]

    # --- UI COMPONENTS DELL'IDE ---
    preview_surface = ft.Container(
        expand=True,
        alignment=ft.Alignment(0, 0),
        theme_mode=project_theme_mode[0],
        bgcolor=None,
    )
    project_theme_button = ft.IconButton(
        icon=ft.Icons.DARK_MODE,
        tooltip="Imposta il tema scuro per il progetto",
        on_click=lambda e: toggle_project_theme(),
    )
    preview_mode_button = ft.IconButton(
        icon=ft.Icons.TOUCH_APP,
        tooltip="Seleziona elementi",
        on_click=lambda e: toggle_preview_selection(),
    )
    preview_state_selector = ft.Dropdown(
        value="",
        options=[ft.dropdown.Option(key="", text="Layout Principale")],
        width=260,
        dense=True,
        on_select=lambda e: render_preview_state(e.control.value),
    )
    preview_state_toolbar = ft.Row(
        [
            ft.Text("Stato Anteprima:", size=12, color="#B0BEC5"),
            preview_state_selector,
        ],
        spacing=8,
        visible=False,
    )
    canvas_area = ft.Container(
        expand=True,
        padding=10,
        bgcolor="#1E1E1E",
        border=ft.Border.all(1, "#333333"),
        content=ft.Column([
            preview_state_toolbar,
            ft.Row([
                ft.Text("ANTEPRIMA", size=12, weight=ft.FontWeight.BOLD, color="#90CAF9"),
                ft.Container(expand=True),
                project_theme_button,
                preview_mode_button,
            ]),
            preview_surface,
        ], expand=True, spacing=4),
    )
    inspector_area = ft.ListView(expand=True, padding=10, spacing=10)
    interface_tree_area = ft.ListView(
        expand=True, padding=10, spacing=3, width=320
    )
    interface_tree_scroller = ft.Row(
        controls=[interface_tree_area],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

    code_ui_view = ft.TextField(multiline=True, expand=True, text_style=ft.TextStyle(font_family="Consolas", size=12), bgcolor="#121212", border_color="#333333")
    code_logic_view = ft.TextField(multiline=True, expand=True, text_style=ft.TextStyle(font_family="Consolas", size=12), bgcolor="#121212", border_color="#333333")
    code_highlight_enabled = [True]
    code_ui_highlight = ft.Markdown(
        "```python\n\n```",
        selectable=True,
        fit_content=False,
        extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
        code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK,
    )
    code_logic_highlight = ft.Markdown(
        "```python\n\n```",
        selectable=True,
        fit_content=False,
        extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
        code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK,
    )

    code_ui_scroll = ft.ListView(
        controls=[code_ui_highlight], expand=True, auto_scroll=False,
        spacing=0, padding=4,
    )
    code_logic_scroll = ft.ListView(
        controls=[code_logic_highlight], expand=True, auto_scroll=False,
        spacing=0, padding=4,
    )

    def update_colored_code_highlight():
        if not code_highlight_enabled[0]:
            return
        theme = (
            ft.MarkdownCodeTheme.ATOM_ONE_DARK
            if page.theme_mode == ft.ThemeMode.DARK
            else ft.MarkdownCodeTheme.ATOM_ONE_LIGHT
        )
        source_text = code_ui_view.value or ""
        lines = source_text.splitlines()

        start_line = None
        end_line = None

        node = selected_node[0]
        if node:
            if node.get("_imported") and node.get("_call") is not None:
                start_line = node["_call"].lineno
                end_line = getattr(node["_call"], "end_lineno", start_line)
            elif node.get("_imported") and node.get("_line") is not None:
                start_line = node["_line"]
                end_line = node.get("_end_line", start_line)
            elif imported_analysis[0] is not None:
                ordered_nodes = []
                def visit(current):
                    ordered_nodes.append(current)
                    for child in current.get("children", []) or []:
                        visit(child)
                visit(layout_data)
                try:
                    node_index = next(i for i, c in enumerate(ordered_nodes) if c.get("id") == node.get("id"))
                    v_comps = flatten_components(imported_analysis[0].components)
                    if node_index < len(v_comps):
                        comp = v_comps[node_index]
                        start_line = comp.line
                        end_line = comp.end_line
                except (StopIteration, Exception):
                    pass
            else:
                ordered_nodes = []
                def visit(current):
                    ordered_nodes.append(current)
                    for child in current.get("children", []) or []:
                        visit(child)
                visit(layout_data)
                try:
                    node_index = next(
                        index for index, current in enumerate(ordered_nodes)
                        if current.get("id") == node.get("id")
                    )
                    node_type = node.get("type", "")
                    same_type_index = sum(
                        1 for current in ordered_nodes[:node_index]
                        if current.get("type") == node_type
                    )
                    pattern = re.compile(rf"ft\.{re.escape(node_type)}\s*\(")
                    matches = list(pattern.finditer(source_text))
                    if same_type_index < len(matches):
                        match = matches[same_type_index]
                        start_line = source_text[:match.start()].count("\n") + 1
                        # stima blocco
                        end_line = start_line + 3
                except (StopIteration, Exception):
                    pass

        if start_line is not None and 1 <= start_line <= len(lines):
            end_line = end_line or min(len(lines), start_line + 4)
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)
            pre_lines = "\n".join(lines[:start_idx])
            target_lines = "\n".join(lines[start_idx:end_idx])
            post_lines = "\n".join(lines[end_idx:])

            controls = []
            if pre_lines.strip():
                controls.append(ft.Markdown(
                    f"```python\n{pre_lines}\n```",
                    selectable=True,
                    extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
                    code_theme=theme,
                ))

            if target_lines.strip():
                highlight_container = ft.Container(
                    key="highlighted_block",
                    content=ft.Markdown(
                        f"```python\n{target_lines}\n```",
                        selectable=True,
                        extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
                        code_theme=theme,
                    ),
                    bgcolor="#1A3A4A" if page.theme_mode == ft.ThemeMode.DARK else "#E1F5FE",
                    border=ft.Border.all(2, "#00ACC1"),
                    border_radius=6,
                    padding=6,
                )
                controls.append(highlight_container)

            if post_lines.strip():
                controls.append(ft.Markdown(
                    f"```python\n{post_lines}\n```",
                    selectable=True,
                    extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
                    code_theme=theme,
                ))

            code_ui_scroll.controls = controls if controls else [code_ui_highlight]
        else:
            code_ui_highlight.value = f"```python\n{source_text}\n```"
            code_ui_highlight.code_theme = theme
            code_ui_scroll.controls = [code_ui_highlight]

        code_ui_scroll.update()
        try:
            code_ui_scroll.scroll_to(key="highlighted_block", duration=300)
        except Exception:
            pass

    def update_code_highlighting():
        update_colored_code_highlight()
        theme = (
            ft.MarkdownCodeTheme.ATOM_ONE_DARK
            if page.theme_mode == ft.ThemeMode.DARK
            else ft.MarkdownCodeTheme.ATOM_ONE_LIGHT
        )
        code_logic_highlight.value = f"```python\n{code_logic_view.value or ''}\n```"
        code_logic_highlight.code_theme = theme
        code_logic_highlight.extension_set = ft.MarkdownExtensionSet.GITHUB_FLAVORED

    def toggle_code_view(e=None):
        code_highlight_enabled[0] = not code_highlight_enabled[0]
        code_ui_view.read_only = code_highlight_enabled[0]
        code_logic_view.read_only = code_highlight_enabled[0]
        code_highlight_button.icon = (
            ft.Icons.EDIT if code_highlight_enabled[0] else ft.Icons.CODE
        )
        code_highlight_button.tooltip = (
            "Modifica codice" if code_highlight_enabled[0]
            else "Mostra codice evidenziato"
        )
        switch_tab(active_code_view[0])
        page.update()

    code_highlight_button = ft.IconButton(
        icon=ft.Icons.EDIT,
        tooltip="Modifica codice",
        on_click=toggle_code_view,
    )
    
    ai_prompt_input = ft.TextField(hint_text="Chiedi modifiche o logica all'AI...", expand=True, text_size=12)
    ai_output_view = ft.ListView(expand=True, padding=10, spacing=5)

    pkg_input = ft.TextField(hint_text="Nome pacchetto (es. requests, pandas)...", expand=True, text_size=12)
    pkg_list_view = ft.ListView(expand=True, padding=10, spacing=5)

    # --- COMPONENTI MODULO FIREBIRD ---
    fb_host = ft.TextField(label="Host / DSN", value="localhost", width=150, text_size=12)
    fb_path = ft.TextField(label="Percorso DB (.fdb)", value="C:/App/Data/App.FDB", expand=True, text_size=12)
    fb_user = ft.TextField(label="User", value="SYSDBA", width=120, text_size=12)
    fb_password = ft.TextField(label="Password", value="masterkey", password=True, can_reveal_password=True, width=150, text_size=12)
    fb_query = ft.TextField(label="Query SQL", value="SELECT * FROM PAZIENTI", multiline=True, height=60, text_size=12, expand=True)
    fb_result_table = ft.DataTable(
        columns=[ft.DataColumn(ft.Text("Risultati"))],
        rows=[]
    )
    fb_status_text = ft.Text(f"Workspace attivo in: {WORK_DIR}", color="#9E9E9E", size=12)

    def test_firebird_connection(e):
        if "firebirdsql" not in project_dependencies:
            project_dependencies.append("firebirdsql")
            refresh_package_list()
            update_code_files()

        fb_status_text.value = "Connessione in corso a Firebird..."
        page.update()

        try:
            import firebirdsql
            con = firebirdsql.connect(
                host=fb_host.value,
                database=fb_path.value,
                user=fb_user.value,
                password=fb_password.value,
                charset='UTF8'
            )
            cur = con.cursor()
            cur.execute(fb_query.value)
            
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
            con.close()

            fb_result_table.columns = [ft.DataColumn(ft.Text(col, weight=ft.FontWeight.BOLD)) for col in columns]
            fb_result_table.rows = [
                ft.DataRow(cells=[ft.DataCell(ft.Text(str(val if val is not None else ""))) for val in row])
                for row in rows[:50]
            ]
            fb_status_text.value = f"Query eseguita con successo. {len(rows)} record trovati."
            fb_status_text.color = "#4CAF50"
        except Exception as ex:
            fb_status_text.value = f"Errore Firebird: {str(ex)}"
            fb_status_text.color = "#F44336"
        page.update()

    def generate_firebird_logic_with_ollama(e):
        ai_output_view.controls.append(ft.Text("Tu: Genera una classe Python per Firebird SQL", color="#80DEEA"))
        page.update()

        prompt = (
            "Sei un assistente esperto in Python e database Firebird SQL per un gestionale dentistico. "
            "Scrivi una classe Python robusta chiamata 'FirebirdDBManager' che gestisca la connessione, "
            "la chiusura e l'esecuzione di query SQL (SELECT, INSERT, UPDATE) con supporto ai parametri "
            "per evitare SQL injection. Includi la gestione delle eccezioni (try/except/finally) "
            "e l'uso della codifica UTF8. Restituisci solo codice Python puro senza markdown aggiuntivo."
        )

        data = json.dumps({"model": "llama3", "prompt": prompt, "stream": False}).encode("utf-8")
        req = urllib.request.Request("http://localhost:11434/api/generate", data=data, headers={"Content-Type": "application/json"})
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res_json = json.loads(response.read().decode("utf-8"))
                generated_code = res_json.get("response", "")
                
                code_logic_view.value = (
                    "# logic.py - Gestione logica e Database Firebird (Generato da Ollama)\n"
                    "import flet as ft\n"
                    "import firebirdsql\n\n"
                    f"{generated_code}\n\n"
                    "def esegui_ricerca(e: ft.ControlEvent):\n"
                    "    print('Ricerca avviata ...')\n"
                    "    e.page.update()\n"
                )
                update_code_files()
                ai_output_view.controls.append(ft.Text("Ollama: Classe Firebird generata e scritta in logic.py!", color="#A5D6A7"))
                page.show_dialog(ft.SnackBar(content=ft.Text("Codice Firebird inserito in logic.py con successo!")))
        except Exception as ex:
            ai_output_view.controls.append(ft.Text(f"Ollama Errore: {str(ex)}", color="#EF9A9A"))
        
        page.update()

    def call_ollama_ai():
        prompt = ai_prompt_input.value
        if not prompt:
            return
        ai_output_view.controls.append(ft.Text(f"Tu: {prompt}", color="#80DEEA"))
        ai_prompt_input.value = ""
        page.update()

        data = json.dumps({"model": "llama3", "prompt": f"Sei un assistente Flet. Rispondi alla richiesta: {prompt}", "stream": False}).encode("utf-8")
        req = urllib.request.Request("http://localhost:11434/api/generate", data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                res_json = json.loads(response.read().decode("utf-8"))
                reply = res_json.get("response", "Nessuna risposta.")
                ai_output_view.controls.append(ft.Text(f"Ollama: {reply}", color="#A5D6A7"))
        except Exception:
            ai_output_view.controls.append(ft.Text("Ollama: Impossibile connettersi a http://localhost:11434.", color="#EF9A9A"))
        page.update()

    # --- TAB SWITCHER ---
    tab_content_container = ft.Container(expand=True, bgcolor="#1E1E1E", padding=10)
    active_bottom_tab = ["ui"]
    code_panel_collapsed = [False]

    ui_tab_button = ft.TextButton("ui", on_click=lambda e: switch_tab("ui"))
    logic_tab_button = ft.TextButton("logic", on_click=lambda e: switch_tab("logic"))
    firebird_tab_button = ft.TextButton(
        "Firebird DB", on_click=lambda e: switch_tab("firebird")
    )
    packages_tab_button = ft.TextButton(
        "Pacchetti", on_click=lambda e: switch_tab("packages")
    )
    ai_tab_button = ft.TextButton(
        "Ollama AI", on_click=lambda e: switch_tab("ai")
    )
    code_panel_toggle_button = ft.IconButton(
        icon=ft.Icons.EXPAND_LESS,
        tooltip="Nascondi pannello codice",
        on_click=lambda e: toggle_code_panel(),
    )
    code_tab_buttons = {
        "ui": ui_tab_button,
        "logic": logic_tab_button,
        "firebird": firebird_tab_button,
        "packages": packages_tab_button,
        "ai": ai_tab_button,
    }

    def update_code_tab_styles():
        for tab_name, button in code_tab_buttons.items():
            is_active = tab_name == active_bottom_tab[0]
            button.style = ft.ButtonStyle(
                bgcolor="#263238" if is_active else None,
                color="#80DEEA" if is_active else None,
                side=ft.BorderSide(
                    1,
                    "#00ACC1" if is_active else "#555555",
                ),
            )

    def toggle_code_panel():
        code_panel_collapsed[0] = not code_panel_collapsed[0]
        tab_content_container.visible = not code_panel_collapsed[0]
        code_panel_wrapper.expand = not code_panel_collapsed[0]
        code_panel_wrapper.height = 42 if code_panel_collapsed[0] else None
        code_panel_toggle_button.icon = (
            ft.Icons.EXPAND_MORE
            if code_panel_collapsed[0]
            else ft.Icons.EXPAND_LESS
        )
        code_panel_toggle_button.tooltip = (
            "Mostra pannello codice"
            if code_panel_collapsed[0]
            else "Nascondi pannello codice"
        )
        page.update()

    def update_project_file_labels():
        if not file_open[0]:
            project_title.value = "Nessun file aperto"
            ui_tab_button.content = "ui"
            logic_tab_button.content = "logic"
            file_close_button.visible = False
            file_open_button.visible = True
            if top_bar_ref[0] is not None:
                top_bar_ref[0].content.controls[1] = file_open_button
                top_bar_ref[0].content.update()
            return
        ui_name = os.path.basename(project_file_path("ui"))
        logic_path = project_file_path("logic")
        logic_name = os.path.basename(logic_path) if logic_path else "nessun file logica"
        ui_tab_button.content = ui_name
        logic_tab_button.content = logic_name
        project_title.value = project_display_name[0] or ui_name
        file_close_button.visible = True
        file_open_button.visible = False
        if top_bar_ref[0] is not None:
            top_bar_ref[0].content.controls[1] = file_close_button
            top_bar_ref[0].content.update()

    def switch_tab(view_name):
        active_bottom_tab[0] = view_name
        if view_name == "ui":
            active_code_view[0] = "ui"
            tab_content_container.content = code_ui_scroll if code_highlight_enabled[0] else code_ui_view
        elif view_name == "logic":
            active_code_view[0] = "logic"
            tab_content_container.content = code_logic_scroll if code_highlight_enabled[0] else code_logic_view
        elif view_name == "firebird":
            tab_content_container.content = ft.Column([
                ft.Text("Gestione & Test Database Firebird SQL", weight=ft.FontWeight.BOLD, size=14),
                ft.Row([fb_host, fb_path, fb_user, fb_password], spacing=10),
                ft.Row([fb_query, ft.IconButton(icon=ft.Icons.PLAY_ARROW, tooltip="Esegui Query", on_click=test_firebird_connection)], spacing=10),
                fb_status_text,
                ft.Divider(),
                ft.Row([fb_result_table], scroll=ft.ScrollMode.AUTO, expand=True)
            ], expand=True, scroll=ft.ScrollMode.AUTO)
        elif view_name == "packages":
            tab_content_container.content = ft.Column([
                ft.Text("Dipendenze del Progetto (requirements.txt)", weight=ft.FontWeight.BOLD),
                pkg_list_view,
                ft.Row([
                    pkg_input,
                    ft.IconButton(icon=ft.Icons.ADD, tooltip="Aggiungi Modulo", on_click=lambda e: add_package(pkg_input.value))
                ])
            ], expand=True)
        elif view_name == "ai":
            tab_content_container.content = ft.Column([
                ai_output_view,
                ft.Row([
                    ft.TextButton("Genera Logica UI", on_click=lambda e: call_ollama_ai()),
                    ft.TextButton("Genera Classe Firebird DB", on_click=generate_firebird_logic_with_ollama),
                ], spacing=10),
                ft.Row([
                    ai_prompt_input,
                    ft.IconButton(icon=ft.Icons.SEND, icon_color="#00ACC1", tooltip="Invia", on_click=lambda e: call_ollama_ai())
                ], spacing=10)
            ], expand=True)
        update_code_tab_styles()
        page.update()

    tab_bar = ft.Container(
        bgcolor="#181818", padding=5,
        content=ft.Row([
            ui_tab_button,
            logic_tab_button,
            code_highlight_button,
            firebird_tab_button,
            packages_tab_button,
            ai_tab_button,
            ft.Container(expand=True),
            code_panel_toggle_button,
        ], spacing=5)
    )

    code_panel_wrapper = ft.Column([
        tab_bar,
        tab_content_container
    ], expand=True, spacing=0)

    def get_flet_init_parameters(control_type):
        control_class = getattr(ft, control_type, None)
        if control_class is None:
            return set()
        try:
            signature = inspect.signature(control_class.__init__)
        except (TypeError, ValueError):
            return set()
        return {
            name
            for name in signature.parameters
            if name not in {"self", "args", "kwargs", "controls", "content"}
        } | ({"controls"} if "controls" in signature.parameters else set()) | (
            {"content"} if "content" in signature.parameters else set()
        )

    def format_generated_prop(control_type, key, value):
        valid_parameters = get_flet_init_parameters(control_type)
        output_key = key
        if key == "text" and "content" in valid_parameters and key not in valid_parameters:
            output_key = "content"

        if output_key not in valid_parameters:
            return ""
        if output_key == "on_click" and isinstance(value, str):
            return f"on_click=getattr({project_module_name('logic')}, {value!r}, None)"
        if output_key == "icon" and isinstance(value, str):
            icon_name = value.removeprefix("ft.Icons.").removeprefix("Icons.")
            if icon_name in FLET_ICON_NAMES:
                return f"icon=ft.Icons.{icon_name}"
        return f"{output_key}={value!r}"

    def _generate_ui_code(node, indent=0):
        ind = " " * indent
        n_type = node["type"]
        props = node.get("props", {})

        props_str = ", ".join(
            generated_prop
            for k, v in props.items()
            if (generated_prop := format_generated_prop(n_type, k, v))
        )

        if n_type == "SubmenuButton":
            controls_code = ",\n".join(
                generate_ui_code(child, indent + 8)
                for child in node.get("children", []) or []
                if child
            )
            arguments = [
                f"content=ft.Text({props['content']!r})"
                if key == "content" and isinstance(props["content"], str)
                else generated_prop
                for key, value in props.items()
                if (generated_prop := format_generated_prop(n_type, key, value))
            ]
            arguments.append(
                f"controls=[\n{controls_code}\n{ind}]"
                if controls_code else "controls=[]"
            )
            return f"{ind}ft.SubmenuButton({', '.join(arguments)})"
        if n_type in CONTROL_COLLECTION_PROPERTIES and n_type not in {
            "PopupMenuButton", "Dropdown",
        }:
            children_code = ",\n".join([generate_ui_code(c, indent + 8) for c in node.get("children", []) if c])
            collection_name = CONTROL_COLLECTION_PROPERTIES[n_type]
            controls_code = (
                f"{collection_name}=[\n{children_code}\n{ind}]"
                if children_code
                else f"{collection_name}=[]"
            )
            args = [controls_code]
            if props_str:
                args.append(props_str)
            args_code = ",\n".join(args)
            return f"{ind}ft.{n_type}(\n{args_code}\n{ind})"
        elif n_type == "PopupMenuButton":
            items_code = ",\n".join(
                generate_ui_code(child, indent + 8)
                for child in node.get("children", []) or []
                if child
            )
            args = [props_str] if props_str else []
            args.append(
                f"items=[\n{items_code}\n{ind}]" if items_code else "items=[]"
            )
            return f"{ind}ft.PopupMenuButton({', '.join(args)})"
        elif n_type in {"PopupMenuItem", "MenuItemButton"}:
            args = []
            for key, value in props.items():
                if key == "content" and isinstance(value, str):
                    args.append(f"content=ft.Text({value!r})")
                elif generated_prop := format_generated_prop(n_type, key, value):
                    args.append(generated_prop)
            return f"{ind}ft.{n_type}({', '.join(args)})"
        elif n_type == "Dropdown":
            option_values = props.get("options", [])
            options_code = ", ".join(
                "ft.DropdownOption("
                f"key={option.get('key')!r}, text={option.get('text')!r})"
                for option in option_values
                if isinstance(option, dict)
            )
            args = [
                generated_prop
                for key, value in props.items()
                if key != "options"
                and (generated_prop := format_generated_prop(n_type, key, value))
            ]
            args.append(f"options=[{options_code}]")
            return f"{ind}ft.Dropdown({', '.join(args)})"
        elif n_type in {"Container", "Card", "SafeArea", "Tabs"}:
            node_children = [child for child in node.get("children", []) or [] if child]
            if len(node_children) > 1:
                children_code = ",\n".join(
                    generate_ui_code(child, indent + 12) for child in node_children
                )
                child_code = (
                    f"{' ' * (indent + 8)}ft.Column(controls=[\n"
                    f"{children_code}\n"
                    f"{' ' * (indent + 8)}])"
                )
            else:
                child_code = (
                    generate_ui_code(node_children[0], indent + 8)
                    if node_children else "None"
                )
            args = [f"content=\n{child_code}"]
            if props_str:
                args.append(props_str)
            args_code = ",\n".join(args)
            return f"{ind}ft.{n_type}({args_code}\n{ind})"
        control_code = f"ft.{n_type}({props_str})"
        children = [child for child in node.get("children", []) or [] if child]
        if children:
            children_code = ",\n".join(
                generate_ui_code(child, indent + 4) for child in children
            )
            return (
                f"{ind}ft.Column(controls=[\n"
                f"{' ' * (indent + 4)}{control_code},\n"
                f"{children_code}\n"
                f"{ind}])"
            )
        return f"{ind}{control_code}"

    def generate_ui_code(node, indent=0):
        code = _generate_ui_code(node, indent)
        comment = str(node.get("_comment", "")).strip()
        if not comment:
            return code
        ind = " " * indent
        comment_lines = [
            f"{ind}# {line}" if line else f"{ind}#"
            for line in comment.splitlines()
        ]
        return "\n".join((*comment_lines, code))

    def generate_layout_ui_source():
        ui_lines = [
            "import flet as ft",
            f"import {project_module_name('logic')}",
            "",
            "def main(page: ft.Page):",
            f"    page.theme_mode = ft.ThemeMode.{project_theme_mode[0].name}",
        ]
        window_props = layout_data.get("window_props", {})
        for key, value in window_props.items():
            if key == "center":
                if value:
                    ui_lines.append("    page.window.center()")
                continue
            if key == "theme_mode":
                continue
            target = "page.title" if key == "title" else f"page.window.{key}"
            ui_lines.append(
                f"    {target} = {_window_value_expression(key, value)}"
            )
        if layout_data.get("children"):
            ui_body = generate_ui_code(layout_data, indent=4)
            ui_lines.append(f"    page.add({ui_body.lstrip()})")
        else:
            ui_lines.append("    pass")
        ui_lines.extend([
            "",
            "if __name__ == \"__main__\":",
            "    ft.run(main)",
            "",
        ])
        return "\n".join(ui_lines)

    def _window_value_expression(key, value):
        if key == "theme_mode":
            mode = (
                str(value)
                .removeprefix("ft.ThemeMode.")
                .removeprefix("ThemeMode.")
                .upper()
            )
            if mode not in {"LIGHT", "DARK", "SYSTEM"}:
                raise ValueError(f"Tema progetto non supportato: {value}")
            return f"ft.ThemeMode.{mode}"
        if not isinstance(value, str):
            return repr(value)
        if key in {"title", "icon", "badge_label"}:
            return repr(value)
        stripped = value.strip()
        if not stripped:
            return "''"
        if key.startswith("on_") or stripped.startswith(("ft.", "page.")):
            ast.parse(stripped, mode="eval")
            return stripped
        try:
            literal = ast.literal_eval(stripped)
        except (ValueError, TypeError, SyntaxError):
            return repr(value)
        if isinstance(literal, (bool, int, float)) or literal is None:
            return repr(literal)
        return repr(value)

    def _read_imported_window_properties(source_path):
        if not source_path or not os.path.exists(source_path):
            return {}
        with open(source_path, "r", encoding="utf-8") as source_file:
            source = source_file.read()
        tree = ast.parse(source, filename=source_path)
        main_function = next(
            (
                node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "main"
                and node.args.args
            ),
            None,
        )
        if main_function is None:
            return {}
        page_name = main_function.args.args[0].arg
        properties = {}

        def property_for_target(target):
            if isinstance(target, ast.Attribute) and (
                target.attr == "title"
                and isinstance(target.value, ast.Name)
                and target.value.id == page_name
            ):
                return "title"
            if isinstance(target, ast.Attribute) and (
                target.attr == "theme_mode"
                and isinstance(target.value, ast.Name)
                and target.value.id == page_name
            ):
                return "theme_mode"
            if (
                isinstance(target, ast.Call)
                and isinstance(target.func, ast.Attribute)
                and target.func.attr == "center"
                and isinstance(target.func.value, ast.Attribute)
                and target.func.value.attr == "window"
                and isinstance(target.func.value.value, ast.Name)
                and target.func.value.value.id == page_name
            ):
                return "center"
            if isinstance(target, ast.Attribute) and (
                isinstance(target.value, ast.Attribute)
                and target.value.attr == "window"
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == page_name
            ):
                return target.attr
            return None

        for statement in main_function.body:
            if isinstance(statement, ast.Assign):
                targets = statement.targets
                value = statement.value
            elif isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
                value = statement.value
            elif (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Call)
            ):
                targets = [statement.value]
                value = ast.Constant(value=True)
            else:
                continue
            if value is None:
                continue
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "window"
                    and isinstance(target.value, ast.Name)
                    and target.value.id == page_name
                    and isinstance(value, ast.Call)
                    and (
                        isinstance(value.func, ast.Name)
                        and value.func.id == "Window"
                        or isinstance(value.func, ast.Attribute)
                        and value.func.attr == "Window"
                    )
                ):
                    for keyword in value.keywords:
                        if keyword.arg in WINDOW_SCHEMA and keyword.arg != "title":
                            try:
                                properties[keyword.arg] = ast.literal_eval(
                                    keyword.value
                                )
                            except (ValueError, TypeError, SyntaxError):
                                properties[keyword.arg] = ast.unparse(keyword.value)
                    continue
                property_name = property_for_target(target)
                if property_name not in WINDOW_SCHEMA:
                    continue
                try:
                    properties[property_name] = ast.literal_eval(value)
                except (ValueError, TypeError, SyntaxError):
                    properties[property_name] = ast.unparse(value)
        return properties

    def create_window_node():
        if single_file_mode[0]:
            props = _read_imported_window_properties(project_file_path("ui"))
            return {
                "id": "window",
                "type": "Window",
                "props": props,
                "_window": True,
                "_imported": True,
                "_source_path": project_file_path("ui"),
            }
        return {
            "id": "window",
            "type": "Window",
            "props": layout_data.setdefault("window_props", {}),
            "_window": True,
        }

    def update_code_files():
        if not project_code_authoritative[0]:
            code_ui_view.value = generate_layout_ui_source()
            if not code_logic_view.value:
                code_logic_view.value = "# logic.py - Gestione logica\nimport flet as ft\n"
        
        with open(project_file_path("ui"), "w", encoding="utf-8") as f:
            f.write(code_ui_view.value)
        logic_path = project_file_path("logic")
        if logic_path is not None:
            with open(logic_path, "w", encoding="utf-8") as f:
                f.write(code_logic_view.value)
        with open(os.path.join(project_folder[0], "requirements.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(project_dependencies))
        update_code_highlighting()

    def auto_save_project():
        if single_file_mode[0]:
            update_code_files()
            return
        with open(os.path.join(project_folder[0], f"{project_base_name[0]}_project.json"), "w", encoding="utf-8") as f:
            json.dump(layout_data, f, indent=4)
        update_code_files()

    def refresh_package_list():
        pkg_list_view.controls.clear()
        for pkg in project_dependencies:
            pkg_list_view.controls.append(ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE, color="#4CAF50", size=16),
                ft.Text(pkg, expand=True),
                ft.IconButton(icon=ft.Icons.DELETE, icon_size=16, icon_color="#F44336", tooltip="Elimina", on_click=lambda e, p=pkg: remove_package(p))
            ]))
        page.update()

    def add_package(pkg_name):
        if pkg_name and pkg_name not in project_dependencies:
            project_dependencies.append(pkg_name)
            pkg_input.value = ""
            refresh_package_list()
            update_code_files()

    def remove_package(pkg_name):
        if pkg_name in project_dependencies and pkg_name != "flet":
            project_dependencies.remove(pkg_name)
            refresh_package_list()
            update_code_files()

    def stop_live_preview():
        if running_process[0]:
            if running_process[0].poll() is None:
                running_process[0].terminate()
                try:
                    running_process[0].wait(timeout=3)
                except subprocess.TimeoutExpired:
                    running_process[0].kill()
                    running_process[0].wait()
            running_process[0] = None
        if running_preview_directory[0] is not None:
            running_preview_directory[0].cleanup()
            running_preview_directory[0] = None

    def render_node(node):
        if not node:
            return ft.Container()
            
        n_type = node["type"]
        props = node.get("props", {})
        child_widgets = [render_node(c) for c in node.get("children", []) or []]
        project_is_dark = project_theme_mode[0] == ft.ThemeMode.DARK
        default_container_background = "#2B2D30" if project_is_dark else "#FFFFFF"
        default_card_background = "#2B2D30" if project_is_dark else "#FFFFFF"
        default_project_text_color = (
            "#212121"
            if not project_is_dark
            else "#FFFFFF"
        )

        if n_type == "Column":
            widget = ft.Column(
                controls=child_widgets,
                alignment=props.get("alignment", "start"),
                horizontal_alignment=props.get("horizontal_alignment", "start"),
                spacing=props.get("spacing", 10),
            )
        elif n_type == "Row":
            widget = ft.Row(
                controls=child_widgets,
                alignment=props.get("alignment", "start"),
                vertical_alignment=props.get("vertical_alignment", "center"),
                spacing=props.get("spacing", 10),
            )
        elif n_type == "Container":
            widget = ft.Container(
                content=child_widgets[0] if child_widgets else None,
                bgcolor=props.get("bgcolor", default_container_background),
                padding=props.get("padding", 0),
                alignment=props.get("alignment"),
                width=props.get("width"),
                height=props.get("height"),
            )
        elif n_type == "Card":
            widget = ft.Card(
                content=child_widgets[0] if child_widgets else None,
                elevation=props.get("elevation", 1),
                bgcolor=props.get("bgcolor", default_card_background),
            )
        elif n_type == "ListView":
            widget = ft.ListView(
                controls=child_widgets,
                spacing=props.get("spacing", 10),
                height=props.get("height", 200),
            )
        elif n_type == "SubmenuButton":
            content = props.get("content", "Nuovo menu")
            if isinstance(content, str):
                content = ft.Text(content)
            widget = ft.SubmenuButton(
                content=content,
                controls=child_widgets,
            )
        elif n_type in CONTROL_COLLECTION_PROPERTIES and n_type != "PopupMenuButton":
            control_class = getattr(ft, n_type, None)
            if control_class is None:
                widget = ft.Column(controls=child_widgets, tight=True)
            else:
                try:
                    accepted_parameters = inspect.signature(
                        control_class.__init__
                    ).parameters
                except (TypeError, ValueError):
                    accepted_parameters = {}
                control_props = {
                    key: value for key, value in props.items()
                    if key in accepted_parameters
                    and isinstance(value, (str, int, float, bool))
                }
                control_props[CONTROL_COLLECTION_PROPERTIES[n_type]] = child_widgets
                widget = control_class(**control_props)
        elif n_type in {"SafeArea", "Tabs"}:
            control_class = getattr(ft, n_type, ft.Container)
            content = child_widgets[0] if child_widgets else None
            if len(child_widgets) > 1:
                content = ft.Column(controls=child_widgets, tight=True)
            widget = control_class(
                content=content
            )
        elif n_type in BUTTON_TYPES or n_type in {"CupertinoButton", "TextButton"}:
            button_class = getattr(ft, n_type, None) or getattr(ft, "Button", None)
            if button_class is None:
                widget = ft.Text(
                    props.get(
                        "content", props.get("text", props.get("value", "Button"))
                    ),
                    color=props.get("color", default_project_text_color),
                )
            else:
                button_props = {
                    "content": props.get(
                        "content", props.get("text", props.get("value", f"Nuovo {n_type}"))
                    ),
                    "width": props.get("width"),
                    "height": props.get("height"),
                }
                if getattr(ft, "TextButton", None) is button_class:
                    button_props["style"] = ft.ButtonStyle(
                        color=props.get("color", default_project_text_color),
                        bgcolor=props.get("bgcolor"),
                    )
                if n_type not in {"CupertinoButton"} and props.get("icon"):
                    icon_name = str(props["icon"]).removeprefix("ft.Icons.").removeprefix("Icons.")
                    if icon_name in FLET_ICON_NAMES:
                        button_props["icon"] = getattr(ft.Icons, icon_name)
                widget = button_class(**{
                    key: value for key, value in button_props.items()
                    if value is not None
                })
        elif n_type == "IconButton":
            icon_name = str(props.get("icon", "ADD")).removeprefix("ft.Icons.").removeprefix("Icons.")
            icon_value = getattr(ft.Icons, icon_name, ft.Icons.ADD)
            widget = ft.IconButton(
                icon=icon_value,
                icon_color=props.get("icon_color", props.get("color")),
                tooltip=props.get("tooltip"),
            )
        elif n_type == "PopupMenuItem":
            content = props.get("content", "Nuova voce")
            if isinstance(content, str):
                content = ft.Text(content)
            widget = ft.PopupMenuItem(
                content=content,
                icon=props.get("icon"),
            )
        elif n_type == "MenuItemButton":
            content = props.get("content", props.get("text", "Nuova voce"))
            if isinstance(content, str):
                content = ft.Text(content)
            widget = ft.MenuItemButton(
                content=content,
                leading=props.get("leading"),
                trailing=props.get("trailing"),
                close_on_click=props.get("close_on_click", True),
            )
        elif n_type == "PopupMenuButton":
            menu_items = []
            for child in node.get("children", []) or []:
                item_props = child.get("props", {})
                content = item_props.get(
                    "content", item_props.get("text", item_props.get("value", "Nuova voce"))
                )
                if isinstance(content, str):
                    content = tree_text_from_source(content) or content
                icon = item_props.get("icon")
                if isinstance(icon, str):
                    icon_name = icon.removeprefix("ft.Icons.").removeprefix("Icons.")
                    icon = getattr(ft.Icons, icon_name, None)
                menu_items.append(ft.PopupMenuItem(content=content, icon=icon))
            widget = ft.PopupMenuButton(
                content=props.get("content"),
                icon=getattr(
                    ft.Icons,
                    str(props.get("icon", "MORE_VERT")).removeprefix("ft.Icons.").removeprefix("Icons."),
                    ft.Icons.MORE_VERT,
                ),
                items=menu_items,
            )
        elif n_type == "Dropdown":
            options = [
                ft.DropdownOption(key=option.get("key"), text=option.get("text"))
                for option in props.get("options", [])
                if isinstance(option, dict)
            ]
            dropdown_props = {
                key: value for key, value in props.items()
                if key in inspect.signature(ft.Dropdown.__init__).parameters
                and key != "options"
                and isinstance(value, (str, int, float, bool))
            }
            widget = ft.Dropdown(options=options, **dropdown_props)
        elif n_type == "TextField":
            widget = ft.TextField(
                label=props.get("label", ""),
                value=props.get("value", ""),
                width=props.get("width", 200),
                height=props.get("height"),
                color=props.get("color", default_project_text_color),
                bgcolor=props.get("bgcolor"),
                border_color=props.get("border_color"),
                text_size=props.get("text_size"),
            )
        elif n_type == "Checkbox":
            widget = ft.Checkbox(
                label=props.get("label", ""),
                value=props.get("value", False),
                fill_color=props.get("fill_color", props.get("color")),
            )
        elif n_type == "Switch":
            widget = ft.Switch(
                label=props.get("label", ""),
                value=props.get("value", False),
                active_color=props.get("active_color", props.get("color")),
            )
        elif n_type == "Image":
            widget = ft.Image(
                src=props.get("src", ""),
                width=props.get("width"),
                height=props.get("height"),
            )
        else:
            widget = ft.Text(
                props.get("value", props.get("text", "Testo")),
                size=props.get("size", 14),
                color=props.get("color", default_project_text_color),
                bgcolor=props.get("bgcolor"),
                text_align=props.get("text_align"),
            )
        if child_widgets and n_type not in {
            *CONTROL_COLLECTION_PROPERTIES.keys(), "Column", "Row", "ListView",
            "SafeArea", "Tabs",
        }:
            if n_type in {"Container", "Card"}:
                child_content = (
                    ft.Column(controls=child_widgets, tight=True)
                    if len(child_widgets) > 1
                    else child_widgets[0]
                )
                widget.content = child_content
            else:
                widget = ft.Column(controls=[widget, *child_widgets], tight=True)

        is_selected = selected_node[0] and selected_node[0]["id"] == node["id"]
        preview_node = ft.Container(
            content=widget,
            bgcolor="#1A3A4A" if is_selected else None,
            padding=6,
            border_radius=6,
            border=ft.Border.all(2, "#F44336") if is_selected else None,
            on_click=(
                (lambda e, n=node: select_element(n))
                if preview_select_enabled[0]
                else None
            )
        )

        return preview_node

    FLET_ENUM_OPTIONS = {
        "theme_mode": ["LIGHT", "DARK", "SYSTEM"],
        "alignment": ["start", "center", "end", "spaceBetween", "spaceAround", "spaceEvenly"],
        "horizontal_alignment": ["start", "center", "end", "stretch"],
        "vertical_alignment": ["start", "center", "end", "stretch"],
        "main_axis_alignment": ["start", "center", "end", "spaceBetween", "spaceAround", "spaceEvenly"],
        "cross_axis_alignment": ["start", "center", "end", "stretch"],
        "text_align": ["left", "right", "center", "justify", "start", "end"],
        "scroll": ["auto", "always", "adaptive", "hidden", "none"],
        "shape": ["rectangle", "circle"],
        "image_fit": ["none", "contain", "cover", "fill", "fitWidth", "fitHeight"],
    }
    FLET_CONTAINER_ALIGNMENTS = [
        "topLeft", "topCenter", "topRight", "centerLeft", "center",
        "centerRight", "bottomLeft", "bottomCenter", "bottomRight",
    ]

    COLOR_PROPERTIES = {
        "color", "bgcolor", "background_color", "border_color", "overlay_color",
        "selection_color", "cursor_color", "icon_color", "shadow_color",
    }

    def property_example(node_type, key):
        if node_type == "Window":
            window_examples = {
                "center": True,
                "title": "Titolo applicazione",
                "theme_mode": "SYSTEM",
                "bgcolor": "#212121",
                "icon": "assets/icon.png",
            }
            if key in window_examples:
                return window_examples[key]
            if key.startswith("on_"):
                return "None"
        annotation = None
        control_class = getattr(ft, node_type, None)
        if control_class is not None:
            try:
                annotation = inspect.signature(control_class.__init__).parameters[key].annotation
            except (KeyError, TypeError, ValueError):
                pass
        if typing.get_origin(annotation) is typing.Annotated:
            annotation = typing.get_args(annotation)[0]
        annotation_types = typing.get_args(annotation) or (annotation,)

        examples = {
            "alignment": "center",
            "bgcolor": "#2196F3",
            "border_color": "#2196F3",
            "color": "#212121",
            "content": "Esempio testo",
            "height": 200,
            "hint_text": "Inserisci un valore",
            "icon": "ADD",
            "icon_color": "#2196F3",
            "label": "Esempio",
            "max": 1,
            "min": 0,
            "opacity": 1,
            "size": 16,
            "spacing": 10,
            "text": "Esempio testo",
            "text_size": 14,
            "value": "Esempio testo",
            "width": 200,
        }
        if key in examples:
            example = examples[key]
            if key == "value":
                if bool in annotation_types:
                    return True
                if int in annotation_types or float in annotation_types:
                    return 0
            return example

        if bool in annotation_types:
            return True
        if int in annotation_types or float in annotation_types:
            return 1
        return "Esempio"

    def property_limits_tooltip(node_type, key, props):
        control_class = getattr(ft, node_type, None)
        if control_class is None:
            return "Minimo: non specificato da Flet\nMassimo: non specificato da Flet"
        try:
            parameters = inspect.signature(control_class.__init__).parameters
            parameter = parameters.get(key)
        except (TypeError, ValueError):
            parameter = None

        lower = None
        upper = None
        annotation = parameter.annotation if parameter is not None else None
        if typing.get_origin(annotation) is typing.Annotated:
            for rule in typing.get_args(annotation)[1:]:
                check = getattr(rule, "_check", None)
                if check is None:
                    continue
                rule_name = check.__qualname__.split(".")[1]
                closure_values = [
                    cell.cell_contents for cell in (check.__closure__ or ())
                ]
                numeric_values = [
                    value for value in closure_values
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                ]
                bound = numeric_values[0] if numeric_values else None
                if bound is None:
                    related_key = next(
                        (
                            value for value in closure_values
                            if isinstance(value, str) and value in parameters
                        ),
                        None,
                    )
                    if related_key is not None:
                        related_parameter = parameters[related_key]
                        bound = props.get(related_key, related_parameter.default)
                        if bound is inspect.Parameter.empty:
                            bound = None

                if rule_name in {"gt", "ge", "gt_field", "ge_field"} and bound is not None:
                    lower = (bound, rule_name in {"ge", "ge_field"})
                elif rule_name in {"lt", "le", "lt_field", "le_field"} and bound is not None:
                    upper = (bound, rule_name in {"le", "le_field"})
                elif rule_name == "between" and len(numeric_values) >= 2:
                    lower = (min(numeric_values), True)
                    upper = (max(numeric_values), True)

        if key == "max_length":
            minimum = "1 (oppure -1 per nessun limite)"
        elif lower is None:
            minimum = "non specificato da Flet"
        else:
            minimum = f"{'≥' if lower[1] else '>'} {lower[0]}"

        if upper is None:
            maximum = "non specificato da Flet"
        else:
            maximum = f"{'≤' if upper[1] else '<'} {upper[0]}"
        return f"Minimo: {minimum}\nMassimo: {maximum}"

    FLET_COLOR_PALETTE = [
        ("RED", "#F44336"), ("PINK", "#E91E63"), ("PURPLE", "#9C27B0"),
        ("DEEP_PURPLE", "#673AB7"), ("INDIGO", "#3F51B5"), ("BLUE", "#2196F3"),
        ("LIGHT_BLUE", "#03A9F4"), ("CYAN", "#00BCD4"), ("TEAL", "#009688"),
        ("GREEN", "#4CAF50"), ("LIGHT_GREEN", "#8BC34A"), ("LIME", "#CDDC39"),
        ("YELLOW", "#FFEB3B"), ("AMBER", "#FFC107"), ("ORANGE", "#FF9800"),
        ("DEEP_ORANGE", "#FF5722"), ("BROWN", "#795548"), ("GREY", "#9E9E9E"),
        ("BLUE_GREY", "#607D8B"), ("BLACK", "#000000"), ("WHITE", "#FFFFFF"),
        ("TRANSPARENT", "transparent"),
    ]

    def collect_used_colors():
        colors = []
        def visit(current):
            for key, value in current.get("props", {}).items():
                if key in COLOR_PROPERTIES and isinstance(value, str) and value not in colors:
                    colors.append(value)
            for child in current.get("children", []) or []:
                visit(child)
        visit(layout_data)
        return colors

    def close_color_picker(dialog):
        page.pop_dialog()

    def choose_color(dialog, key, color):
        stage_property_value(selected_node[0], key, color)
        close_color_picker(dialog)

    def show_color_picker(key):
        current_value = str(selected_node[0].get("props", {}).get(key, ""))
        used_colors = collect_used_colors()
        used_set = set(used_colors)
        palette = [("GIÀ USATI", color) for color in used_colors]
        palette.extend((name, color) for name, color in FLET_COLOR_PALETTE if color not in used_set)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Scegli colore per {key}"),
            content=ft.Column([
                ft.Text(f"Valore attuale: {current_value or 'nessun colore'}", size=12, color="#B0BEC5"),
                ft.Text("Colori già usati", weight=ft.FontWeight.BOLD, size=12),
                ft.Row([
                    ft.Container(
                        width=34, height=34, bgcolor=color,
                        border=ft.Border.all(2, "#FFFFFF" if color == current_value else "#555555"),
                        border_radius=5, tooltip=color,
                        on_click=lambda e, c=color: choose_color(dialog, key, c),
                    ) for color in used_colors
                ], wrap=True, spacing=6),
                ft.Divider(height=8),
                ft.Text("Palette standard Flet", weight=ft.FontWeight.BOLD, size=12),
                ft.Row([
                    ft.Container(
                        width=34, height=34, bgcolor=color,
                        border=ft.Border.all(2, "#FFFFFF" if color == current_value else "#555555"),
                        border_radius=5, tooltip=name,
                        on_click=lambda e, c=color: choose_color(dialog, key, c),
                    ) for name, color in palette if color not in used_set
                ], wrap=True, spacing=6),
            ], tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Annulla", on_click=lambda e: close_color_picker(dialog))],
        )
        page.show_dialog(dialog)

    def property_editor(key, val, node_type, props, on_change):
        is_empty = val is None or (isinstance(val, str) and not val.strip())
        example = property_example(node_type, key)
        hint_text = f"Esempio: {example}" if is_empty else None
        tooltip = property_limits_tooltip(node_type, key, props)
        if key in COLOR_PROPERTIES:
            return ft.Row([
                ft.TextField(
                    value="" if is_empty else str(val), hint_text=hint_text,
                    tooltip=tooltip, expand=True, dense=True, text_size=12,
                    on_change=lambda e: on_change(e.control.value),
                ),
                ft.IconButton(
                    icon=ft.Icons.COLOR_LENS, tooltip="Scegli colore Flet",
                    on_click=lambda e, k=key: show_color_picker(k),
                ),
            ], spacing=2, expand=True)

        options = FLET_CONTAINER_ALIGNMENTS if key == "alignment" and node_type == "Container" else FLET_ENUM_OPTIONS.get(key)
        if options:
            option_value = str(val)
            if key == "theme_mode":
                option_value = option_value.removeprefix("ft.ThemeMode.")
            selected = option_value if option_value in options else None
            return ft.Dropdown(
                value=selected, options=[ft.dropdown.Option(option) for option in options],
                hint_text=hint_text, tooltip=tooltip,
                expand=True, dense=True, text_size=12,
                on_select=lambda e: on_change(e.control.value),
            )

        return ft.TextField(
            value="" if is_empty else str(val), hint_text=hint_text,
            tooltip=tooltip, expand=True, dense=True, text_size=12,
            on_change=lambda e: on_change(e.control.value),
        )

    def show_icon_picker(key):
        node = selected_node[0]
        if not node:
            return

        icon_names = sorted(FLET_ICON_NAMES)
        icon_categories = {name: icon_category_for_name(name) for name in icon_names}
        categories = ["Tutte", *sorted(set(icon_categories.values()))]
        category_dropdown = ft.Dropdown(
            value="Tutte",
            label="Categoria",
            options=[ft.dropdown.Option(category) for category in categories],
            width=220,
            on_select=lambda e: render_icon_results(),
        )
        search_field = ft.TextField(
            hint_text="Cerca un'icona...",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            on_change=lambda e: render_icon_results(),
        )
        results_label = ft.Text(size=12, color="#B0BEC5")
        icon_grid = ft.GridView(
            expand=True,
            max_extent=112,
            child_aspect_ratio=0.9,
            spacing=6,
            run_spacing=6,
            padding=4,
        )
        more_button = ft.TextButton(
            "Mostra altri risultati",
            on_click=lambda e: render_icon_results(load_more=True),
        )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Scegli un'icona Flet"),
            content=ft.Column(
                [
                    ft.Row([category_dropdown, search_field], spacing=8),
                    results_label,
                    icon_grid,
                    ft.Row([more_button], alignment=ft.MainAxisAlignment.CENTER),
                ],
                width=720,
                height=560,
                spacing=8,
                expand=True,
            ),
            actions=[ft.TextButton("Chiudi", on_click=lambda e: page.pop_dialog())],
        )
        result_limit = [100]

        def choose_icon(icon_name):
            page.pop_dialog()
            stage_property_value(node, key, icon_name)

        def render_icon_results(load_more=False):
            if load_more:
                result_limit[0] += 100
            category = category_dropdown.value or "Tutte"
            query = (search_field.value or "").strip().casefold()
            matches = [
                name for name in icon_names
                if (category == "Tutte" or icon_categories[name] == category)
                and (not query or query in name.replace("_", " ").casefold())
            ]
            results_label.value = f"{len(matches)} icone disponibili"
            icon_grid.controls = [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(getattr(ft.Icons, name), size=26),
                            ft.Text(name, size=9, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=4,
                        tight=True,
                    ),
                    alignment=ft.Alignment(0, 0),
                    padding=6,
                    border_radius=6,
                    bgcolor="#1E232A",
                    tooltip=name,
                    on_click=lambda e, selected=name: choose_icon(selected),
                )
                for name in matches[:result_limit[0]]
            ]
            more_button.visible = result_limit[0] < len(matches)
            page.update()

        render_icon_results()
        page.show_dialog(dialog)

    def show_add_property_popup():
        node = selected_node[0]
        if not node:
            return
        n_type = node["type"]
        used_props = node.get("props", {})
        all_possible_params = (
            WINDOW_SCHEMA if node.get("_window") else FLET_SCHEMA.get(
                n_type,
                ["text", "label", "value", "width", "height", "bgcolor", "spacing", "alignment"],
            )
        )
        if (
            n_type in {"PopupMenuItem", "MenuItemButton", "SubmenuButton"}
            and "content" not in used_props
        ):
            all_possible_params = [*all_possible_params, "content"]
        managed_collection = {
            "PopupMenuButton": "items",
            "MenuBar": "controls",
            "SubmenuButton": "controls",
            "Dropdown": "options",
        }.get(n_type)
        if managed_collection:
            all_possible_params = [
                parameter for parameter in all_possible_params
                if parameter != managed_collection
            ]
        unused_params = [param for param in all_possible_params if param not in used_props]
        dialog = ft.AlertDialog(modal=True, title=ft.Text(f"Aggiungi proprietà - {n_type}"))
        search_field = ft.TextField(
            hint_text="Cerca una proprietà...",
            prefix_icon=ft.Icons.SEARCH,
            autofocus=True,
        )
        property_results = ft.ListView(expand=True, spacing=4)

        def property_category(property_name):
            if property_name in {
                "alignment", "horizontal_alignment", "vertical_alignment",
                "width", "height", "expand", "expand_loose", "spacing",
                "run_spacing", "padding", "margin", "left", "right", "top",
                "bottom", "col",
            }:
                return "Layout"
            if property_name in {
                "color", "bgcolor", "icon_color", "shadow_color", "elevation",
                "border", "border_radius", "opacity", "shape", "style",
                "size", "text_size", "weight", "font_family", "border_side",
            }:
                return "Stile"
            if property_name in {
                "content", "text", "value", "label", "hint_text", "helper_text",
                "icon", "src", "tooltip", "title", "subtitle", "leading",
                "trailing", "items", "controls", "actions", "options",
            }:
                return "Contenuto"
            if property_name.startswith("on_") or property_name in {
                "disabled", "visible", "autofocus", "read_only",
                "enable_feedback", "close_on_click",
            }:
                return "Interazione"
            return "Altro"

        def render_property_results(query=""):
            normalized_query = query.strip().casefold()
            grouped = {}
            for property_name in unused_params:
                if normalized_query and normalized_query not in property_name.casefold():
                    continue
                grouped.setdefault(property_category(property_name), []).append(property_name)
            category_order = ("Layout", "Stile", "Contenuto", "Interazione", "Altro")
            controls = []
            for category in category_order:
                properties = grouped.get(category, [])
                if not properties:
                    continue
                controls.append(
                    ft.Text(
                        category, size=12, weight=ft.FontWeight.BOLD,
                        color="#90CAF9",
                    )
                )
                controls.extend(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(property_name, expand=True, size=12),
                            ft.IconButton(
                                icon=ft.Icons.ADD,
                                icon_size=16,
                                tooltip=f"Attiva {property_name}",
                                on_click=lambda e, p=property_name:
                                    activate_prop_from_popup(
                                        dialog,
                                        p,
                                        unused_params,
                                        render_property_results,
                                    ),
                            ),
                        ]),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                        bgcolor="#1E232A",
                        border_radius=4,
                    )
                    for property_name in properties
                )
            if not controls:
                controls.append(
                    ft.Text(
                        "Tutte le proprietà disponibili sono già utilizzate."
                        if not normalized_query
                        else "Nessuna proprietà corrisponde alla ricerca."
                    )
                )
            property_results.controls = controls
            page.update()

        search_field.on_change = lambda e: render_property_results(
            e.control.value or ""
        )
        render_property_results()
        dialog.content = ft.Column(
            [search_field, property_results],
            width=420,
            height=440,
            spacing=8,
        )
        dialog.actions = [ft.TextButton("Chiudi", on_click=lambda e: close_add_property_popup(dialog))]
        page.show_dialog(dialog)

    def close_add_property_popup(dialog):
        page.pop_dialog()

    def activate_prop_from_popup(dialog, key, available_properties, refresh_results):
        activate_prop(key)
        if key in available_properties:
            available_properties.remove(key)
        refresh_results(search_field_value(dialog))

    def search_field_value(dialog):
        content = dialog.content
        if isinstance(content, ft.Column) and content.controls:
            search_field = content.controls[0]
            if isinstance(search_field, ft.TextField):
                return search_field.value or ""
        return ""

    def menu_collection_for_type(control_type):
        if control_type == "PopupMenuButton":
            return "items"
        if control_type in {"MenuBar", "SubmenuButton"}:
            return "controls"
        return None

    def default_menu_child(parent_type):
        if parent_type == "PopupMenuButton":
            return {
                "id": f"popupmenuitem_{os.urandom(2).hex()}",
                "type": "PopupMenuItem",
                "props": {"content": "Nuova voce"},
                "children": [],
            }
        return {
            "id": f"menuitembutton_{os.urandom(2).hex()}",
            "type": "MenuItemButton",
            "props": {"content": "Nuova voce"},
            "children": [],
        }

    def update_menu_child_label(node, index, value):
        if node.get("_imported"):
            collection_name = menu_collection_for_type(node["type"])
            children = node.get("children") or []
            child = children[index] if index < len(children) else {}
            property_name = (
                "text"
                if child.get("type") == "MenuItemButton"
                and "content" not in child.get("props", {})
                else "content"
            )
            expression = f"ft.Text({value!r})" if property_name == "content" else repr(value)
            try:
                if edit_source_list_item_property(
                    node["_source_path"],
                    node["_line"],
                    node["_column"],
                    collection_name,
                    index,
                    property_name,
                    expression,
                ):
                    reload_opened_project()
            except (OSError, ValueError, IndexError, SyntaxError) as edit_error:
                page.show_dialog(
                    ft.SnackBar(
                        content=ft.Text(f"Rinomina voce menu non riuscita: {edit_error}")
                    )
                )
            return
        children = node.get("children", [])
        if index < 0 or index >= len(children):
            return
        child_props = children[index].setdefault("props", {})
        label_property = next(
            (key for key in ("content", "text", "value") if key in child_props),
            "content",
        )
        child_props[label_property] = value
        refresh_ui()
        update_inspector()

    def update_dropdown_option_label(node, index, value):
        if node.get("_imported"):
            try:
                if edit_source_list_item_property(
                    node["_source_path"],
                    node["_line"],
                    node["_column"],
                    "options",
                    index,
                    "text",
                    repr(value),
                ):
                    reload_opened_project()
            except (OSError, ValueError, IndexError, SyntaxError) as edit_error:
                page.show_dialog(
                    ft.SnackBar(
                        content=ft.Text(f"Rinomina opzione non riuscita: {edit_error}")
                    )
                )
            return
        options = node.get("props", {}).get("options", [])
        if index < 0 or index >= len(options):
            return
        options[index]["text"] = value
        refresh_ui()
        update_inspector()

    def add_menu_child(node):
        if node.get("_imported"):
            return edit_imported_list_property(
                node, menu_collection_for_type(node["type"]), "add"
            )
        node.setdefault("children", []).append(default_menu_child(node["type"]))
        refresh_ui()
        update_inspector()
        return True

    def add_dropdown_option(node):
        options = node.setdefault("props", {}).setdefault("options", [])
        options.append({
            "key": f"opzione_{len(options) + 1}",
            "text": f"Nuova opzione {len(options) + 1}",
        })
        refresh_ui()
        update_inspector()

    def remove_dropdown_option(node, index):
        options = node.get("props", {}).get("options", [])
        if len(options) <= 1 or index >= len(options):
            return
        options.pop(index)
        refresh_ui()
        update_inspector()

    def remove_menu_child(node, index):
        if node.get("_imported"):
            return edit_imported_list_property(
                node,
                menu_collection_for_type(node["type"]),
                "remove",
                index=index,
            )
        children = node.get("children", [])
        if len(children) <= 1 or index >= len(children):
            return False
        removed = children.pop(index)
        if selected_node[0] is removed:
            selected_node[0] = node
        refresh_ui()
        update_inspector()
        return True

    def source_for_selected_control(node):
        if node.get("_window"):
            return "\n".join(
                (
                    f"page.title = {_window_value_expression(key, value)}"
                    if key == "title"
                    else f"page.theme_mode = {_window_value_expression(key, value)}"
                    if key == "theme_mode"
                    else "page.window.center()"
                    if key == "center" and value
                    else f"page.window.{key} = {_window_value_expression(key, value)}"
                )
                for key, value in node.get("props", {}).items()
                    if key != "center" or value
            )
        if node.get("_imported"):
            source_path = node.get("_source_path")
            if not source_path:
                return ""
            source = Path(source_path).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=source_path)
            call = next(
                (
                    item for item in ast.walk(tree)
                    if isinstance(item, ast.Call)
                    and item.lineno == node.get("_line")
                    and item.col_offset == node.get("_column")
                ),
                None,
            )
            return ast.get_source_segment(source, call) if call is not None else ""
        return _generate_ui_code(node)

    def selected_control_comment(node):
        if not node.get("_imported"):
            return node.get("_comment", "")
        source_path = node.get("_source_path")
        if not source_path:
            return ""
        source_lines = Path(source_path).read_text(encoding="utf-8").splitlines()
        call_line = node.get("_line", 0)
        comment_lines = []
        index = call_line - 2
        while index >= 0:
            match = re.match(r"^\s*#\s?(.*)$", source_lines[index])
            if not match:
                break
            comment_lines.append(match.group(1))
            index -= 1
        if not comment_lines or index < 0 or not re.match(
            r"^\s*\(\s*$", source_lines[index]
        ):
            return ""
        return "\n".join(reversed(comment_lines))

    def set_imported_control_comment(node, comment):
        source_path = node.get("_source_path")
        if not source_path:
            raise ValueError("Percorso del controllo importato non disponibile.")
        source = Path(source_path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=source_path)
        call = next(
            (
                item for item in ast.walk(tree)
                if isinstance(item, ast.Call)
                and item.lineno == node.get("_line")
                and item.col_offset == node.get("_column")
            ),
            None,
        )
        if call is None:
            raise ValueError("Il controllo selezionato non è stato trovato nel sorgente.")

        source_lines = source.splitlines(keepends=True)

        def source_offset(line, byte_column):
            line_text = source_lines[line - 1]
            character_column = len(line_text.encode("utf-8")[:byte_column].decode("utf-8"))
            return sum(len(item) for item in source_lines[:line - 1]) + character_column

        start = source_offset(call.lineno, call.col_offset)
        end = source_offset(call.end_lineno, call.end_col_offset)
        before, call_source, after = source[:start], source[start:end], source[end:]
        indent = " " * call.col_offset

        previous_wrapper = re.search(
            rf"\(\n(?P<indent>[ \t]*)#.*\n"
            rf"(?:(?P=indent)#.*\n)*(?P=indent)$",
            before,
        )
        if previous_wrapper:
            before = before[:previous_wrapper.start()]
            closing_wrapper = re.match(
                rf"\n{re.escape(previous_wrapper.group('indent'))}\)", after
            )
            if closing_wrapper:
                after = after[closing_wrapper.end():]

        comment_lines = [
            f"{indent}{line.strip()}" if line.strip().startswith("#")
            else f"{indent}# {line}" if line
            else f"{indent}#"
            for line in comment.splitlines()
        ]
        if comment_lines:
            replacement = (
                "(\n"
                + "\n".join(comment_lines)
                + f"\n{indent}{call_source}\n{indent})"
            )
        else:
            replacement = call_source
        Path(source_path).write_text(before + replacement + after, encoding="utf-8")

    def apply_selected_control_comment(node, comment):
        if node.get("_window"):
            page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(
                        "I commenti sono disponibili per i controlli, non per la finestra."
                    )
                )
            )
            return
        try:
            if node.get("_imported"):
                set_imported_control_comment(node, comment)
                reload_opened_project()
                return
            node["_comment"] = comment.strip()
            refresh_ui()
            update_inspector()
        except (OSError, ValueError, SyntaxError) as comment_error:
            page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(f"Commento non applicato: {comment_error}")
                )
            )

    def visual_expression_value(value, property_name):
        try:
            return ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError):
            pass
        if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Attribute):
            if value.value.attr == "Icons":
                return value.attr
        if property_name == "on_click" and isinstance(value, ast.Call):
            if (
                isinstance(value.func, ast.Name)
                and value.func.id == "getattr"
                and len(value.args) > 1
                and isinstance(value.args[1], ast.Constant)
                and isinstance(value.args[1].value, str)
            ):
                return value.args[1].value
        raise ValueError(
            f"L'espressione della proprietà {property_name} non è modificabile "
            "dall'Inspector visuale."
        )

    def parse_visual_control_call(call, existing_id=None):
        if not isinstance(call, ast.Call):
            raise ValueError("Il codice deve essere una chiamata a un controllo Flet.")
        control_type = (
            call.func.attr
            if isinstance(call.func, ast.Attribute)
            else call.func.id
            if isinstance(call.func, ast.Name)
            else None
        )
        if not control_type or not hasattr(ft, control_type):
            raise ValueError("Il codice deve usare un controllo Flet disponibile.")

        node = {
            "id": existing_id or f"{control_type.lower()}_{os.urandom(2).hex()}",
            "type": control_type,
            "props": {},
            "children": [],
        }
        properties = node["props"]
        collection_property = CONTROL_COLLECTION_PROPERTIES.get(control_type)
        textual_content_types = {
            "Button", "CupertinoButton", "IconButton", "MenuItemButton",
            "PopupMenuItem", "SubmenuButton", "TextButton", "ElevatedButton", "OutlinedButton",
            "FilledButton", "FilledTonalButton",
        }

        def text_control_value(value):
            if not isinstance(value, ast.Call):
                return None
            text_type = (
                value.func.attr
                if isinstance(value.func, ast.Attribute)
                else value.func.id
                if isinstance(value.func, ast.Name)
                else None
            )
            if text_type != "Text":
                return None
            text_value = value.args[0] if value.args else next(
                (keyword.value for keyword in value.keywords if keyword.arg == "value"),
                None,
            )
            if text_value is None:
                return ""
            try:
                return ast.literal_eval(text_value)
            except (ValueError, TypeError, SyntaxError):
                return None

        control_class = getattr(ft, control_type)
        parameter_names = [
            name for name in inspect.signature(control_class.__init__).parameters
            if name not in {"self", "args", "kwargs", "controls"}
        ]
        consumed_positional = set()
        for index, argument in enumerate(call.args):
            if (
                index == 0
                and collection_property
                and isinstance(argument, (ast.List, ast.Tuple))
            ):
                node["children"] = [
                    parse_visual_control_call(item, None)
                    for item in argument.elts
                    if isinstance(item, ast.Call)
                ]
                continue
            if index >= len(parameter_names):
                raise ValueError("Il controllo contiene un argomento posizionale non supportato.")
            key = parameter_names[index]
            consumed_positional.add(key)
            if key == collection_property and isinstance(argument, (ast.List, ast.Tuple)):
                node["children"] = [
                    parse_visual_control_call(item, None)
                    for item in argument.elts
                    if isinstance(item, ast.Call)
                ]
            elif isinstance(argument, ast.Call) and key == "content":
                node["children"].append(parse_visual_control_call(argument, None))
            else:
                properties[key] = visual_expression_value(argument, key)

        for keyword in call.keywords:
            key = keyword.arg
            if key is None or key in consumed_positional:
                continue
            value = keyword.value
            if key == collection_property and isinstance(value, (ast.List, ast.Tuple)):
                node["children"] = [
                    parse_visual_control_call(item, None)
                    for item in value.elts
                    if isinstance(item, ast.Call)
                ]
            elif key == "options" and isinstance(value, (ast.List, ast.Tuple)):
                node["props"]["options"] = [
                    {
                        option.arg: visual_expression_value(option.value, option.arg)
                        for option in item.keywords
                        if option.arg in {"key", "text"}
                    }
                    for item in value.elts
                    if isinstance(item, ast.Call)
                ]
            elif key == "content" and isinstance(value, ast.Call):
                content_value = text_control_value(value)
                if control_type in textual_content_types and content_value is not None:
                    properties[key] = content_value
                elif control_type in {
                    "Container", "Card", "SafeArea", "Tabs", "Tooltip",
                }:
                    node["children"].append(parse_visual_control_call(value, None))
                else:
                    raise ValueError(
                        f"Il valore di content per {control_type} non è modificabile "
                        "dall'Inspector visuale."
                    )
            else:
                properties[key] = visual_expression_value(value, key)
        return node

    def apply_selected_control_source(node, expression):
        if node.get("_window"):
            try:
                module = ast.parse(expression)
                assignments = []
                main_function = next(
                    (
                        item for item in module.body
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == "main" and item.args.args
                    ),
                    None,
                )
                page_name = main_function.args.args[0].arg if main_function else "page"
                for statement in module.body:
                    candidates = (
                        statement.body
                        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and statement.name == "main"
                        else [statement]
                    )
                    for candidate in candidates:
                        if isinstance(candidate, ast.Assign):
                            targets = candidate.targets
                            value = candidate.value
                        elif isinstance(candidate, ast.AnnAssign):
                            targets = [candidate.target]
                            value = candidate.value
                        elif (
                            isinstance(candidate, ast.Expr)
                            and isinstance(candidate.value, ast.Call)
                        ):
                            targets = [candidate.value]
                            value = ast.Constant(value=True)
                        else:
                            continue
                        if value is None:
                            continue
                        for target in targets:
                            key = None
                            if (
                                isinstance(target, ast.Attribute)
                                and target.attr == "title"
                                and isinstance(target.value, ast.Name)
                                and target.value.id == page_name
                            ):
                                key = "title"
                            elif (
                                isinstance(target, ast.Attribute)
                                and target.attr == "theme_mode"
                                and isinstance(target.value, ast.Name)
                                and target.value.id == page_name
                            ):
                                key = "theme_mode"
                            elif (
                                isinstance(target, ast.Call)
                                and isinstance(target.func, ast.Attribute)
                                and target.func.attr == "center"
                                and isinstance(target.func.value, ast.Attribute)
                                and target.func.value.attr == "window"
                                and isinstance(target.func.value.value, ast.Name)
                                and target.func.value.value.id == page_name
                            ):
                                key = "center"
                            elif (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Attribute)
                                and target.value.attr == "window"
                                and isinstance(target.value.value, ast.Name)
                                and target.value.value.id == page_name
                            ):
                                key = target.attr
                            if key in WINDOW_SCHEMA:
                                assignments.append((key, ast.unparse(value)))
                if not assignments:
                    raise ValueError("Inserisci almeno un'assegnazione page.window o page.title.")
                if node.get("_imported"):
                    for key, value_expression in assignments:
                        set_source_window_property(
                            node["_source_path"], key, value_expression
                        )
                    reload_opened_project()
                    return
                window_props = layout_data.setdefault("window_props", {})
                for key, value_expression in assignments:
                    try:
                        parsed_value = ast.literal_eval(
                            ast.parse(value_expression, mode="eval").body
                        )
                    except (ValueError, TypeError, SyntaxError):
                        parsed_value = value_expression
                    if key == "theme_mode":
                        mode_name = str(value_expression).rsplit(".", 1)[-1].upper()
                        if mode_name not in {"LIGHT", "DARK", "SYSTEM"}:
                            raise ValueError(
                                f"Tema progetto non supportato: {value_expression}"
                            )
                        project_theme_mode[0] = getattr(ft.ThemeMode, mode_name)
                        parsed_value = mode_name
                    if key == "center" and not parsed_value:
                        window_props.pop(key, None)
                    else:
                        window_props[key] = parsed_value
                update_project_theme_button()
                refresh_ui()
                update_inspector()
                return
            except (OSError, ValueError, SyntaxError) as edit_error:
                page.show_dialog(
                    ft.SnackBar(
                        content=ft.Text(f"Modifica finestra non riuscita: {edit_error}")
                    )
                )
                return
        try:
            parsed = ast.parse(expression.strip(), mode="eval").body
            if node.get("_imported"):
                changed = replace_source_control_call(
                    node["_source_path"],
                    node["_line"],
                    node["_column"],
                    expression.strip(),
                )
                if changed:
                    reload_opened_project()
                else:
                    page.show_dialog(
                        ft.SnackBar(
                            content=ft.Text(
                                "Il controllo selezionato non è stato trovato nel sorgente."
                            )
                        )
                    )
                return
            replacement = parse_visual_control_call(parsed, node.get("id"))
            replacement["_comment"] = node.get("_comment", "")
            node.clear()
            node.update(replacement)
            refresh_ui()
            update_inspector()
        except (OSError, ValueError, SyntaxError) as edit_error:
            page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(f"Modifica codice del controllo non riuscita: {edit_error}")
                )
            )

    def render_menu_items_inspector(node):
        collection_name = menu_collection_for_type(node["type"])
        if not collection_name:
            return
        if node.get("_imported"):
            item_count = imported_collection_length(node, collection_name)
            if item_count < 1:
                edit_imported_list_property(node, collection_name, "add")
                return False
            children = node.get("children", [])
        else:
            children = node.setdefault("children", [])
            if not children:
                children.append(default_menu_child(node["type"]))
                refresh_ui()

        item_count = imported_collection_length(node, collection_name) if node.get("_imported") else len(children)
        inspector_area.controls.append(
            ft.Text(
                f"VOCI MENU ({item_count})",
                weight=ft.FontWeight.BOLD,
                size=12,
                color="#81C784",
            )
        )
        if not children:
            children = [
                {"type": "Voce", "props": {}, "id": f"menu-item-{index}"}
                for index in range(item_count)
            ]
        for index, child in enumerate(children):
            child_props = child.get("props", {})
            label = (
                child_props.get("content")
                or child_props.get("text")
                or child_props.get("value")
                or f"Voce {index + 1}"
            )
            if node.get("_imported") and isinstance(label, str):
                label = tree_text_from_source(label) or label
            label_editor = ft.TextField(
                value=str(label),
                hint_text="Nome voce",
                expand=True,
                dense=True,
                text_size=12,
                on_submit=lambda e, n=node, i=index:
                    update_menu_child_label(n, i, e.control.value or ""),
            )
            controls = [
                ft.Text(f"{index + 1}.", width=24, size=12),
                label_editor,
                ft.IconButton(
                    icon=ft.Icons.CHECK,
                    icon_size=15,
                    icon_color="#81C784",
                    tooltip="Applica nome voce",
                    on_click=lambda e, n=node, i=index, field=label_editor:
                        update_menu_child_label(n, i, field.value or ""),
                ),
                ft.IconButton(
                    icon=ft.Icons.ADD,
                    icon_size=15,
                    icon_color="#81C784",
                    tooltip="Aggiungi voce menu",
                    on_click=lambda e, n=node: add_menu_child(n),
                ),
            ]
            if item_count > 1:
                controls.append(
                    ft.IconButton(
                        icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                        icon_size=15,
                        icon_color="#EF9A9A",
                        tooltip="Rimuovi voce menu",
                        on_click=lambda e, n=node, i=index: remove_menu_child(n, i),
                    )
                )
            inspector_area.controls.append(ft.Row(controls, spacing=2))
        return True

    def update_inspector():
        inspector_area.controls.clear()
        property_editor_controls.clear()
        property_action_buttons.clear()
        node = selected_node[0]
        if not node:
            page.update()
            return
            
        n_type = node["type"]
        used_props = node.get("props", {})

        header_controls = [
            ft.Text(
                "Finestra applicazione"
                if node.get("_window")
                else f"{n_type} (#{node['id']})",
                weight=ft.FontWeight.BOLD,
                size=15,
                color="#00ACC1",
                expand=True,
            ),
            ft.IconButton(
                icon=ft.Icons.ADD,
                icon_color="#81C784",
                tooltip="Aggiungi proprietà",
                on_click=lambda e: show_add_property_popup(),
            ),
        ]
        if (
            node["id"] != "root"
            and not node.get("_imported")
            and not node.get("_window")
        ):
            header_controls.append(
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_color="#EF9A9A",
                    tooltip="Elimina elemento",
                    on_click=lambda e: delete_current_node(),
                )
            )

        inspector_area.controls.append(ft.Row(header_controls, spacing=2))
        if node.get("_imported") and not node.get("_window"):
            inspector_area.controls.append(
                ft.Text("File importato: le modifiche vengono salvate nel codice.",
                        size=11, color="#B0BEC5")
            )
        inspector_area.controls.append(ft.Text("PROPRIETÀ ATTIVE", weight=ft.FontWeight.BOLD, size=12, color="#81C784"))
        
        for key, val in list(used_props.items()):
            if node.get("_imported") and key in {"actions", "items", "options"}:
                continue
            if n_type == "Dropdown" and key == "options":
                continue
            property_key = (id(node), key)
            editor_value = pending_property_values.get(property_key, val)
            editor = property_editor(
                key,
                editor_value,
                n_type,
                used_props,
                on_change=lambda value, n=node, k=key: stage_property_value(n, k, value),
            )
            action_button = ft.IconButton(
                icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                icon_color="#EF9A9A",
                tooltip="Disattiva Proprietà",
                visible=can_remove_property(node, key),
                on_click=lambda e, n=node, k=key: handle_property_action(n, k),
            )
            property_editor_controls[property_key] = editor
            property_action_buttons[property_key] = action_button
            if property_key in pending_property_values:
                set_pending_action_button(action_button)

            property_controls = [
                ft.Text(f"{key}:", width=80, size=12, weight=ft.FontWeight.BOLD),
                editor,
            ]
            if key == "icon" and not node.get("_window"):
                property_controls.append(
                    ft.IconButton(
                        icon=ft.Icons.EMOJI_SYMBOLS,
                        tooltip="Scegli un'icona Flet",
                        on_click=lambda e, k=key: show_icon_picker(k),
                    )
                )
            property_controls.append(action_button)
            inspector_area.controls.append(
                ft.Row(property_controls, spacing=5)
            )

        imported_collection_properties = {
            "AlertDialog": ("actions",),
            "CupertinoAlertDialog": ("actions",),
            "Dropdown": ("options",),
        }
        if node.get("_imported"):
            for property_name in imported_collection_properties.get(n_type, ()):
                item_count = imported_collection_length(node, property_name)
                minimum_items = 1 if n_type == "Dropdown" and property_name == "options" else 0
                if item_count < minimum_items:
                    edit_imported_list_property(node, property_name, "add")
                    page.update()
                    return
                inspector_area.controls.append(
                    ft.Row(
                        [
                            ft.Text(
                                f"{property_name} ({item_count})",
                                size=12,
                                weight=ft.FontWeight.BOLD,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.ADD,
                                icon_color="#81C784",
                                tooltip=f"Aggiungi elemento a {property_name}",
                                on_click=lambda e, n=node, k=property_name:
                                    edit_imported_list_property(n, k, "add"),
                            ),
                        ],
                        spacing=4,
                    )
                )
                children = node.get("children", [])
                for index in range(item_count):
                    child = children[index] if index < len(children) else {}
                    child_props = child.get("props", {})
                    label = (
                        child_props.get("content")
                        or child_props.get("text")
                        or child_props.get("value")
                        or f"{property_name[:-1].capitalize()} {index + 1}"
                    )
                    if isinstance(label, str):
                        label = tree_text_from_source(label) or label
                    inline_editable = (
                        property_name == "options" and n_type == "Dropdown"
                    ) or menu_collection_for_type(n_type) == property_name
                    label_editor = ft.TextField(
                        value=str(label),
                        hint_text="Nome voce",
                        expand=True,
                        dense=True,
                        text_size=12,
                        read_only=not inline_editable,
                        on_submit=lambda e, n=node, k=property_name, i=index:
                            (
                                update_dropdown_option_label(n, i, e.control.value or "")
                                if k == "options"
                                else update_menu_child_label(n, i, e.control.value or "")
                            ),
                    )
                    row_controls = [
                        ft.Text(f"{index + 1}.", width=24, size=12),
                        label_editor,
                    ]
                    if inline_editable:
                        row_controls.append(
                            ft.IconButton(
                                icon=ft.Icons.CHECK,
                                icon_size=15,
                                icon_color="#81C784",
                                tooltip="Applica nome voce",
                                on_click=lambda e, n=node, k=property_name, i=index, field=label_editor:
                                    (
                                        update_dropdown_option_label(n, i, field.value or "")
                                        if k == "options"
                                        else update_menu_child_label(n, i, field.value or "")
                                    ),
                            )
                        )
                    row_controls.append(
                        ft.IconButton(
                            icon=ft.Icons.ADD,
                            icon_size=15,
                            icon_color="#81C784",
                            tooltip=f"Aggiungi elemento a {property_name}",
                            on_click=lambda e, n=node, k=property_name:
                                edit_imported_list_property(n, k, "add"),
                        )
                    )
                    if item_count > minimum_items:
                        row_controls.append(
                            ft.IconButton(
                                icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                                icon_size=15,
                                icon_color="#EF9A9A",
                                tooltip=f"Rimuovi elemento da {property_name}",
                                on_click=lambda e, n=node, k=property_name, i=index:
                                    edit_imported_list_property(
                                        n, k, "remove", index=i
                                    ),
                            )
                        )
                    inspector_area.controls.append(ft.Row(row_controls, spacing=2))

        if menu_collection_for_type(n_type) and not render_menu_items_inspector(node):
            page.update()
            return
        if n_type == "Dropdown" and not node.get("_imported"):
            options = node.setdefault("props", {}).setdefault("options", [])
            if not options:
                options.append({
                    "key": "nuova_opzione",
                    "text": "Nuova opzione",
                })
                refresh_ui()
            inspector_area.controls.append(
                ft.Text(
                    f"OPZIONI ({len(options)})",
                    weight=ft.FontWeight.BOLD,
                    size=12,
                    color="#81C784",
                )
            )
            for index, option in enumerate(options):
                label_editor = ft.TextField(
                    value=str(option.get("text") or option.get("key") or "Opzione"),
                    hint_text="Nome opzione",
                    expand=True,
                    dense=True,
                    text_size=12,
                    on_submit=lambda e, n=node, i=index:
                        update_dropdown_option_label(n, i, e.control.value or ""),
                )
                row_controls = [
                    ft.Text(f"{index + 1}.", width=24, size=12),
                    label_editor,
                    ft.IconButton(
                        icon=ft.Icons.CHECK,
                        icon_size=15,
                        icon_color="#81C784",
                        tooltip="Applica nome opzione",
                        on_click=lambda e, n=node, i=index, field=label_editor:
                            update_dropdown_option_label(n, i, field.value or ""),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ADD,
                        icon_size=15,
                        icon_color="#81C784",
                        tooltip="Aggiungi opzione",
                        on_click=lambda e, n=node: add_dropdown_option(n),
                    ),
                ]
                if len(options) > 1:
                    row_controls.append(
                        ft.IconButton(
                            icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                            icon_size=15,
                            icon_color="#EF9A9A",
                            tooltip="Rimuovi opzione",
                            on_click=lambda e, n=node, i=index:
                                remove_dropdown_option(n, i),
                        )
                    )
                inspector_area.controls.append(ft.Row(row_controls, spacing=2))

        existing_controls = inspector_area.controls
        header = existing_controls[0]
        property_controls = existing_controls[1:]
        source_editor = ft.TextField(
            value=source_for_selected_control(node),
            multiline=True,
            min_lines=4,
            max_lines=10,
            text_size=11,
            text_style=ft.TextStyle(font_family="Consolas", size=11),
            tooltip="Modifica il codice del controllo selezionato e applica.",
        )
        source_controls = [
            ft.Text(
                "CODICE SORGENTE DEL CONTROLLO",
                weight=ft.FontWeight.BOLD,
                size=12,
                color="#90CAF9",
            ),
            source_editor,
            ft.FilledButton(
                "Applica codice al controllo",
                icon=ft.Icons.CHECK,
                on_click=lambda e, n=node, editor=source_editor:
                    apply_selected_control_source(n, editor.value or ""),
            ),
        ]
        comment_editor = ft.TextField(
            value=selected_control_comment(node),
            label="Commento Python",
            hint_text="Inserisci un commento da posizionare prima del controllo",
            multiline=True,
            min_lines=4,
            max_lines=8,
            text_size=11,
            text_style=ft.TextStyle(font_family="Consolas", size=11),
            tooltip="Il commento verrà inserito immediatamente prima del controllo selezionato.",
        )
        comment_controls = [
            ft.Text(
                "COMMENTO PRIMA DEL CONTROLLO",
                weight=ft.FontWeight.BOLD,
                size=12,
                color="#CE93D8",
            ),
            comment_editor,
            ft.FilledButton(
                "Applica commento",
                icon=ft.Icons.COMMENT,
                on_click=lambda e, n=node, editor=comment_editor:
                    apply_selected_control_comment(n, editor.value or ""),
            ),
        ]
        inspector_area.controls = [
            header,
            ft.Tabs(
                content=ft.Column(
                    [
                        ft.TabBar(
                            tabs=[
                                ft.Tab(
                                    icon=ft.Icons.SETTINGS,
                                    tooltip="Proprietà attive",
                                ),
                                ft.Tab(
                                    icon=ft.Icons.CODE,
                                    tooltip="Codice sorgente",
                                ),
                                ft.Tab(
                                    icon=ft.Icons.COMMENT,
                                    tooltip="Commenti",
                                ),
                            ],
                        ),
                        ft.TabBarView(
                            controls=[
                                ft.Container(
                                    content=ft.Column(
                                        property_controls,
                                        tight=True,
                                        scroll=ft.ScrollMode.AUTO,
                                    ),
                                    padding=4,
                                ),
                                ft.Container(
                                    content=ft.Column(
                                        source_controls,
                                        tight=True,
                                        scroll=ft.ScrollMode.AUTO,
                                    ),
                                    padding=4,
                                ),
                                ft.Container(
                                    content=ft.Column(
                                        comment_controls,
                                        tight=True,
                                        scroll=ft.ScrollMode.AUTO,
                                    ),
                                    padding=4,
                                ),
                            ],
                            expand=True,
                        ),
                    ],
                    tight=True,
                ),
                length=3,
                selected_index=0,
                height=420,
            ),
        ]
        page.update()

    def set_property_editor_value(editor, value):
        if isinstance(editor, ft.Row):
            editor = next(
                (control for control in editor.controls if isinstance(control, (ft.TextField, ft.Dropdown))),
                None,
            )
        if isinstance(editor, (ft.TextField, ft.Dropdown)):
            editor.value = str(value)

    def set_pending_action_button(button):
        button.icon = ft.Icons.ADD
        button.icon_color = "#4CAF50"
        button.tooltip = "Applica modifica"
        button.visible = True

    def stage_property_value(node, key, value):
        if not node:
            return
        property_key = (id(node), key)
        pending_property_values[property_key] = value
        editor = property_editor_controls.get(property_key)
        if editor is not None:
            set_property_editor_value(editor, value)
        button = property_action_buttons.get(property_key)
        if button is not None:
            set_pending_action_button(button)
        page.update()

    def has_property_value(value):
        return value is not None and (not isinstance(value, str) or bool(value.strip()))

    def is_required_property(node, key):
        control_type = node.get("type", "")
        props = node.get("props", {})
        if control_type in {"PopupMenuItem", "MenuItemButton", "SubmenuButton"} and key == "content":
            return True
        has_button_content = has_property_value(props.get("content")) or has_property_value(
            props.get("text")
        )
        has_button_icon = has_property_value(props.get("icon"))

        if control_type in BUTTON_TYPES or control_type in {"CupertinoButton", "IconButton"}:
            if key in {"content", "text"}:
                return not has_button_icon
            if key == "icon":
                return not has_button_content

        control_class = getattr(ft, node.get("type", ""), None)
        if control_class is not None:
            try:
                parameters = inspect.signature(control_class.__init__).parameters
            except (TypeError, ValueError):
                parameters = {}
            if key in parameters and parameters[key].default is inspect.Parameter.empty:
                return True

        return False

    def can_remove_property(node, key):
        return not is_required_property(node, key)

    def handle_property_action(node, key):
        property_key = (id(node), key)
        if property_key in pending_property_values:
            apply_property_value(node, key)
        else:
            remove_prop(key)

    def apply_property_value(node, key):
        property_key = (id(node), key)
        if property_key not in pending_property_values:
            return

        value = pending_property_values[property_key]
        if node.get("_window") and isinstance(value, str) and key != "title":
            try:
                value = ast.literal_eval(value)
            except (ValueError, TypeError, SyntaxError):
                pass
        if node.get("_window"):
            try:
                _window_value_expression(key, value)
            except SyntaxError as edit_error:
                page.show_dialog(
                    ft.SnackBar(
                        content=ft.Text(
                            f"Valore finestra non valido per {key}: {edit_error}"
                        )
                    )
                )
                return
            except ValueError as edit_error:
                page.show_dialog(
                    ft.SnackBar(
                        content=ft.Text(
                            f"Valore finestra non valido per {key}: {edit_error}"
                        )
                    )
                )
                return
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        if isinstance(value, str) and not value.strip() and is_required_property(node, key):
            page.show_dialog(ft.SnackBar(content=ft.Text(f"La proprietà {key} non può essere vuota.")))
            return

        if node.get("_imported"):
            pending_property_values.pop(property_key, None)
            edit_imported_property(node, key, value)
            return

        if node.get("_window") and key == "theme_mode":
            mode = str(value).removeprefix("ft.ThemeMode.").upper()
            project_theme_mode[0] = getattr(ft.ThemeMode, mode)
            value = mode
            update_project_theme_button()
        node.setdefault("props", {})[key] = value
        pending_property_values.pop(property_key, None)
        refresh_ui()
        update_inspector()

    def remove_prop(key):
        if selected_node[0] and key in selected_node[0]["props"]:
            node = selected_node[0]
            if not can_remove_property(node, key):
                return
            pending_property_values.pop((id(node), key), None)
            if selected_node[0].get("_imported"):
                node = selected_node[0]
                if node.get("_window"):
                    edit_imported_property(node, key, None)
                    return
                line = node["_call"].lineno if node.get("_call") is not None else node["_line"]
                column = node["_call"].col_offset if node.get("_call") is not None else node["_column"]
                if edit_source_property(node["_source_path"], line, column, key, remove=True):
                    reload_opened_project()
                return
            if node.get("_window") and key == "theme_mode":
                project_theme_mode[0] = ft.ThemeMode.SYSTEM
                update_project_theme_button()
            del selected_node[0]["props"][key]
            update_inspector()
            refresh_ui()

    def activate_prop(key):
        if selected_node[0]:
            if selected_node[0].get("_window"):
                if key == "center":
                    selected_node[0]["props"][key] = True
                elif key == "title":
                    selected_node[0]["props"][key] = "Titolo applicazione"
                elif key == "theme_mode":
                    selected_node[0]["props"][key] = "SYSTEM"
                    project_theme_mode[0] = ft.ThemeMode.SYSTEM
                    update_project_theme_button()
                else:
                    selected_node[0]["props"][key] = property_example(
                        "Window", key
                    )
            elif key == "alignment" and selected_node[0]["type"] == "Container":
                selected_node[0]["props"][key] = "center"
            elif key == "icon":
                selected_node[0]["props"][key] = "ADD"
            elif key in FLET_ENUM_OPTIONS:
                selected_node[0]["props"][key] = FLET_ENUM_OPTIONS[key][0]
            elif key in COLOR_PROPERTIES:
                selected_node[0]["props"][key] = "#FFFFFF"
            else:
                selected_node[0]["props"][key] = property_example(
                    selected_node[0]["type"], key
                )
            if selected_node[0].get("_imported"):
                edit_imported_property(selected_node[0], key, selected_node[0]["props"][key])
                return
            update_inspector()
            refresh_ui()

    def select_element(node):
        selected_node[0] = node
        selected_imported_control[0] = None
        update_inspector()
        refresh_ui()
        focus_generated_code(node)

    def select_window_node():
        selected_node[0] = create_window_node()
        selected_imported_control[0] = None
        update_inspector()
        update_interface_tree()
        page.update()

    def select_imported_control(control):
        selected_imported_control[0] = control
        selected_node[0] = imported_control_nodes.get(id(control))
        update_inspector()
        update_interface_tree()
        if selected_node[0]:
            focus_imported_code(selected_node[0])
            set_preview_content(build_generated_preview())
        page.update()

    def parse_imported_component_properties(component):
        props = {}
        for key, value in component.properties.items():
            try:
                props[key] = ast.literal_eval(value)
            except (ValueError, TypeError, SyntaxError):
                props[key] = value
        return props

    def select_imported_virtual(component):
        props = parse_imported_component_properties(component)
        selected_node[0] = {
            "id": component.id,
            "type": component.type_name,
            "props": props,
            "_imported": True,
            "_call": None,
            "_line": component.line,
            "_column": component.column,
            "_end_line": component.end_line,
            "_end_column": component.end_column,
            "_source": imported_analysis[0].source,
            "_source_path": imported_analysis[0].path,
        }
        selected_imported_control[0] = None
        update_inspector()
        focus_imported_code(selected_node[0])
        update_interface_tree()
        set_preview_content(build_generated_preview())
        page.update()

    def select_imported_preview_control(control_type, type_index):
        analysis = imported_analysis[0]
        if analysis is None:
            return
        matching = [
            component for component in flatten_components(analysis.components)
            if component.type_name == control_type
        ]
        if 0 <= type_index < len(matching):
            select_imported_virtual(matching[type_index])

    def show_imported_control_picker(component):
        select_imported_virtual(component)
        show_control_picker(selected_node[0])

    def find_node(node, node_id):
        if node["id"] == node_id:
            return node
        for child in node.get("children", []) or []:
            found = find_node(child, node_id)
            if found:
                return found
        return None

    def find_parent(node, node_id):
        for child in node.get("children", []) or []:
            if child["id"] == node_id:
                return node
            parent = find_parent(child, node_id)
            if parent:
                return parent
        return None

    def contains_node(node, node_id):
        return find_node(node, node_id) is not None

    def can_contain_children(node):
        return bool(node) and node.get("type") in CONTAINER_TYPES

    def can_accept_child(target_node, source_node):
        if not can_contain_children(target_node):
            return False
        if target_node.get("type") == "PopupMenuButton":
            return source_node.get("type") == "PopupMenuItem"
        return True

    def move_node_before(source_id, target_id):
        if not source_id or source_id == target_id or source_id == "root":
            return
        source_node = find_node(layout_data, source_id)
        target_node = find_node(layout_data, target_id)
        source_parent = find_parent(layout_data, source_id)
        if not source_node or not target_node or not source_parent:
            return
        if contains_node(source_node, target_id):
            return

        source_parent["children"].remove(source_node)
        if can_accept_child(target_node, source_node):
            target_node.setdefault("children", []).append(source_node)
            refresh_ui()
            return

        target_parent = find_parent(layout_data, target_id)
        if not target_parent:
            source_parent["children"].append(source_node)
            return
        target_children = target_parent.setdefault("children", [])
        target_index = target_children.index(target_node)
        target_children.insert(target_index, source_node)
        refresh_ui()

    def toggle_preview_selection():
        preview_select_enabled[0] = not preview_select_enabled[0]
        preview_mode_button.icon_color = "#00ACC1" if preview_select_enabled[0] else None
        preview_mode_button.tooltip = (
            "Selezione elementi attiva"
            if preview_select_enabled[0]
            else "Seleziona elementi"
        )
        refresh_ui()

    def update_project_theme_button():
        current_mode = project_theme_mode[0]
        next_mode, icon, label = {
            ft.ThemeMode.LIGHT: (
                ft.ThemeMode.DARK, ft.Icons.DARK_MODE, "chiaro"
            ),
            ft.ThemeMode.DARK: (
                ft.ThemeMode.SYSTEM, ft.Icons.BRIGHTNESS_AUTO, "scuro"
            ),
            ft.ThemeMode.SYSTEM: (
                ft.ThemeMode.LIGHT, ft.Icons.LIGHT_MODE, "system"
            ),
        }[current_mode]
        project_theme_button.icon = icon
        project_theme_button.tooltip = (
            f"Tema progetto: {label}. Prossimo: {next_mode.name.lower()}."
        )

    def toggle_project_theme():
        next_mode = {
            ft.ThemeMode.LIGHT: ft.ThemeMode.DARK,
            ft.ThemeMode.DARK: ft.ThemeMode.SYSTEM,
            ft.ThemeMode.SYSTEM: ft.ThemeMode.LIGHT,
        }[project_theme_mode[0]]
        if single_file_mode[0] or project_code_authoritative[0]:
            try:
                set_source_theme_mode(project_file_path("ui"), next_mode.name)
            except (OSError, ValueError, SyntaxError) as theme_error:
                page.show_dialog(
                    ft.SnackBar(
                        content=ft.Text(f"Impossibile aggiornare il tema del progetto: {theme_error}")
                    )
                )
                return
            project_theme_mode[0] = next_mode
            update_project_theme_button()
            reload_opened_project()
            return

        project_theme_mode[0] = next_mode
        layout_data.setdefault("window_props", {})["theme_mode"] = next_mode.name
        update_project_theme_button()
        refresh_ui()

    def refresh_static_analysis():
        source_path = project_file_path("ui")
        if not source_path or not os.path.exists(source_path):
            imported_analysis[0] = None
            return
        try:
            imported_analysis[0] = analyze_module(source_path)
        except (OSError, SyntaxError) as analysis_error:
            imported_analysis[0] = None
            imported_preview_error[0] = f"Analisi statica: {analysis_error}"

    def focus_imported_code(node):
        call = node.get("_call")
        source_text = node.get("_source", "")
        if not source_text:
            return
        update_code_highlighting()
        page.update()

    def focus_generated_code(node):
        if not node or node.get("_imported"):
            return
        update_code_highlighting()
        page.update()

    def edit_imported_property(node, key, value):
        source_path = node.get("_source_path")
        if node.get("_window"):
            expression = None
            if value is not None:
                try:
                    expression = _window_value_expression(key, value)
                except SyntaxError as edit_error:
                    page.show_dialog(
                        ft.SnackBar(
                            content=ft.Text(
                                f"Valore finestra non valido per {key}: {edit_error}"
                            )
                        )
                    )
                    return
            try:
                if set_source_window_property(source_path, key, expression):
                    reload_opened_project()
            except (OSError, ValueError, SyntaxError) as edit_error:
                page.show_dialog(
                    ft.SnackBar(
                        content=ft.Text(f"Modifica finestra non riuscita: {edit_error}")
                    )
                )
            return
        call = node.get("_call")
        if not source_path:
            return
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        expression = False
        if key == "icon" and isinstance(value, str):
            icon_name = value.removeprefix("ft.Icons.").removeprefix("Icons.")
            if icon_name in FLET_ICON_NAMES:
                value = f"ft.Icons.{icon_name}"
                expression = True
        elif isinstance(value, str) and key in {"title", "content"}:
            try:
                expression = isinstance(ast.parse(value, mode="eval").body, ast.Call)
            except SyntaxError:
                expression = False
        line = call.lineno if call is not None else node["_line"]
        column = call.col_offset if call is not None else node["_column"]
        if edit_source_property(source_path, line, column, key, value, expression=expression):
            reload_opened_project()

    def imported_collection_length(node, property_name):
        analysis = imported_analysis[0]
        if analysis is None:
            return 0
        target_call = next(
            (
                item for item in ast.walk(analysis.tree)
                if isinstance(item, ast.Call)
                and item.lineno == node.get("_line")
                and item.col_offset == node.get("_column")
            ),
            None,
        )
        if target_call is None:
            return 0
        value = next(
            (
                keyword.value for keyword in target_call.keywords
                if keyword.arg == property_name
            ),
            None,
        )
        if isinstance(value, ast.Name):
            assignments = [
                item.value for item in ast.walk(analysis.tree)
                if isinstance(item, (ast.Assign, ast.AnnAssign))
                and item.value is not None
                and any(
                    isinstance(target, ast.Name) and target.id == value.id
                    for target in (
                        item.targets if isinstance(item, ast.Assign)
                        else [item.target]
                    )
                )
            ]
            value = assignments[-1] if assignments else None
        return len(value.elts) if isinstance(value, (ast.List, ast.Tuple)) else 0

    def edit_imported_list_property(node, property_name, action, value=None, index=None):
        source_path = node.get("_source_path")
        if not source_path:
            return False
        expressions = {
            "actions": 'ft.TextButton("Nuova azione")',
            "items": 'ft.PopupMenuItem(content=ft.Text("Nuova voce"))',
            "controls": (
                'ft.MenuItemButton(content=ft.Text("Nuova voce"))'
                if node.get("type") in {"MenuBar", "SubmenuButton"}
                else 'ft.Text("Nuovo controllo")'
            ),
            "options": (
                'ft.DropdownOption(key="nuova_opzione", text="Nuova opzione")'
                if hasattr(ft, "DropdownOption")
                else 'ft.dropdown.Option(key="nuova_opzione", text="Nuova opzione")'
            ),
        }
        expression = True
        value = expressions.get(property_name) if value is None else value
        try:
            changed = edit_source_list_property(
                source_path,
                node["_line"],
                node["_column"],
                property_name,
                action,
                value,
                index=index,
                expression=expression,
                minimum_items=(
                    1 if (
                        menu_collection_for_type(node.get("type")) == property_name
                        or node.get("type") == "Dropdown"
                        and property_name == "options"
                    )
                    else 0
                ),
            )
        except (OSError, ValueError, IndexError, SyntaxError) as edit_error:
            page.show_dialog(
                ft.SnackBar(content=ft.Text(f"Modifica elenco non riuscita: {edit_error}"))
            )
            return False
        if changed:
            reload_opened_project()
            return True
        else:
            page.show_dialog(
                ft.SnackBar(content=ft.Text(f"La proprietà {property_name} non è modificabile."))
            )
            return False

    def tree_text_from_source(value):
        if not isinstance(value, str):
            return None
        try:
            literal_value = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError):
            try:
                expression = ast.parse(value, mode="eval").body
            except SyntaxError:
                return value.strip() or None
            if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
                return expression.value.strip() or None
            if isinstance(expression, ast.Call):
                control_name = (
                    expression.func.attr
                    if isinstance(expression.func, ast.Attribute)
                    else expression.func.id
                    if isinstance(expression.func, ast.Name)
                    else ""
                )
                if control_name in {"Text", "TextButton", "ElevatedButton", "FilledButton", "OutlinedButton"}:
                    for argument in expression.args:
                        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                            return argument.value.strip() or None
                    for keyword in expression.keywords:
                        if keyword.arg in {"value", "content", "text"} and isinstance(keyword.value, ast.Constant):
                            if isinstance(keyword.value.value, str):
                                return keyword.value.value.strip() or None
            return None
        if isinstance(literal_value, str):
            return literal_value.strip() or None
        if isinstance(literal_value, (int, float)) and not isinstance(literal_value, bool):
            return str(literal_value)
        return None

    def tree_node_label(control_type, node_id, properties, *, source_properties=False):
        for key in ("text", "content", "label", "value"):
            value = properties.get(key)
            if source_properties:
                description = tree_text_from_source(value)
            elif isinstance(value, str):
                description = value.strip() or None
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                description = str(value)
            else:
                description = None
            if description:
                return f"{control_type} #{description}"
        return f"{control_type} #{node_id}"

    def imported_tree_label(component):
        properties = component.properties
        label = tree_node_label(
            component.type_name,
            component.variable_name or component.id,
            properties,
            source_properties=True,
        )
        if label != f"{component.type_name} #{component.variable_name or component.id}":
            return label
        analysis = imported_analysis[0]
        if analysis is not None:
            call = next(
                (
                    item for item in ast.walk(analysis.tree)
                    if isinstance(item, ast.Call)
                    and item.lineno == component.line
                    and item.col_offset == component.column
                ),
                None,
            )
            if call is not None:
                for argument in call.args:
                    description = tree_text_from_source(
                        ast.get_source_segment(analysis.source, argument) or ""
                    )
                    if description:
                        return f"{component.type_name} #{description}"
                for keyword in call.keywords:
                    if keyword.arg in {"text", "content", "label", "value"}:
                        description = tree_text_from_source(
                            ast.get_source_segment(analysis.source, keyword.value) or ""
                        )
                        if description:
                            return f"{component.type_name} #{description}"
        return label

    def default_control_expression(control_name):
        if control_name in BUTTON_TYPES or control_name == "CupertinoButton":
            return f'ft.{control_name}(content="Nuovo {control_name}")'
        if control_name == "PopupMenuItem":
            return 'ft.PopupMenuItem(content=ft.Text("Nuova voce"))'
        if control_name == "MenuItemButton":
            return 'ft.MenuItemButton(content=ft.Text("Nuova voce"))'
        if control_name == "MenuBar":
            return (
                'ft.MenuBar(controls=['
                'ft.MenuItemButton(content=ft.Text("Nuova voce"))])'
            )
        if control_name == "SubmenuButton":
            return (
                'ft.SubmenuButton(content=ft.Text("Nuovo menu"), controls=['
                'ft.MenuItemButton(content=ft.Text("Nuova voce"))])'
            )
        if control_name == "Dropdown":
            return (
                'ft.Dropdown(options=['
                'ft.DropdownOption(key="nuova_opzione", text="Nuova opzione")])'
            )
        if control_name == "IconButton":
            return "ft.IconButton(icon=ft.Icons.ADD)"
        if control_name == "Text":
            return 'ft.Text("Nuovo Text")'
        if control_name == "TextField":
            return 'ft.TextField(label="Nuovo Campo")'
        if control_name in {"Column", "Row"}:
            return f"ft.{control_name}(controls=[], spacing=10, expand=True)"
        if control_name == "PopupMenuButton":
            return (
                'ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, items=['
                'ft.PopupMenuItem(content=ft.Text("Nuova voce"))])'
            )
        if control_name == "Image":
            return 'ft.Image(src="")'
        control_class = getattr(ft, control_name, None)
        if control_class is not None:
            try:
                required = [
                    parameter for parameter in inspect.signature(
                        control_class.__init__
                    ).parameters.values()
                    if parameter.name != "self"
                    and parameter.default is inspect.Parameter.empty
                    and parameter.name not in {"args", "kwargs"}
                ]
            except (TypeError, ValueError):
                required = []
            defaults = {
                "value": f'"Nuovo {control_name}"',
                "content": f'"Nuovo {control_name}"',
                "label": f'"Nuovo {control_name}"',
                "icon": "ft.Icons.ADD",
                "src": '""',
            }
            required_values = [
                f"{parameter.name}={defaults[parameter.name]}"
                for parameter in required
                if parameter.name in defaults
            ]
            if required_values:
                return f"ft.{control_name}({', '.join(required_values)})"
        return f"ft.{control_name}()"

    def add_imported_child(parent_node, control_name):
        source_path = parent_node.get("_source_path")
        if not source_path:
            return
        expression = default_control_expression(control_name)
        parent_type = parent_node.get("type")
        collection_property = CONTROL_COLLECTION_PROPERTIES.get(parent_type)
        if parent_type in {"AlertDialog", "CupertinoAlertDialog"}:
            collection_property = "actions"
        if collection_property:
            edit_imported_list_property(
                parent_node, collection_property, "add", value=expression
            )
            return
        if parent_type in {"Container", "Card", "SafeArea", "Tabs"}:
            try:
                changed = add_source_content_child(
                    source_path,
                    parent_node["_line"],
                    parent_node["_column"],
                    expression,
                )
            except (OSError, ValueError, SyntaxError) as edit_error:
                page.show_dialog(
                    ft.SnackBar(content=ft.Text(f"Aggiunta controllo non riuscita: {edit_error}"))
                )
                return
            if changed:
                reload_opened_project()
            return
        page.show_dialog(
            ft.SnackBar(content=ft.Text("Questo controllo non supporta figli modificabili nel file importato."))
        )

    def update_interface_tree():
        interface_tree_area.controls.clear()
        maximum_tree_width = 320
        if not file_open[0]:
            interface_tree_area.controls.append(
                ft.Text("Nessun file aperto", color="#9E9E9E", size=12)
            )
            return

        if single_file_mode[0] and imported_analysis[0] is not None:
            is_dark = page.theme_mode == ft.ThemeMode.DARK
            tree_text_color = "#E0E0E0" if is_dark else "#212121"
            if imported_preview_error[0]:
                interface_tree_area.controls.append(
                    ft.Text(f"Errore file importato: {imported_preview_error[0]}", color="#EF9A9A", size=12)
                )
                return

            analysis = imported_analysis[0]
            if analysis is not None:
                window_selected = bool(
                    selected_node[0] and selected_node[0].get("_window")
                )
                window_label = "Finestra applicazione"
                maximum_tree_width = max(maximum_tree_width, len(window_label) * 8 + 120)
                interface_tree_area.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(
                                ft.Icons.ACCOUNT_TREE,
                                size=14,
                                color="#90CAF9",
                            ),
                            ft.Text(
                                window_label,
                                size=12,
                                color=(
                                    "#FFFFFF" if window_selected and is_dark
                                    else "#0D47A1" if window_selected
                                    else tree_text_color
                                ),
                            ),
                        ], spacing=4),
                        bgcolor=(
                            ("#1A3A4A" if is_dark else "#BBDEFB")
                            if window_selected else None
                        ),
                        border_radius=4,
                        padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                        on_click=lambda e: select_window_node(),
                    )
                )

                def append_virtual(component, level=0):
                    nonlocal maximum_tree_width
                    is_selected = selected_node[0] and selected_node[0].get("id") == component.id
                    label = imported_tree_label(component)
                    maximum_tree_width = max(
                        maximum_tree_width, len(label) * 8 + level * 16 + 100
                    )
                    row = ft.Container(
                        content=ft.Row([
                            ft.Container(width=level * 16),
                            ft.Icon(ft.Icons.ACCOUNT_TREE, size=14, color="#90CAF9"),
                            ft.Text(label, size=12, color=tree_text_color),
                        ], spacing=4),
                        bgcolor=("#1A3A4A" if is_dark else "#BBDEFB") if is_selected else None,
                        border_radius=4,
                        padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                        on_click=lambda e, c=component: select_imported_virtual(c),
                    )
                    row_controls = [row]
                    if is_selected and (
                        can_contain_children({"type": component.type_name})
                        or component.type_name in {
                            "AlertDialog", "CupertinoAlertDialog"
                        }
                    ):
                        row_controls.append(
                            ft.IconButton(
                                icon=ft.Icons.ADD,
                                icon_size=16,
                                icon_color="#81C784",
                                tooltip=f"Aggiungi figlio a {component.type_name}",
                                on_click=lambda e, c=component:
                                    show_imported_control_picker(c),
                            )
                        )
                    if is_selected:
                        row_controls.append(
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_size=14,
                                icon_color="#EF9A9A",
                                tooltip="Rimuovi elemento e codice",
                                on_click=lambda e, n=selected_node[0]: remove_interface_node(n),
                            )
                        )
                    interface_tree_area.controls.append(ft.Row(row_controls, spacing=0))
                    for child in component.children:
                        append_virtual(child, level + 1)

                for component in analysis.components:
                    append_virtual(component)
                if not analysis.components:
                    interface_tree_area.controls.append(
                        ft.Text("Nessun costruttore Flet individuato staticamente", size=12, color="#B0BEC5")
                    )
                interface_tree_area.width = maximum_tree_width
                return

        def append_node(node, level=0):
            nonlocal maximum_tree_width
            is_selected = selected_node[0] and selected_node[0]["id"] == node["id"]
            is_dark = page.theme_mode == ft.ThemeMode.DARK
            selected_tree_background = "#1A3A4A" if is_dark else "#BBDEFB"
            selected_tree_text = "#FFFFFF" if is_dark else "#0D47A1"
            tree_text_color = selected_tree_text if is_selected else ("#E0E0E0" if is_dark else "#212121")
            label = tree_node_label(node["type"], node["id"], node.get("props", {}))
            maximum_tree_width = max(
                maximum_tree_width, len(label) * 8 + level * 16 + 120
            )
            tree_row = ft.Container(
                content=ft.Row([
                    ft.Container(width=level * 16),
                    ft.Icon(ft.Icons.ACCOUNT_TREE, size=14, color="#90CAF9"),
                    ft.Text(label, size=12, color=tree_text_color),
                ], spacing=4),
                bgcolor=selected_tree_background if is_selected else None,
                border_radius=4,
                padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                on_click=lambda e, n=node: select_element(n),
            )
            tree_controls = [
                ft.DragTarget(
                    expand=True,
                    group="tree-elements",
                    content=ft.Draggable(
                        content=tree_row,
                        group="tree-elements",
                        data=node["id"],
                    ),
                    on_accept=lambda e, target_id=node["id"]: move_node_before(
                        getattr(e.src, "data", None), target_id
                    ),
                )
            ]
            if is_selected and can_contain_children(node):
                tree_controls.append(
                    ft.IconButton(
                        icon=ft.Icons.ADD,
                        icon_size=16,
                        icon_color="#81C784",
                        tooltip=f"Aggiungi figlio a {node['type']}",
                        on_click=lambda e, n=node: show_control_picker(n),
                    )
                )
            if is_selected and node["id"] != "root":
                tree_controls.append(
                    ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        icon_size=14,
                        icon_color="#EF9A9A",
                        tooltip="Rimuovi elemento e codice",
                        on_click=lambda e, n=node: remove_interface_node(n),
                    )
                )
            interface_tree_area.controls.append(ft.Row(tree_controls, spacing=0))
            for child in node.get("children", []) or []:
                append_node(child, level + 1)

        window_selected = bool(
            selected_node[0] and selected_node[0].get("_window")
        )
        interface_tree_area.controls.append(
            ft.Container(
                content=ft.Row([
                    ft.Icon(
                        ft.Icons.ACCOUNT_TREE,
                        size=14,
                        color="#90CAF9",
                    ),
                    ft.Text(
                        "Finestra applicazione",
                        size=12,
                        color=(
                            "#FFFFFF" if window_selected and page.theme_mode == ft.ThemeMode.DARK
                            else "#0D47A1" if window_selected
                            else ("#E0E0E0" if page.theme_mode == ft.ThemeMode.DARK else "#212121")
                        ),
                    ),
                ], spacing=4),
                bgcolor=(
                    ("#1A3A4A" if page.theme_mode == ft.ThemeMode.DARK else "#BBDEFB")
                    if window_selected else None
                ),
                border_radius=4,
                padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                on_click=lambda e: select_window_node(),
            )
        )
        append_node(layout_data)
        interface_tree_area.width = maximum_tree_width

    def build_generated_preview():
        ui_path = project_file_path("ui")
        preview_background = (
            "#121212" if project_theme_mode[0] == ft.ThemeMode.DARK
            else "#FFFFFF" if project_theme_mode[0] == ft.ThemeMode.LIGHT
            else None
        )

        try:
            if (
                preview_select_enabled[0]
                and not single_file_mode[0]
                and not project_code_authoritative[0]
            ):
                preview_surface.theme_mode = project_theme_mode[0]
                preview_surface.bgcolor = preview_background
                return render_node(layout_data)
            imported_preview_error[0] = None
            harness = PreviewHarness(ui_path)
            imported_harness[0] = harness
            descriptor = harness.render()
            descriptor_theme = descriptor.get("theme_mode", "system")
            project_theme_mode[0] = {
                "dark": ft.ThemeMode.DARK,
                "light": ft.ThemeMode.LIGHT,
                "system": ft.ThemeMode.SYSTEM,
            }.get(descriptor_theme, ft.ThemeMode.SYSTEM)
            preview_surface.theme_mode = project_theme_mode[0]
            preview_surface.bgcolor = (
                "#121212" if project_theme_mode[0] == ft.ThemeMode.DARK
                else "#FFFFFF" if project_theme_mode[0] == ft.ThemeMode.LIGHT
                else None
            )
            update_project_theme_button()
            imported_preview_descriptor[0] = descriptor
            states = descriptor.get("states", [])
            preview_state_selector.options = [
                ft.dropdown.Option(key="", text="Layout Principale"),
                *[
                    ft.dropdown.Option(key=state["id"], text=state["label"])
                    for state in states
                ],
            ]
            preview_state_toolbar.visible = bool(states)
            if not any(
                state.get("id") == imported_preview_state_id[0] for state in states
            ):
                imported_preview_state_id[0] = None
            preview_state_selector.value = imported_preview_state_id[0] or ""
            highlight_index = None
            highlight_type = None
            highlight_type_index = None
            if imported_analysis[0] is not None and selected_node[0].get("_imported"):
                virtual_components = flatten_components(imported_analysis[0].components)
                selected = selected_node[0]
                for index, component in enumerate(virtual_components):
                    if component.id == selected.get("id"):
                        highlight_type = component.type_name
                        highlight_type_index = sum(
                            1 for previous in virtual_components[:index]
                            if previous.type_name == component.type_name
                        )
                        break
                if highlight_type is None:
                    highlight_type = selected.get("type")
            return harness.build_preview(
                highlight_index=highlight_index,
                highlight_type=highlight_type,
                highlight_type_index=highlight_type_index,
                on_control_click=(
                    select_imported_preview_control
                    if preview_select_enabled[0] and single_file_mode[0]
                    else None
                ),
                state_id=imported_preview_state_id[0],
                descriptor=descriptor,
            )
        except Exception as ex:
            print(f"Errore anteprima generata: {ex}")
            imported_preview_error[0] = str(ex)
            imported_preview_descriptor[0] = None
            preview_state_toolbar.visible = False
            return ft.Container(
                expand=True,
                bgcolor=preview_background,
                content=ft.Column([
                    ft.Text("Impossibile costruire l'anteprima", color="#EF9A9A"),
                    ft.Text(str(ex), selectable=True, size=12),
                ], scroll=ft.ScrollMode.AUTO),
            )

    def render_preview_state(state_id):
        imported_preview_state_id[0] = state_id or None
        harness = imported_harness[0]
        descriptor = imported_preview_descriptor[0]
        if harness is not None and descriptor is not None:
            set_preview_content(
                harness.build_preview(
                    state_id=imported_preview_state_id[0],
                    descriptor=descriptor,
                    on_control_click=(
                        select_imported_preview_control
                        if preview_select_enabled[0] and single_file_mode[0]
                        else None
                    ),
                )
            )
        page.update()

    def set_preview_content(content):
        preview_surface.content = ft.ListView(
            controls=[content],
            expand=True,
            auto_scroll=False,
            spacing=10,
            padding=10,
        )

    def refresh_ui():
        if not file_open[0]:
            update_interface_tree()
            page.update()
            return
        if single_file_mode[0]:
            set_preview_content(build_generated_preview())
            refresh_static_analysis()
            update_interface_tree()
            page.update()
            return
        project_code_authoritative[0] = False
        auto_save_project()
        set_preview_content(build_generated_preview())
        refresh_static_analysis()
        update_interface_tree()
        page.update()

    def control_category(control_name):
        name = control_name.lower()
        if control_name in {
            "Column", "Row", "Container", "Card", "ListView", "GridView",
            "Stack", "ResponsiveRow", "SafeArea", "Wrap", "MenuBar",
        }:
            return "Layout"
        if control_name.startswith("Cupertino"):
            return "Cupertino"
        if any(token in name for token in (
            "button", "fab", "menuitem", "menubar", "submenu",
        )):
            return "Bottoni e menu"
        if any(token in name for token in ("dialog", "banner", "snackbar")):
            return "Dialoghi e notifiche"
        if any(token in name for token in (
            "field", "input", "dropdown", "checkbox", "switch", "slider",
            "radio", "datepicker", "timepicker", "autocomplete",
        )):
            return "Input"
        if any(token in name for token in (
            "navigation", "tab", "rail", "drawer", "view", "pageview",
        )):
            return "Navigazione"
        if any(token in name for token in (
            "text", "icon", "image", "progress", "divider", "chart",
            "markdown", "video", "audio",
        )):
            return "Testo e media"
        return "Altro"

    def control_picker_controls(query, parent_node, results):
        normalized_query = query.strip().casefold()
        grouped_controls = {}
        available_controls = (
            ["PopupMenuItem"]
            if parent_node.get("type") == "PopupMenuButton"
            else ["MenuItemButton", "SubmenuButton"]
            if parent_node.get("type") in {"MenuBar", "SubmenuButton"}
            else sorted(FLET_SCHEMA)
        )
        for control_name in available_controls:
            if normalized_query and normalized_query not in control_name.casefold():
                continue
            category = control_category(control_name)
            grouped_controls.setdefault(category, []).append(control_name)

        category_order = (
            "Layout", "Bottoni e menu", "Dialoghi e notifiche", "Input",
            "Cupertino", "Navigazione", "Testo e media", "Altro",
        )
        controls = []
        for category in category_order:
            names = grouped_controls.get(category)
            if not names:
                continue
            controls.append(
                ft.Text(category, size=13, weight=ft.FontWeight.BOLD, color="#90CAF9")
            )
            for offset in range(0, len(names), 3):
                controls.append(
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                name,
                                expand=True,
                                on_click=lambda e, component_type=name:
                                    choose_control_from_picker(
                                        component_type, parent_node
                                    ),
                            )
                            for name in names[offset:offset + 3]
                        ],
                        spacing=6,
                    )
                )
        if not controls:
            controls.append(ft.Text("Nessun controllo corrisponde alla ricerca."))
        results.controls = controls
        page.update()

    def choose_control_from_picker(control_name, parent_node):
        page.pop_dialog()
        if parent_node.get("_imported"):
            add_imported_child(parent_node, control_name)
            return
        add_component(control_name, parent_node=parent_node)

    def show_control_picker(parent_node):
        search_field = ft.TextField(
            label="Cerca un controllo",
            prefix_icon=ft.Icons.SEARCH,
            autofocus=True,
        )
        results = ft.Column(expand=True, spacing=8, scroll=ft.ScrollMode.AUTO)
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Aggiungi controllo"),
            content=ft.Column(
                [search_field, results],
                width=560,
                height=460,
                spacing=12,
            ),
            actions=[
                ft.TextButton("Chiudi", on_click=lambda e: page.pop_dialog())
            ],
        )
        control_picker_controls("", parent_node, results)
        search_field.on_change = lambda e: control_picker_controls(
            e.control.value or "", parent_node, results
        )
        page.show_dialog(dialog)

    def add_component(comp_type, parent_node=None):
        if not file_open[0]:
            page.show_dialog(ft.SnackBar(content=ft.Text("Apri o crea prima un file.")))
            return
        parent = parent_node or selected_node[0]
        if not parent or parent.get("_imported"):
            parent = layout_data
        if parent.get("children") is None:
            parent["children"] = []
            
        new_id = f"{comp_type.lower()}_{os.urandom(2).hex()}"
        props_dict = {}
        initial_children = []
        if comp_type in BUTTON_TYPES:
            props_dict["content"] = f"Nuovo {comp_type}"
        elif comp_type == "CupertinoButton":
            props_dict["content"] = f"Nuovo {comp_type}"
        elif comp_type == "IconButton":
            props_dict["icon"] = "ADD"
        elif comp_type in {"PopupMenuItem", "MenuItemButton"}:
            props_dict["content"] = "Nuova voce"
        elif comp_type in ["Text"]:
            props_dict["value"] = f"Nuovo {comp_type}"
        elif comp_type in ["TextField"]:
            props_dict["label"] = "Nuovo Campo"
            props_dict["width"] = 200
        elif comp_type in {"Row", "Column"}:
            props_dict.update({"expand": True, "spacing": 10})
        elif comp_type == "Image":
            props_dict["src"] = ""
        elif comp_type == "Dropdown":
            props_dict["options"] = [{
                "key": "nuova_opzione",
                "text": "Nuova opzione",
            }]
        elif comp_type == "PopupMenuButton":
            props_dict["icon"] = "MORE_VERT"
            initial_children.append({
                "id": f"popupmenuitem_{os.urandom(2).hex()}",
                "type": "PopupMenuItem",
                "props": {"content": "Nuova voce"},
                "children": [],
            })
        elif comp_type == "MenuBar":
            initial_children.append(default_menu_child("MenuBar"))
        elif comp_type == "SubmenuButton":
            props_dict["content"] = "Nuovo menu"
            initial_children.append(default_menu_child("SubmenuButton"))
            
        new_node = {
            "id": new_id,
            "type": comp_type,
            "props": props_dict,
            "children": initial_children,
        }
        parent["children"].append(new_node)
        selected_node[0] = new_node
        selected_imported_control[0] = None
        refresh_ui()
        update_inspector()

    def remove_interface_node(node):
        if not node or node.get("id") == "root":
            return

        if node.get("_imported"):
            source_path = node.get("_source_path")
            call = node.get("_call")
            line = call.lineno if call is not None else node.get("_line")
            column = call.col_offset if call is not None else node.get("_column")
            if source_path and line is not None and column is not None:
                for property_key in list(pending_property_values):
                    if property_key[0] == id(node):
                        pending_property_values.pop(property_key, None)
                if remove_source_component(source_path, line, column):
                    reload_opened_project()
                else:
                    page.show_dialog(ft.SnackBar(
                        content=ft.Text("Impossibile rimuovere il controllo dal codice.")
                    ))
            return

        parent = find_parent(layout_data, node["id"])
        if parent is None:
            return
        removed = find_node(layout_data, node["id"])
        removed_ids = set()

        def collect_removed_ids(current):
            removed_ids.add(id(current))
            for child in current.get("children", []) or []:
                collect_removed_ids(child)

        if removed is not None:
            collect_removed_ids(removed)
        parent["children"] = [
            child for child in parent.get("children", [])
            if child["id"] != node["id"]
        ]
        for property_key in list(pending_property_values):
            if property_key[0] in removed_ids:
                pending_property_values.pop(property_key, None)
        selected_node[0] = layout_data
        selected_imported_control[0] = None
        update_inspector()
        refresh_ui()

    def delete_current_node():
        remove_interface_node(selected_node[0])

    def export_project_zip(e):
        update_code_files()
        zip_filename = os.path.join(project_folder[0], f"{project_base_name[0]}_project.zip")
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            files_to_export = [os.path.basename(project_file_path("ui"))]
            if project_file_path("logic"):
                files_to_export.append(os.path.basename(project_file_path("logic")))
            files_to_export.extend([
                f"{project_base_name[0]}_run.py",
                f"{project_base_name[0]}_project.json",
                "requirements.txt",
            ])
            for file in files_to_export:
                filepath = os.path.join(project_folder[0], file)
                if os.path.exists(filepath):
                    zipf.write(filepath, arcname=file)
        page.show_dialog(ft.SnackBar(content=ft.Text(f"Progetto esportato in {zip_filename}!")))

    def export_and_run(e):
        stop_live_preview()
        if single_file_mode[0]:
            imported_harness[0] = PreviewHarness(project_file_path("ui"))
            running_process[0] = imported_harness[0].start()
            page.show_dialog(ft.SnackBar(content=ft.Text("File importato avviato in tempo reale!")))
            return

        ui_module_name = project_module_name("ui")
        logic_module_name = project_module_name("logic")
        preview_directory = tempfile.TemporaryDirectory(prefix="idea_dbm_live_")
        preview_path = preview_directory.name
        if project_code_authoritative[0]:
            ui_source = code_ui_view.value or ""
        else:
            ui_source = generate_layout_ui_source()
        logic_source = code_logic_view.value or (
            "# logic.py - Gestione logica\nimport flet as ft\n"
        )
        ui_path = os.path.join(preview_path, f"{ui_module_name}.py")
        logic_path = os.path.join(preview_path, f"{logic_module_name}.py")
        runner_path = os.path.join(preview_path, f"{project_base_name[0]}_run.py")
        with open(ui_path, "w", encoding="utf-8") as ui_file:
            ui_file.write(ui_source)
        with open(logic_path, "w", encoding="utf-8") as logic_file:
            logic_file.write(logic_source)
        runner_code = f"""import flet as ft
import sys
sys.path.insert(0, {project_folder[0]!r})
sys.path.insert(0, {preview_path!r})
import {logic_module_name} as logic
sys.modules["logic"] = logic
import {ui_module_name}

ft.run({ui_module_name}.main)
"""
        with open(runner_path, "w", encoding="utf-8") as f:
            f.write(runner_code)
        try:
            running_process[0] = subprocess.Popen(
                [sys.executable, runner_path],
                cwd=project_folder[0],
            )
        except OSError as error:
            preview_directory.cleanup()
            page.show_dialog(ft.SnackBar(content=ft.Text(f"Avvio anteprima non riuscito: {error}")))
            return
        running_preview_directory[0] = preview_directory
        page.show_dialog(ft.SnackBar(content=ft.Text("App avviata in tempo reale!")))

    file_picker = [None]

    def reload_opened_project():
        previous_node = selected_node[0]
        ui_path = project_file_path("ui")
        logic_path = project_file_path("logic")
        refresh_static_analysis()
        if os.path.exists(ui_path):
            with open(ui_path, "r", encoding="utf-8") as source_file:
                code_ui_view.value = source_file.read()
        if logic_path and os.path.exists(logic_path):
            with open(logic_path, "r", encoding="utf-8") as source_file:
                code_logic_view.value = source_file.read()
        elif not single_file_mode[0]:
            code_logic_view.value = (
                "import flet as ft\n\n"
                "def esegui_ricerca(e: ft.ControlEvent):\n"
                "    print('Ricerca avviata...')\n"
            )
            with open(logic_path, "w", encoding="utf-8") as logic_file:
                logic_file.write(code_logic_view.value)
        else:
            code_logic_view.value = ""

        update_code_highlighting()

        project_json = os.path.join(project_folder[0], f"{project_base_name[0]}_project.json")
        if os.path.exists(project_json):
            try:
                with open(project_json, "r", encoding="utf-8") as project_file:
                    loaded_layout = json.load(project_file)
                if isinstance(loaded_layout, dict) and loaded_layout.get("type"):
                    layout_data.clear()
                    layout_data.update(loaded_layout)
                    window_theme = loaded_layout.get("window_props", {}).get(
                        "theme_mode"
                    )
                    if window_theme is not None:
                        mode_name = str(window_theme).removeprefix(
                            "ft.ThemeMode."
                        ).upper()
                        if mode_name in {"LIGHT", "DARK", "SYSTEM"}:
                            project_theme_mode[0] = getattr(ft.ThemeMode, mode_name)
            except (OSError, json.JSONDecodeError):
                pass

        if previous_node and previous_node.get("_window"):
            selected_node[0] = create_window_node()
        elif previous_node and previous_node.get("_imported") and imported_analysis[0] is not None:
            components = flatten_components(imported_analysis[0].components)
            component = next(
                (
                    item for item in components
                    if item.id == previous_node.get("id")
                    or (
                        item.type_name == previous_node.get("type")
                        and item.line == previous_node.get("_line")
                        and item.column == previous_node.get("_column")
                    )
                ),
                None,
            )
            if component is None:
                matching_types = [
                    item for item in components
                    if item.type_name == previous_node.get("type")
                ]
                if matching_types:
                    old_line = previous_node.get("_line", 0)
                    old_column = previous_node.get("_column", 0)
                    component = min(
                        matching_types,
                        key=lambda item: (
                            abs(item.line - old_line),
                            abs(item.column - old_column),
                        ),
                    )
            if component is not None:
                props = parse_imported_component_properties(component)
                selected_node[0] = {
                    "id": component.id,
                    "type": component.type_name,
                    "props": props,
                    "_imported": True,
                    "_call": None,
                    "_line": component.line,
                    "_column": component.column,
                    "_end_line": component.end_line,
                    "_end_column": component.end_column,
                    "_source": imported_analysis[0].source,
                    "_source_path": imported_analysis[0].path,
                }
            else:
                selected_node[0] = layout_data
        elif previous_node and previous_node.get("id") != "root":
            selected_node[0] = find_node(layout_data, previous_node.get("id")) or layout_data
        else:
            selected_node[0] = layout_data
        selected_imported_control[0] = None

        set_preview_content(build_generated_preview())
        update_interface_tree()
        update_inspector()
        switch_tab(active_code_view[0])
        page.update()

    async def open_python_file(e=None):
        page.pop_dialog()
        if file_picker[0] is not None:
            selected_files = await file_picker[0].pick_files(
                dialog_title="Apri file Python del progetto",
                initial_directory=project_folder[0],
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["py"],
                allow_multiple=False,
            )
            if selected_files:
                load_selected_file(selected_files[0].path)

    def handle_code_change(e):
        project_code_authoritative[0] = True
        with open(project_file_path("ui"), "w", encoding="utf-8") as ui_file:
            ui_file.write(code_ui_view.value or "")
        logic_path = project_file_path("logic")
        if logic_path is not None:
            with open(logic_path, "w", encoding="utf-8") as logic_file:
                logic_file.write(code_logic_view.value or "")
        update_code_highlighting()
        set_preview_content(build_generated_preview())
        refresh_static_analysis()
        update_interface_tree()
        page.update()

    def load_selected_file(file_path):
        selected_path = os.path.abspath(file_path)
        selected_folder = os.path.dirname(selected_path)
        selected_stem = os.path.splitext(os.path.basename(selected_path))[0]
        base_name = selected_stem
        if base_name.endswith("_ui"):
            base_name = base_name[:-3]
        elif base_name.endswith("_logic"):
            base_name = base_name[:-6]
        ui_path = selected_path
        logic_path = os.path.join(selected_folder, f"{base_name}_logic.py")
        has_companion_logic = (
            selected_stem.endswith("_ui") and os.path.isfile(logic_path)
        )
        active_code_view[0] = "logic" if has_companion_logic else "ui"

        project_folder[0] = selected_folder
        project_base_name[0] = base_name or "idea_dbm"
        project_ui_file[0] = ui_path
        project_logic_file[0] = logic_path if has_companion_logic else None
        single_file_mode[0] = True
        file_open[0] = True
        selected_imported_control[0] = None
        project_code_authoritative[0] = True
        project_display_name[0] = os.path.basename(selected_path)
        try:
            imported_analysis[0] = analyze_module(selected_path)
        except (OSError, SyntaxError) as analysis_error:
            imported_analysis[0] = None
            imported_preview_error[0] = f"Analisi statica: {analysis_error}"
        update_project_file_labels()
        reload_opened_project()

    def initialize_new_project(new_name, destination):
        project_folder[0] = destination
        project_base_name[0] = python_module_name(
            new_name.removesuffix("_ui").removesuffix("_logic")
        )
        project_ui_file[0] = None
        project_logic_file[0] = None
        single_file_mode[0] = False
        file_open[0] = True
        selected_imported_control[0] = None
        project_code_authoritative[0] = False
        project_display_name[0] = None
        active_code_view[0] = "ui"
        project_theme_mode[0] = ft.ThemeMode.SYSTEM
        layout_data.clear()
        layout_data.update({
            "id": "root", "type": "Column", "props": {}, "children": [],
            "window_props": {},
        })
        selected_node[0] = layout_data
        code_logic_view.value = ""
        update_project_file_labels()
        update_code_files()
        refresh_ui()

    def create_new_project(e):
        new_name = new_project_name.value.strip()
        if not new_name:
            new_project_name.error_text = "Inserisci un nome"
            page.update()
            return
        new_project_name.error_text = None
        destination = os.path.abspath(
            os.path.expanduser((new_project_folder.value or "").strip())
        )
        if not os.path.isdir(destination):
            new_project_folder.error_text = "Scegli una cartella esistente"
            page.update()
            return
        new_project_folder.error_text = None
        base_name = python_module_name(
            new_name.removesuffix("_ui").removesuffix("_logic")
        )
        filenames = [f"{base_name}_ui.py", f"{base_name}_logic.py"]
        conflicts = [
            filename for filename in filenames
            if os.path.exists(os.path.join(destination, filename))
        ]
        if conflicts:
            page.pop_dialog()

            def replace_existing_project(event):
                page.pop_dialog()
                try:
                    initialize_new_project(new_name, destination)
                except OSError as create_error:
                    page.show_dialog(
                        ft.SnackBar(
                            content=ft.Text(
                                f"Creazione progetto non riuscita: {create_error}"
                            )
                        )
                    )

            confirmation = ft.CupertinoAlertDialog(
                modal=True,
                title=ft.Text("Sostituire i file esistenti?"),
                content=ft.Text(
                    f"Nella cartella sono già presenti: {', '.join(conflicts)}. "
                    "Vuoi sostituirli?"
                ),
                actions=[
                    ft.CupertinoDialogAction(
                        content="Annulla",
                        on_click=lambda event: page.pop_dialog(),
                    ),
                    ft.CupertinoDialogAction(
                        content="Sostituisci",
                        destructive=True,
                        on_click=replace_existing_project,
                    ),
                ],
            )
            page.show_dialog(confirmation)
            return

        page.pop_dialog()
        try:
            initialize_new_project(new_name, destination)
        except OSError as create_error:
            page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(
                        f"Creazione progetto non riuscita: {create_error}"
                    )
                )
            )

    async def choose_new_project_folder():
        if file_picker[0] is None:
            page.show_dialog(
                ft.SnackBar(content=ft.Text("Selettore cartelle non disponibile."))
            )
            return
        initial_directory = new_project_folder.value or WORK_DIR
        if not os.path.isdir(initial_directory):
            initial_directory = WORK_DIR
        try:
            destination = await file_picker[0].get_directory_path(
                dialog_title="Scegli la cartella del nuovo progetto",
                initial_directory=initial_directory,
            )
        except OSError as picker_error:
            page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(
                        f"Impossibile scegliere la cartella: {picker_error}"
                    )
                )
            )
            return
        if destination:
            new_project_folder.value = destination
            new_project_folder.error_text = None
            page.update()

    def show_new_project_dialog(e=None):
        page.pop_dialog()
        page.show_dialog(new_project_dialog)

    def close_current_file(e=None):
        stop_live_preview()
        file_open[0] = False
        single_file_mode[0] = False
        project_ui_file[0] = None
        project_logic_file[0] = None
        project_display_name[0] = None
        code_ui_view.value = ""
        code_logic_view.value = ""
        imported_preview_controls[0] = []
        imported_preview_error[0] = None
        imported_analysis[0] = None
        imported_control_nodes.clear()
        imported_harness[0] = None
        selected_imported_control[0] = None
        layout_data.clear()
        layout_data.update({"id": "root", "type": "Column", "props": {}, "children": []})
        selected_node[0] = layout_data
        set_preview_content(ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=ft.Text("Nessun file aperto", color="#9E9E9E"),
        ))
        tab_content_container.content = ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=ft.Text("Nessun file aperto", color="#9E9E9E"),
        )
        update_project_file_labels()
        update_interface_tree()
        top_bar.update()
        page.update()

    new_project_name = ft.TextField(
        label="Nome progetto",
        value="mio_progetto",
        autofocus=True,
    )
    new_project_folder = ft.TextField(
        label="Cartella di destinazione",
        value=WORK_DIR,
        expand=True,
        dense=True,
    )
    new_project_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Crea nuovo progetto"),
        content=ft.Column(
            [
                ft.Text(
                    "Verranno creati i file <nome>_ui.py e <nome>_logic.py "
                    "nella cartella selezionata."
                ),
                new_project_name,
                ft.Row(
                    [
                        new_project_folder,
                        ft.CupertinoButton(
                            content="Sfoglia",
                            on_click=choose_new_project_folder,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            tight=True,
            width=500,
            spacing=12,
        ),
        actions=[
            ft.TextButton("Annulla", on_click=lambda e: page.pop_dialog()),
            ft.FilledButton("Crea progetto", on_click=create_new_project),
        ],
    )

    startup_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Benvenuto in IDEa dBM"),
        content=ft.Text("Vuoi aprire un file Python esistente o creare un nuovo progetto?"),
        actions=[
            ft.TextButton("Apri file .py", on_click=open_python_file),
            ft.FilledButton("Nuovo progetto", on_click=show_new_project_dialog),
        ],
    )

    def toggle_theme(e):
        is_dark = page.theme_mode == ft.ThemeMode.DARK
        next_theme = ft.ThemeMode.LIGHT if is_dark else ft.ThemeMode.DARK
        next_is_dark = next_theme == ft.ThemeMode.DARK
        next_background = "#121212" if next_is_dark else "#F5F5F5"
        next_panel_background = "#252526" if next_is_dark else "#EEEEEE"
        next_surface_background = "#1E1E1E" if next_is_dark else "#FAFAFA"
        next_code_background = "#121212" if next_is_dark else "#FFFFFF"
        next_text_color = "#E0E0E0" if next_is_dark else "#212121"

        page.bgcolor = next_background
        top_bar.bgcolor = "#333333" if next_is_dark else "#E0E0E0"
        inspector.bgcolor = next_panel_background
        canvas_area.bgcolor = next_surface_background
        tab_bar.bgcolor = "#181818" if next_is_dark else "#E0E0E0"
        tab_content_container.bgcolor = next_surface_background
        code_ui_view.bgcolor = next_code_background
        code_logic_view.bgcolor = next_code_background
        code_ui_view.text_style = ft.TextStyle(font_family="Consolas", size=12, color=next_text_color)
        code_logic_view.text_style = ft.TextStyle(font_family="Consolas", size=12, color=next_text_color)
        code_theme = (
            ft.MarkdownCodeTheme.ATOM_ONE_DARK
            if next_is_dark
            else ft.MarkdownCodeTheme.ATOM_ONE_LIGHT
        )
        code_ui_highlight.code_theme = code_theme
        code_logic_highlight.code_theme = code_theme
        for input_control in (ai_prompt_input, pkg_input, fb_host, fb_path, fb_user, fb_password, fb_query):
            input_control.text_style = ft.TextStyle(color=next_text_color)

        page.theme_mode = next_theme
        update_interface_tree()
        ide_theme_button.icon = ft.Icons.LIGHT_MODE if next_is_dark else ft.Icons.DARK_MODE
        page.update()

    ide_theme_button = ft.IconButton(
        icon=ft.Icons.DARK_MODE,
        tooltip="Cambia Tema IDE",
        on_click=toggle_theme,
    )
    project_title = ft.Text("", weight=ft.FontWeight.BOLD, size=16)
    file_close_button = ft.IconButton(
        icon=ft.Icons.CLOSE,
        tooltip="Chiudi file corrente",
        on_click=lambda e: close_current_file(e),
    )
    file_open_button = ft.IconButton(
        icon=ft.Icons.FOLDER_OPEN,
        tooltip="Apri o crea file",
        visible=False,
        on_click=lambda e: page.show_dialog(startup_dialog),
    )
    top_bar = ft.Container(
        padding=10, bgcolor="#333333",
        content=ft.Row([
            project_title,
            file_close_button,
            file_open_button,
            ft.VerticalDivider(),
            ft.IconButton(icon=ft.Icons.PLAY_ARROW, tooltip="Avvia Live", on_click=export_and_run),
            ide_theme_button
        ])
    )
    top_bar_ref[0] = top_bar

    inspector = ft.Container(
        width=300,
        bgcolor="#252526",
        padding=10,
        content=ft.Column([
            inspector_area,
            ft.Divider(height=1, color="#555555"),
            ft.Text("ALBERO INTERFACCIA FLET", weight=ft.FontWeight.BOLD, size=12, color="#90CAF9"),
            interface_tree_scroller,
        ], expand=True, spacing=6),
    )

    center_workspace = ft.Column([
        canvas_area,
        code_panel_wrapper
    ], expand=True, spacing=0)

    page.add(
        ft.Column([
            top_bar,
            ft.Row([center_workspace, inspector], expand=True, spacing=0)
        ], expand=True, spacing=0)
    )

    code_ui_view.on_change = handle_code_change
    code_logic_view.on_change = handle_code_change
    update_project_file_labels()
    switch_tab("ui")
    refresh_package_list()
    refresh_ui()
    update_project_theme_button()
    update_inspector()
    file_picker[0] = ft.FilePicker()
    page.services.append(file_picker[0])
    page.show_dialog(startup_dialog)

if __name__ == "__main__":
    ft.run(main)
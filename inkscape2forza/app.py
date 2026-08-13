from . import gamesave, library, ui, workflows


ACTIONS = (
    ("🧩", "安装FH6符号库到Inkscape", "Install symbol library to Inkscape", workflows.workflow_install_inkscape_symbols),
    ("🎨", "从Geometrize JSON生成SVG", "Generate SVG from Geometrize JSON", workflows.workflow_geometrize_to_svg),
    ("🎨", "从Vinylizer JSON生成SVG", "Generate SVG from Vinylizer JSON", workflows.workflow_vinylizer_to_svg),
    ("💾", "备份当前账户存档", "Back up current gamesave", workflows.workflow_backup_save),
    ("⬇️", "将SVG导入存档", "Import SVG to gamesave", workflows.workflow_inject_svg),
    ("⬆️", "从存档导出SVG", "Export SVG from gamesave", workflows.workflow_export_svg),
)


def main():
    library.preload_symbol_library()
    ui.run(ui.App(ACTIONS, gamesave.refresh_accounts, gamesave.select_account))

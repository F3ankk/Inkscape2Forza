"""FH6 save discovery and backup."""
import datetime
import os
import re
import shutil

from . import cgroup_codec, ui
from .common import DEFAULT_GAMESAVE_DIR
from .i18n import tr
from .xbox_profiles import resolve_gamertags

_cached_gamesave_dir = None
_accounts = {}
_selected_account = None


def backup_default_filename(u_dir):
    match = re.fullmatch(r"u_(\d+)_16D460", os.path.basename(os.path.normpath(u_dir)))
    xuid = match.group(1) if match else os.path.basename(os.path.normpath(u_dir))
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return f"backup_{xuid}_{timestamp}.zip"


def create_backup(u_dir, output_path):
    output_path = os.path.normpath(output_path)
    backup_path_base = output_path[:-4] if output_path.lower().endswith(".zip") else output_path

    ui.log(tr("正在打包备份...", "Processing backup..."))
    archive_path = shutil.make_archive(backup_path_base, 'zip', u_dir)
    ui.log(tr(f"备份完成：{archive_path}", f"Backup complete: {archive_path}"))
    return archive_path


def refresh_accounts(prompt=False):
    """Refresh local save accounts."""
    global _cached_gamesave_dir, _accounts, _selected_account
    if _cached_gamesave_dir and os.path.exists(_cached_gamesave_dir):
        gamesave_dir = _cached_gamesave_dir
    elif os.path.exists(DEFAULT_GAMESAVE_DIR) and os.path.exists(os.path.join(DEFAULT_GAMESAVE_DIR, "pgs")):
        gamesave_dir = DEFAULT_GAMESAVE_DIR
    elif prompt:
        gamesave_dir = ui.ask_folder(tr("选择 GameSave 文件夹", "Select GameSave folder"))
        if not gamesave_dir:
            ui.log(tr("已取消", "Cancelled"))
            return []
    else:
        _accounts = {}
        _selected_account = None
        return []

    pgs_dir = os.path.join(gamesave_dir, "pgs")
    if not os.path.exists(pgs_dir):
        if prompt:
            ui.log(tr("这不是有效的存档文件夹", "This is not a valid GameSave folder"))
        _cached_gamesave_dir = None
        _accounts = {}
        _selected_account = None
        return []

    _cached_gamesave_dir = gamesave_dir
    account_folders = sorted(
        folder for folder in os.listdir(pgs_dir)
        if folder.startswith("u_") and folder.endswith("_16D460")
        and os.path.isdir(os.path.join(pgs_dir, folder, "current", "ContainersRoot"))
    )
    account_xuids = {
        folder: match.group(1)
        for folder in account_folders
        if (match := re.fullmatch(r"u_(\d+)_16D460", folder))
    }
    gamertags = resolve_gamertags(account_xuids.values())
    _accounts = {}
    for folder, xuid in account_xuids.items():
        label = gamertags.get(xuid, xuid)
        if label in _accounts:
            label = f"{label} ({xuid})"
        _accounts[label] = os.path.join(pgs_dir, folder)
    account_labels = list(_accounts)
    if _selected_account not in _accounts:
        _selected_account = account_labels[0] if account_labels else None
    if not account_labels and prompt:
        ui.log(tr("未找到玩家数据", "No player data found"))
    return account_labels


def select_account(account_name):
    global _selected_account
    if account_name in _accounts:
        _selected_account = account_name
        return True
    return False


def choose_containers_root():
    """Return paths for the selected account."""
    if not _accounts and not refresh_accounts(prompt=True):
        return None, None, None
    u_dir = _accounts.get(_selected_account)
    if not u_dir:
        ui.log(tr("未选择有效账户", "No valid account is selected"))
        return None, None, None

    containers_root = os.path.join(u_dir, "current", "ContainersRoot")
    if not os.path.exists(containers_root):
        ui.log(tr("未找到数据根目录", "No root directory found"))
        return None, None, None
    ui.refresh_accounts()
    return _cached_gamesave_dir, u_dir, containers_root


def get_target_layer_groups(containers_root):
    valid_groups = []
    try:
        folders = sorted(
            entry.path for entry in os.scandir(containers_root)
            if entry.is_dir() and entry.name.startswith("LayerGroup_0000_")
        )
    except OSError:
        return valid_groups

    for folder in folders:
        c_group_path = os.path.join(folder, "C_group")
        header_path = os.path.join(folder, "header")

        if os.path.exists(c_group_path) and os.path.exists(header_path):
            try:
                with open(c_group_path, 'rb') as f:
                    checked_data = f.read()
                cgroup_codec.validate_cgroup_data(checked_data)
            except Exception:
                continue
            title, author = cgroup_codec.parse_header(header_path)
            valid_groups.append({
                "path": c_group_path,
                "thumbnail": os.path.join(folder, "thumb.webp"),
                "folder_name": os.path.basename(folder),
                "title": title,
                "author": author,
            })
    return valid_groups


def inject_cgroup(target_cgroup, root_group):
    try:
        cgroup_codec.write_cgroup_file(target_cgroup, root_group)
    except Exception as e:
        ui.log(tr(f"写入彩绘纹饰分组失败：{e}", f"Failed to write vinyl group: {e}"))
        return False

    ui.log(tr("注入成功", "Injection successful"))
    return True

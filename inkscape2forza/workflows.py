"""GUI workflows."""
import json
import math
import os
import re
import shutil
import subprocess

from . import cgroup_codec, gamesave, library, svg_codec, ui
from .common import MAX_VINYL_GROUP_LAYERS, get_resource_path
from .i18n import tr
from .model import count_shapes

# Helpers

def find_inkscape_user_data_dir():
    """Find the active Inkscape profile."""
    candidates = [
        shutil.which("inkscape.com"),
        shutil.which("inkscape"),
        r"C:\Program Files\Inkscape\bin\inkscape.com",
    ]
    for executable in dict.fromkeys(path for path in candidates if path):
        try:
            result = subprocess.run(
                [executable, "--user-data-directory"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            data_dir = result.stdout.strip()
            if result.returncode == 0 and os.path.isdir(data_dir):
                return data_dir
        except (OSError, subprocess.SubprocessError):
            continue

    appdata = os.environ.get("APPDATA")
    fallback = os.path.join(appdata, "inkscape") if appdata else ""
    return fallback if os.path.isdir(fallback) else None


def pick_target_group(target_groups):
    """Pick a vinyl group."""
    options = [f"{g['title']} - {g['author']}" for g in target_groups]
    idx = ui.ask_choice(
        tr("选择彩绘纹饰分组", "Select vinyl group"),
        tr("请选择要操作的彩绘纹饰分组（缩略图不一定正确，以游戏内为准）", "Please select the vinyl group (thumbnail may be inaccurate, check in-game)"),
        options,
        [group["thumbnail"] for group in target_groups],
    )
    if idx is None:
        ui.log(tr("已取消", "Cancelled"))
        return None
    return target_groups[idx]


def append_shape_wrapper(target_container, symbol_dict):
    """Build a JSON-to-SVG shape appender."""
    def append_shape(svg_cx, svg_cy, sx, sy, rot_deg, fill_val, opacity_val, href, node_id):
        svg_codec.append_shape_use(target_container, href, symbol_dict,
                                   svg_cx, svg_cy, sx, sy, rot_deg, fill_val, opacity_val, node_id)
    return append_shape


# Symbol installation

def workflow_install_inkscape_symbols():
    ui.log(tr("\n准备安装 FH6 Inkscape 符号库...", "\nPreparing to install the FH6 Inkscape symbol library..."))
    source_libraries = (
        ("fh6_vinyl_symbols.svg", "symbols", "FH6_Vinyl_Symbols.svg"),
        ("fh6_vinyl_patterns.svg", "paint", "FH6_Vinyl_Patterns.svg"),
    )
    missing = [filename for filename, _, _ in source_libraries if not os.path.isfile(get_resource_path(filename))]
    if missing:
        ui.log(tr(f"错误：找不到资源文件：{', '.join(missing)}", f"Error: Missing resource files: {', '.join(missing)}"))
        return

    data_dir = find_inkscape_user_data_dir()
    if data_dir:
        ui.log(tr(f"检测到 Inkscape 用户目录：\n  {data_dir}", f"Inkscape user directory detected:\n  {data_dir}"))
    else:
        ui.log(tr("未能自动定位 Inkscape 用户目录，请选择 Symbols 文件夹。",
                  "Could not locate the Inkscape profile; select its Symbols folder."))
        symbols_dir = ui.ask_folder(tr("选择 Inkscape Symbols 文件夹", "Select Inkscape Symbols folder"))
        if not symbols_dir:
            ui.log(tr("已取消", "Cancelled"))
            return
        data_dir = os.path.dirname(symbols_dir)

    destinations = [
        (get_resource_path(filename), os.path.join(data_dir, folder, installed_name))
        for filename, folder, installed_name in source_libraries
    ]
    existing = [destination for _, destination in destinations if os.path.exists(destination)]
    if existing:
        if not ui.ask_confirm(tr("覆盖确认", "Overwrite?"),
                              tr("已有 FH6 符号库或图案库，是否覆盖？", "Existing FH6 libraries found. Overwrite?")):
            ui.log(tr("已取消", "Cancelled"))
            return

    try:
        for source, destination in destinations:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)
            ui.log(tr(f"已安装：\n  {destination}", f"Installed:\n  {destination}"))
        ui.log(tr("请重启 Inkscape 或重新打开 Symbols/Fill and Stroke 面板以加载新资源。",
                  "Restart Inkscape or reopen the Symbols/Fill and Stroke panels to load the libraries."))
    except Exception as e:
        ui.log(tr(f"安装失败：{e}", f"Installation failed: {e}"))


# Geometrize import

def workflow_geometrize_to_svg():
    ui.log(tr("\n[1/3] 请选择 Geometrize 导出的 JSON 文件...", "\n[1/3] Please select a Geometrize JSON file..."))
    json_path = ui.ask_open_file("Geometrize JSON", [(tr("JSON 文件", "JSON files"), "*.json")])
    if not json_path:
        ui.log(tr("已取消", "Cancelled"))
        return

    ui.log(tr("[2/3] 正在加载内部符号库进行合成...", "[2/3] Loading the internal symbol library..."))

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            geo_data = json.load(f)

        shapes = geo_data.get("shapes", geo_data if isinstance(geo_data, list) else [])
        if isinstance(geo_data, dict) and "shapes" not in geo_data:
            shapes = []

        if not shapes:
            ui.log(tr("错误：JSON 文件中没有找到有效的形状数据。", "Error: No valid shapes found in JSON."))
            return
    except Exception as e:
        ui.log(tr(f"读取 JSON 失败：{e}", f"Failed to read JSON: {e}"))
        return

    boundary_index = next((
        idx for idx, shape in enumerate(shapes)
        if shape.get("type") == 1
        and len(shape.get("data", [])) >= 4
        and json_shape_is_transparent(shape)
    ), None)

    raw_layer_count = 4 if boundary_index is not None else 0
    layer_count = raw_layer_count
    for idx, shape in enumerate(shapes):
        type_code = shape.get("type")
        data = shape.get("data", [])
        if type_code not in (1, 16) or len(data) < 4:
            continue
        if idx == boundary_index:
            continue
        raw_layer_count += 1
        if json_shape_is_transparent(shape):
            continue
        layer_count += 1
    ui.log(tr(f"原始图层数：{raw_layer_count}", f"Original layers: {raw_layer_count}"))
    ui.log(tr(f"过滤后图层数：{layer_count}", f"Layers after filtering: {layer_count}"))
    default_name = f"{os.path.splitext(os.path.basename(json_path))[0]}.{layer_count}.svg"

    ui.log(tr("[3/3] 请选择合并后 SVG 文件的保存位置...", "[3/3] Select where to save the generated SVG..."))
    save_path = ui.ask_save_file(
        title=tr("保存由 Geometrize 生成的 SVG", "Save generated SVG"),
        filetypes=[(tr("SVG 文件", "SVG files"), "*.svg")],
        initialfile=default_name,
    )
    if not save_path:
        ui.log(tr("已取消", "Cancelled"))
        return

    try:
        symbol_dict, _, symbol_elements = library.load_symbol_library()
        tree, root, defs, target_container = svg_codec.create_inkscape_document()
        canvas_w, canvas_h = 1920.0, 1080.0

        rect_href, circle_href = None, None
        for k in symbol_dict.keys():
            if k.endswith('_w101'):
                rect_href = k
            elif k.endswith('_w102'):
                circle_href = k

        if not rect_href or not circle_href:
            ui.log(tr("错误：模板库中找不到基础矩形（w101）或圆形（w102）的符号引用。",
                      "Error: Cannot find the rectangle (w101) or circle (w102) symbols."))
            return

        append_shape = append_shape_wrapper(target_container, symbol_dict)

        geo_w, geo_h = 2048.0, 2048.0
        if boundary_index is not None:
            boundary_data = shapes[boundary_index].get("data", [])
            geo_w = float(boundary_data[2])
            geo_h = float(boundary_data[3])

        min_ext_x, max_ext_x = float('inf'), float('-inf')
        min_ext_y, max_ext_y = float('inf'), float('-inf')
        has_visible_shapes = False

        for idx, shape in enumerate(shapes):
            type_code = shape.get("type")
            data = shape.get("data", [])
            if idx == boundary_index or json_shape_is_transparent(shape):
                continue
            if len(data) < 4 or type_code not in (1, 16):
                continue

            has_visible_shapes = True
            if type_code == 1:
                geo_cx = float(data[0]) + float(data[2]) / 2.0
                geo_cy = float(data[1]) + float(data[3]) / 2.0
                hw = float(data[2]) / 2.0
                hh = float(data[3]) / 2.0
            else:
                geo_cx = float(data[0])
                geo_cy = float(data[1])
                hw = float(data[2])
                hh = float(data[3])

            radius = math.hypot(hw, hh)
            min_ext_x = min(min_ext_x, geo_cx - radius)
            max_ext_x = max(max_ext_x, geo_cx + radius)
            min_ext_y = min(min_ext_y, geo_cy - radius)
            max_ext_y = max(max_ext_y, geo_cy + radius)

        if not has_visible_shapes:
            if boundary_index is not None:
                boundary_data = shapes[boundary_index].get("data", [])
                min_ext_x = float(boundary_data[0])
                min_ext_y = float(boundary_data[1])
                max_ext_x = min_ext_x + float(boundary_data[2])
                max_ext_y = min_ext_y + float(boundary_data[3])
            else:
                min_ext_x = max_ext_x = min_ext_y = max_ext_y = 0.0

        valid_count = 0
        deferred_masks = []

        for idx, shape in enumerate(shapes):
            type_code = shape.get("type")

            if type_code not in (1, 16):
                ui.log(tr(f"跳过不支持的元素（索引 {idx}）：类型 {type_code}",
                          f"Skipped unsupported element (index {idx}): type {type_code}"))
                continue

            data = shape.get("data", [])
            if len(data) < 4:
                continue

            if json_shape_is_transparent(shape) and idx != boundary_index:
                continue

            color = list(shape.get("color", [255, 255, 255, 255]))
            color.extend([255] * (4 - len(color)))
            r, g, b, a = [max(0, min(255, int(v))) for v in color]

            if type_code == 1:
                geo_cx = float(data[0]) + float(data[2]) / 2.0
                geo_cy = float(data[1]) + float(data[3]) / 2.0
                sx = float(data[2]) / 127.0
                sy = float(data[3]) / 127.0
                rot_deg = float(data[4]) if len(data) >= 5 else 0.0
                href = rect_href
            else:  # type == 16
                geo_cx = float(data[0])
                geo_cy = float(data[1])
                sx = float(data[2]) / 63.0
                sy = float(data[3]) / 63.0
                rot_deg = (360.0 - float(data[4])) % 360.0 if len(data) >= 5 else 0.0
                href = circle_href

            svg_cx = geo_cx + (canvas_w / 2.0 - geo_w / 2.0)
            svg_cy = geo_cy + (canvas_h / 2.0 - geo_h / 2.0)

            if idx == boundary_index:
                hw = float(data[2]) / 2.0
                hh = float(data[3]) / 2.0

                svg_min_ext_x = min_ext_x + (canvas_w / 2.0 - geo_w / 2.0)
                svg_max_ext_x = max_ext_x + (canvas_w / 2.0 - geo_w / 2.0)
                svg_min_ext_y = min_ext_y + (canvas_h / 2.0 - geo_h / 2.0)
                svg_max_ext_y = max_ext_y + (canvas_h / 2.0 - geo_h / 2.0)

                top = max(10.0, (svg_cy - hh) - svg_min_ext_y + 20.0)
                bottom = max(10.0, svg_max_ext_y - (svg_cy + hh) + 20.0)
                left = max(10.0, (svg_cx - hw) - svg_min_ext_x + 20.0)
                right = max(10.0, svg_max_ext_x - (svg_cx + hw) + 20.0)

                mask_width = 2 * hw + left + right
                deferred_masks.append((svg_cx + (right - left) / 2.0, svg_cy - hh - top / 2.0, mask_width / 127.0, top / 127.0, 0.0, "url(#mask_indicator_dark)", 1.0, rect_href, f"mask_geo_{idx}_top"))
                deferred_masks.append((svg_cx + (right - left) / 2.0, svg_cy + hh + bottom / 2.0, mask_width / 127.0, bottom / 127.0, 0.0, "url(#mask_indicator_dark)", 1.0, rect_href, f"mask_geo_{idx}_bottom"))
                deferred_masks.append((svg_cx - hw - left / 2.0, svg_cy, left / 127.0, (2 * hh) / 127.0, 0.0, "url(#mask_indicator_dark)", 1.0, rect_href, f"mask_geo_{idx}_left"))
                deferred_masks.append((svg_cx + hw + right / 2.0, svg_cy, right / 127.0, (2 * hh) / 127.0, 0.0, "url(#mask_indicator_dark)", 1.0, rect_href, f"mask_geo_{idx}_right"))
                valid_count += 4
                continue

            fill_hex = f"#{r:02x}{g:02x}{b:02x}"
            opacity = round(a / 255.0, 4)

            append_shape(svg_cx, svg_cy, sx, sy, rot_deg, fill_hex, opacity, href, f"geo_shape_{idx}")
            valid_count += 1

        for mask_args in deferred_masks:
            append_shape(*mask_args)

        library.add_referenced_defs(root, defs, symbol_elements)
        svg_codec.prune_unused_defs(root)
        svg_codec.write_inkscape_svg(tree, save_path)
        ui.log(tr(f"成功写入 {valid_count} 个图形", f"Wrote {valid_count} shapes"))
        ui.log(tr(f"文件已保存至：{os.path.normpath(save_path)}", f"Saved: {os.path.normpath(save_path)}"))
    except Exception as e:
        ui.log(tr(f"错误：{e}", f"Error: {e}"))


# Vinylizer import

def workflow_vinylizer_to_svg():
    ui.log(tr("\n[1/3] 请选择 Vinylizer 导出的 JSON 文件...", "\n[1/3] Please select a Vinylizer JSON file..."))
    json_path = ui.ask_open_file("Vinylizer JSON", [("JSON", "*.json")])
    if not json_path:
        ui.log(tr("已取消", "Cancelled"))
        return

    ui.log(tr("[2/3] 正在加载内部符号库进行合成...", "[2/3] Loading the internal symbol library..."))

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            vin_data = json.load(f)

        shapes = vin_data.get("shapes", vin_data if isinstance(vin_data, list) else [])
        if isinstance(vin_data, dict) and "shapes" not in vin_data:
            shapes = []

        if not shapes:
            ui.log(tr("错误：JSON 文件中没有找到有效的形状数据。", "Error: No valid shapes found in JSON."))
            return
    except Exception as e:
        ui.log(tr(f"读取 JSON 失败：{e}", f"Failed to read JSON: {e}"))
        return

    opacity_threshold = ui.ask_int(
        tr("不透明度阈值", "Opacity threshold"),
        tr("忽略不透明度小于或等于此值的图层（0-255）：",
           "Ignore layers with opacity less than or equal to this value (0-255):"),
        default=0, minvalue=0, maxvalue=255,
    )
    if opacity_threshold is None:
        ui.log(tr("已取消", "Cancelled"))
        return

    supported_types = {1, 16, 103, 228}
    raw_layer_count = sum(
        1 for shape in shapes
        if shape.get("type") in supported_types
        and len(shape.get("data", [])) >= 4
    )
    layer_count = sum(
        1 for shape in shapes
        if shape.get("type") in supported_types
        and len(shape.get("data", [])) >= 4
        and not json_shape_is_at_or_below_opacity(shape, opacity_threshold)
    )
    ui.log(tr(f"原始图层数：{raw_layer_count}", f"Original layers: {raw_layer_count}"))
    ui.log(tr(f"过滤后图层数：{layer_count}", f"Layers after filtering: {layer_count}"))
    default_name = f"{os.path.splitext(os.path.basename(json_path))[0]}.{layer_count}.svg"

    ui.log(tr("[3/3] 请选择合并后 SVG 文件的保存位置...", "[3/3] Select where to save the generated SVG..."))
    save_path = ui.ask_save_file(
        title=tr("保存由 Vinylizer 生成的 SVG", "Save generated SVG"),
        filetypes=[("SVG", "*.svg")],
        initialfile=default_name,
    )
    if not save_path:
        ui.log(tr("已取消", "Cancelled"))
        return

    try:
        symbol_dict, _, symbol_elements = library.load_symbol_library()
        tree, root, defs, target_container = svg_codec.create_inkscape_document()
        canvas_w, canvas_h = 1920.0, 1080.0

        # type: (FH6 shape, X divisor, Y divisor)
        shape_specs = {
            1: (101, 127.0, 127.0),
            16: (102, 63.0, 63.0),
            103: (103, 63.0, 109.265625),
            228: (228, 63.0, 63.0),
        }
        href_by_type = {}
        for type_code, (shape_word, _, _) in shape_specs.items():
            suffix = f'_w{shape_word}'
            href = next((key for key in symbol_dict if key.endswith(suffix)), None)
            if href:
                href_by_type[type_code] = href

        missing_types = [type_code for type_code in shape_specs if type_code not in href_by_type]
        if missing_types:
            missing_words = ', '.join(f'w{shape_specs[type_code][0]}' for type_code in missing_types)
            ui.log(tr(f"错误：符号库中找不到 {missing_words}", f"Error: Missing symbols: {missing_words}"))
            return

        append_shape = append_shape_wrapper(target_container, symbol_dict)

        # Canvas bounds
        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')
        has_valid_shapes = False

        for shape in shapes:
            if shape.get("type") not in shape_specs:
                continue
            if json_shape_is_at_or_below_opacity(shape, opacity_threshold):
                continue
            data = shape.get("data", [])
            if len(data) >= 4:
                has_valid_shapes = True
                geo_cx = float(data[0])
                geo_cy = float(data[1])
                min_x = min(min_x, geo_cx)
                max_x = max(max_x, geo_cx)
                min_y = min(min_y, geo_cy)
                max_y = max(max_y, geo_cy)

        if has_valid_shapes:
            geo_cx_center = (min_x + max_x) / 2.0
            geo_cy_center = (min_y + max_y) / 2.0
        else:
            geo_cx_center, geo_cy_center = canvas_w / 2.0, canvas_h / 2.0

        offset_x = (canvas_w / 2.0) - geo_cx_center
        offset_y = (canvas_h / 2.0) - geo_cy_center

        valid_count = 0
        for idx, shape in enumerate(shapes):
            type_code = shape.get("type")

            if type_code not in shape_specs:
                ui.log(tr(f"跳过不支持的元素（索引 {idx}）：类型 {type_code}",
                          f"Skipped unsupported shape (index {idx}): type {type_code}"))
                continue

            data = shape.get("data", [])
            if len(data) < 4:
                continue

            if json_shape_is_at_or_below_opacity(shape, opacity_threshold):
                continue

            color = list(shape.get("color", [255, 255, 255, 255]))
            color.extend([255] * (4 - len(color)))
            r, g, b, a = [max(0, min(255, int(v))) for v in color]

            # Older rectangles may omit angle.
            geo_cx = float(data[0])
            geo_cy = float(data[1])
            _, divisor_x, divisor_y = shape_specs[type_code]
            sx = float(data[2]) / divisor_x
            sy = float(data[3]) / divisor_y
            rot_deg = (360.0 - float(data[4])) % 360.0 if len(data) >= 5 else 0.0
            href = href_by_type[type_code]

            svg_cx = geo_cx + offset_x
            svg_cy = geo_cy + offset_y

            fill_hex = f"#{r:02x}{g:02x}{b:02x}"
            opacity = round(a / 255.0, 4)

            append_shape(svg_cx, svg_cy, sx, sy, rot_deg, fill_hex, opacity, href, f"vin_shape_{idx}")
            valid_count += 1

        library.add_referenced_defs(root, defs, symbol_elements)
        svg_codec.prune_unused_defs(root)
        svg_codec.write_inkscape_svg(tree, save_path)
        ui.log(tr(f"成功写入 {valid_count} 个图形", f"Wrote {valid_count} shapes"))
        ui.log(tr(f"文件已保存至：{os.path.normpath(save_path)}", f"Saved: {os.path.normpath(save_path)}"))
    except Exception as e:
        ui.log(tr(f"错误：{e}", f"Error: {e}"))


# Save backup

def workflow_backup_save():
    ui.log(tr("\n正在定位当前账户存档...", "\nLocating the current account save..."))
    _, u_dir, containers_root = gamesave.choose_containers_root()
    if not containers_root:
        return
    ui.log(tr(f"当前存档：{os.path.normpath(u_dir)}", f"Current save: {os.path.normpath(u_dir)}"))
    output_path = ui.ask_save_file(
        title=tr("保存账户存档备份", "Save account backup"),
        filetypes=[(tr("ZIP 压缩包", "ZIP archive"), "*.zip")],
        initialfile=gamesave.backup_default_filename(u_dir),
        defaultextension=".zip",
    )
    if not output_path:
        ui.log(tr("已取消", "Cancelled"))
        return
    try:
        gamesave.create_backup(u_dir, output_path)
    except Exception as e:
        ui.log(tr(f"备份失败：{e}", f"Backup failed: {e}"))


# SVG injection

def workflow_inject_svg():
    ui.log(tr("\n[1/3] 正在定位当前账户存档...", "\n[1/3] Locating the current account save..."))

    gamesave_dir, u_dir, containers_root = gamesave.choose_containers_root()
    if not containers_root:
        return
    ui.log(tr(f"已定位到存档：{os.path.normpath(u_dir)}", f"Save located: {os.path.normpath(u_dir)}"))

    ui.log(tr("[2/3] 请选择要注入的 Inkscape SVG 文件...", "[2/3] Select the Inkscape SVG to inject..."))
    svg_path = ui.ask_open_file("Inkscape SVG", [("SVG", "*.svg")])
    if not svg_path:
        ui.log(tr("已取消", "Cancelled"))
        return

    ui.log(tr(f"正在解析 SVG：{os.path.basename(svg_path)}", f"Parsing SVG: {os.path.basename(svg_path)}"))
    try:
        root_group, total_nodes = svg_codec.process_svg(svg_path)
        layer_count = count_shapes(root_group)
        ui.log(tr(f"识别到 {total_nodes} 个元素，过滤后有效图层数：{layer_count}",
                  f"Found {total_nodes} elements; {layer_count} valid layers after filtering"))
    except Exception as e:
        ui.log(tr(f"解析 SVG 失败：{e}", f"Failed to parse SVG: {e}"))
        return

    if layer_count > MAX_VINYL_GROUP_LAYERS:
        ui.log(tr(f"错误：有效图层数 {layer_count} 超过 FH6 彩绘纹饰分组上限 {MAX_VINYL_GROUP_LAYERS}，无法注入。",
                  f"Error: {layer_count} valid layers exceeds the FH6 vinyl group limit of {MAX_VINYL_GROUP_LAYERS}. Injection cancelled."))
        return

    ui.log(tr("[3/3] 扫描可写入的彩绘纹饰分组...", "[3/3] Scanning writable vinyl groups..."))
    target_groups = gamesave.get_target_layer_groups(containers_root)
    if not target_groups:
        ui.log(tr("未找到任何可用彩绘纹饰分组，请先在游戏内创建！",
                  "No available vinyl groups found. Create one in the game first."))
        return

    selected_group = pick_target_group(target_groups)
    if selected_group is None:
        return

    if not ui.ask_confirm(
            tr("确认注入", "Confirm injection"),
            tr(f"将覆盖以下分组：\n{selected_group['title']} - {selected_group['author']}\n确定继续吗？",
               f"The following vinyl group will be overwritten:\n{selected_group['title']} - {selected_group['author']}\nContinue?")):
        ui.log(tr("已取消", "Cancelled"))
        return

    ui.log(tr(f"准备注入到：{selected_group['title']}", f"Injecting into: {selected_group['title']}"))
    if gamesave.inject_cgroup(selected_group["path"], root_group):
        ui.log(tr("注入完成！请回到游戏打开该彩绘纹饰分组并重新保存，以刷新缩略图。",
                  "Injection complete. Open this vinyl group in the game and save it again to refresh its thumbnail."))


# SVG export

def workflow_export_svg():
    ui.log(tr("\n[1/3] 正在定位当前账户存档...", "\n[1/3] Locating the current account save..."))
    _, _, containers_root = gamesave.choose_containers_root()
    if not containers_root:
        return

    ui.log(tr("[2/3] 扫描可导出的彩绘纹饰分组...", "[2/3] Scanning exportable vinyl groups..."))
    target_groups = gamesave.get_target_layer_groups(containers_root)
    if not target_groups:
        ui.log(tr("未找到任何可导出的彩绘纹饰分组", "No exportable vinyl groups found"))
        return

    selected_group = pick_target_group(target_groups)
    if selected_group is None:
        return

    safe_title = re.sub(r'[\\/:*?"<>|]+', '_', selected_group['title']).strip() or "Exported_Forza_VinylGroup"
    try:
        exported_root = cgroup_codec.decode_cgroup_payload(cgroup_codec.unwrap_cgroup_file(selected_group["path"]))
        layer_count = count_shapes(exported_root)
    except Exception as e:
        ui.log(tr(f"读取图层数量失败：{e}", f"Failed to count layers: {e}"))
        return

    save_path = ui.ask_save_file(
        title=tr("保存导出的 Inkscape SVG", "Save exported Inkscape SVG"),
        filetypes=[("SVG", "*.svg")],
        initialfile=f"{safe_title}.{layer_count}.svg",
    )
    if not save_path:
        ui.log(tr("已取消", "Cancelled"))
        return

    ui.log(tr("[3/3] 正在导出 SVG...", "[3/3] Exporting SVG..."))
    try:
        svg_codec.export_cgroup_to_svg(selected_group["path"], save_path)
    except Exception as e:
        ui.log(tr(f"导出失败：{e}", f"Export failed: {e}"))
        return
    ui.log(tr(f"导出完成：\n  {os.path.normpath(save_path)}", f"Export complete:\n  {os.path.normpath(save_path)}"))


# JSON helpers

def json_shape_is_transparent(shape):
    color = shape.get("color", [])
    return len(color) >= 4 and color[3] == 0


def json_shape_is_at_or_below_opacity(shape, threshold):
    color = shape.get("color", [])
    if len(color) < 4:
        return False
    try:
        opacity = max(0, min(255, int(color[3])))
    except (TypeError, ValueError):
        return False
    return opacity <= threshold

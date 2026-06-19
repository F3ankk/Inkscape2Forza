import xml.etree.ElementTree as ET
import math
import re
import struct
import zlib
import os
import shutil
import zipfile
import datetime
import glob
import sys
import json
import tkinter as tk
from tkinter import filedialog

# config
ANCHOR_BYTES = b"\x00\x02\x66\x00"

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def quantize_alpha(a):
    if a >= 255: return 255
    quantized = int(round(a / 3.0) * 3)
    if quantized < 2: return 2
    return quantized

def parse_color(elem):
    r, g, b, a = 0, 0, 0, 255 
    style_str = elem.get('style', '')
    fill_match = re.search(r'fill:\s*#([0-9a-fA-F]{6})', style_str)
    if not fill_match:
        fill_attr = elem.get('fill', '')
        fill_match = re.search(r'#([0-9a-fA-F]{6})\b', fill_attr)
        
    if fill_match:
        hex_color = fill_match.group(1)
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        
    raw_a = 255.0
    opacity_match = re.search(r'(?:fill-)?opacity:\s*([0-9.]+)', style_str)
    if opacity_match:
        raw_a = float(opacity_match.group(1)) * 255.0
    else:
        op_attr = elem.get('opacity') or elem.get('fill-opacity')
        if op_attr:
            raw_a = float(op_attr) * 255.0
            
    a = quantize_alpha(raw_a)
    return r, g, b, a

def parse_transform(transform_str):
    current_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not transform_str: return current_matrix
        
    def mult_matrix(M1, M2):
        a1, b1, c1, d1, e1, f1 = M1
        a2, b2, c2, d2, e2, f2 = M2
        return (a1*a2+c1*b2, b1*a2+d1*b2, a1*c2+c1*d2, b1*c2+d1*d2, a1*e2+c1*f2+e1, b1*e2+d1*f2+f1)
        
    for cmd, args in re.findall(r'([a-zA-Z]+)\s*\(([^)]+)\)', transform_str):
        vals = [float(x) for x in args.replace(',', ' ').split()]
        if not vals: continue
        if cmd == 'matrix' and len(vals) == 6: m = tuple(vals)
        elif cmd == 'translate': m = (1.0, 0.0, 0.0, 1.0, vals[0], vals[1] if len(vals)>1 else 0.0)
        elif cmd == 'scale': m = (vals[0], 0.0, 0.0, vals[1] if len(vals)>1 else vals[0], 0.0, 0.0)
        elif cmd == 'rotate':
            a = math.radians(vals[0])
            ca, sa = math.cos(a), math.sin(a)
            if len(vals) >= 3:
                cx, cy = vals[1], vals[2]
                m = (ca, sa, -sa, ca, cx - cx*ca + cy*sa, cy - cx*sa - cy*ca)
            else:
                m = (ca, sa, -sa, ca, 0.0, 0.0)
        elif cmd == 'skewX': m = (1.0, 0.0, math.tan(math.radians(vals[0])), 1.0, 0.0, 0.0)
        elif cmd == 'skewY': m = (1.0, math.tan(math.radians(vals[0])), 0.0, 1.0, 0.0, 0.0)
        else: continue
        current_matrix = mult_matrix(current_matrix, m)
    return current_matrix

def decompose_matrix(a, b, c, d, e, f, min_x, min_y, canvas_w, canvas_h):
    real_svg_cx = a * (-min_x) + c * (-min_y) + e
    real_svg_cy = b * (-min_x) + d * (-min_y) + f
    tx = real_svg_cx - (canvas_w / 2.0)
    ty = (canvas_h / 2.0) - real_svg_cy
    A, B, C, D = a, -b, -c, d
    sx = math.sqrt(A*A + B*B)
    if sx < 1e-6: return tx, ty, 0, 0, 0, 0
    rot_rad = math.atan2(B, A)
    rot_deg = math.degrees(rot_rad) % 360.0
    sy = -C * math.sin(rot_rad) + D * math.cos(rot_rad)
    skew = (C * math.cos(rot_rad) + D * math.sin(rot_rad)) / sy if abs(sy) > 1e-6 else 0.0
    return tx, ty, sx, sy, rot_deg, skew

def build_layer_bytes(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a, is_masked_by_prev=False):
    shape_id = (shape_word << 16) | 0x0200
    if is_masked_by_prev: shape_id |= 0x00000001
    return struct.pack('<IffffffBBBB', shape_id, rot, tx, ty, sx, sy, skew, b, g, r, a)

def process_svg(svg_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()
    
    canvas_w = float(root.get('width', '1920').replace('px', '').strip())
    canvas_h = float(root.get('height', '1080').replace('px', '').strip())
    
    symbol_dict, pattern_dict = {}, {}
    for elem in root.iter():
        if elem.tag.endswith('symbol'):
            symbol_id = elem.get('id')
            viewbox_str = elem.get('viewBox')
            if symbol_id and viewbox_str:
                vb = viewbox_str.split()
                if len(vb) == 4: symbol_dict[f"#{symbol_id}"] = (float(vb[0]), float(vb[1]))
        if elem.tag.endswith('pattern'):
            pattern_id = elem.get('id')
            href = elem.get('{http://www.w3.org/1999/xlink}href') or elem.get('href', '')
            if pattern_id and href: pattern_dict[f"#{pattern_id}"] = href

    layers_bin_list, prev_was_mask, total_fh6_nodes = [], False, 0
    
    for elem in root.iter():
        if not elem.tag.endswith('use'): continue
        href = elem.get('{http://www.w3.org/1999/xlink}href') or elem.get('href', '')
        match = re.search(r'fh6_t(\d+)_i(\d+)_w(\d+)', href)
        if not match: continue
            
        total_fh6_nodes += 1
        shape_word = int(match.group(3))
        
        elem_id, style_str, fill_attr = elem.get('id', '').lower(), elem.get('style', '').lower(), elem.get('fill', '').lower()
        url_match = re.search(r'url\((\#[^)]+)\)', style_str) or re.search(r'url\((\#[^)]+)\)', fill_attr)
        resolved_href = pattern_dict.get(url_match.group(1), '').lower() if url_match else ""
        
        is_current_mask = (
            elem_id.startswith('mask') or 
            'destination-out' in style_str or 
            'mask_indicator' in resolved_href or
            (url_match and 'mask_indicator' in url_match.group(1).lower())
        )
        if (('fill:none' in style_str.replace(' ', '') or fill_attr == 'none') or 
            ('display:none' in style_str.replace(' ', '') or elem.get('display', '').lower() == 'none')) and not is_current_mask:
            continue
        
        r, g, b, a_val = parse_color(elem)
        if is_current_mask: r, g, b = 255, 255, 255
            
        transform_str = elem.get('transform', '')
        use_x, use_y = float(elem.get('x', '0')), float(elem.get('y', '0'))
        
        ma, mb, mc, md, me, mf = parse_transform(transform_str)
        min_x, min_y = symbol_dict.get(href, (0.0, 0.0))
        
        me, mf = me + ma * use_x + mc * use_y, mf + mb * use_x + md * use_y
        tx, ty, sx, sy, rot, skew = decompose_matrix(ma, mb, mc, md, me, mf, min_x, min_y, canvas_w, canvas_h)
        
        layers_bin_list.append(build_layer_bytes(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a_val, prev_was_mask))
        prev_was_mask = is_current_mask
        
    return layers_bin_list, prev_was_mask, total_fh6_nodes

def read_u32(data, offset): return struct.unpack_from("<I", data, offset)[0], offset + 4
def read_utf16(data, offset, char_count):
    return data[offset:offset + char_count*2].decode("utf-16le", errors="replace").strip("\x00"), offset + char_count*2

def parse_header(header_path):
    try:
        data = open(header_path, 'rb').read()
        if len(data) < 8: return "Error", "Error"
        magic, off = read_u32(data, 0)
        if magic != 7: return "Invalid Magic", "Unknown"
        
        t_len, off = read_u32(data, off)
        title, off = read_utf16(data, off, t_len)
        
        d_len, off = read_u32(data, off)
        _, off = read_utf16(data, off, d_len)
        
        off += 28
        
        a_len, off = read_u32(data, off)
        author, off = read_utf16(data, off, a_len)
        
        return title.strip() or "Untitled", author.strip() or "Unknown"
    except Exception:
        return "Unknown", "Unknown"

# ================= UI & Workflow Helpers =================

def select_folder(title):
    root = tk.Tk()
    root.withdraw()
    folder_path = filedialog.askdirectory(title=title, initialdir=os.getcwd())
    root.destroy()
    return folder_path

def select_file(title, filetypes):
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title=title, filetypes=filetypes, initialdir=os.getcwd())
    root.destroy()
    return file_path

def save_file(title, filetypes, initialfile):
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.asksaveasfilename(
        title=title, 
        filetypes=filetypes, 
        initialfile=initialfile, 
        initialdir=os.getcwd(),
        defaultextension=".svg"
    )
    root.destroy()
    return file_path

def create_backup(u_dir, gamesave_dir):
    backup_dir = os.path.join(os.path.dirname(gamesave_dir), "Backup")
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    backup_name = f"backup_{timestamp}"
    backup_path_base = os.path.normpath(os.path.join(backup_dir, backup_name))
    
    print("正在打包备份... / Processing backup...")
    shutil.make_archive(backup_path_base, 'zip', u_dir)
    print(f"备份完成 / Backup complete: {backup_path_base}.zip")

def get_target_layer_groups(containers_root):
    folders = glob.glob(os.path.join(containers_root, "LayerGroup_0000_*"))
    valid_groups = []
    
    for folder in sorted(folders):
        c_group_path = os.path.join(folder, "C_group")
        header_path = os.path.join(folder, "header")
        
        if os.path.exists(c_group_path) and os.path.exists(header_path):
            title, author = parse_header(header_path)
            valid_groups.append({
                "path": c_group_path,
                "folder_name": os.path.basename(folder),
                "title": title,
                "author": author
            })
    return valid_groups

def inject_cgroup(target_cgroup, layers_bin_list, last_was_mask):
    with open(target_cgroup, 'rb') as f:
        cgroup_data = f.read()
        
    zstream = cgroup_data[8:]
    try:
        decomp_data = zlib.decompress(zstream)
    except Exception as e:
        print(f"读取彩绘纹饰分组失败 / Failed to read vinyl group: {e}")
        return False
        
    idx = decomp_data.find(ANCHOR_BYTES)
    if idx == -1:
        print("定位第一层图形失败，该彩绘纹饰分组可能不符合注入要求。 / Failed to locate first layer graphics, the vinyl group may not meet injection requirements.")
        return False
        
    original_layer_count = (len(decomp_data) - idx - 2) // 32
    
    if len(layers_bin_list) != original_layer_count:
        print(f"图层数量不匹配！ / Layer count mismatch!")
        print(f"   SVG 有效图层数 / Valid SVG layers: {len(layers_bin_list)}")
        print(f"   绘纹饰分组图层数 / vinyl group layers: {original_layer_count}")
        print("为了您的存档安全，请选择一个图层数量一致的彩绘纹饰分组。 / For safety, please select a vinyl group with a matching layer count.")
        return False
    
    header_data = decomp_data[:idx]
    footer_data = bytearray(decomp_data[idx + original_layer_count * 32:])
    
    if len(footer_data) > 0:
        if last_was_mask:
            footer_data[0] |= 0x01
        else:
            footer_data[0] &= ~0x01
            
    new_decomp_data = header_data + b"".join(layers_bin_list) + bytes(footer_data)
    
    compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=zlib.MAX_WBITS, memLevel=8, strategy=zlib.Z_DEFAULT_STRATEGY)
    new_zstream = compressor.compress(new_decomp_data) + compressor.flush()
    new_header = struct.pack('<II', len(new_zstream), len(new_decomp_data))
    
    temp_cgroup = target_cgroup + ".tmp"
    with open(temp_cgroup, 'wb') as f:
        f.write(new_header + new_zstream)
        
    try:
        shutil.copystat(target_cgroup, temp_cgroup)
    except: pass
    os.replace(temp_cgroup, target_cgroup)
    
    print(f"注入成功 / Injection successful")
    return True

# ================= Workflows =================

def workflow_create_template():
    print("\n准备建立新的空白 SVG 模板... / Preparing to create a new blank SVG template...")
    template_path = get_resource_path("inkscape_template.svg.tmp")
    
    if not os.path.exists(template_path):
        print(f"错误: 找不到内部模板文件 / Error: Cannot find internal template file.")
        print(f"Path searched: {template_path}")
        return
        
    save_path = save_file(
        title="保存空白模板 / Save Blank Template", 
        filetypes=[("SVG", "*.svg")], 
        initialfile="My_Forza_VinylGroup.svg"
    )
    
    if not save_path:
        print("已取消 / Cancelled")
        return
        
    try:
        shutil.copy2(template_path, save_path)
        print(f"模板已成功保存至 / Template successfully saved to:\n  {os.path.normpath(save_path)}")
    except Exception as e:
        print(f"保存失败 / Failed to save: {e}")

def workflow_geometrize_to_svg():
    print("\n[1/3] 请选择 Geometrize 导出的 JSON 文件... / Please select Geometrize JSON file...")
    json_path = select_file("Geometrize JSON", [("JSON 文件", "*.json")])
    if not json_path:
        print("已取消 / Cancelled")
        return
        
    print("[2/3] 正在加载内部 SVG 模板进行合成... / Loading internal SVG template for synthesis...")
    template_path = get_resource_path("inkscape_template.svg.tmp")
    if not os.path.exists(template_path):
        print(f"错误: 找不到内部模板文件 / Error: Cannot find internal template file.")
        return
        
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            geo_data = json.load(f)
            
        shapes = geo_data.get("shapes", geo_data if isinstance(geo_data, list) else [])
        if isinstance(geo_data, dict) and "shapes" not in geo_data:
            shapes = []
            
        if not shapes:
            print("错误: JSON 文件中没有找到有效的形状数据 / Error: No valid shapes found in JSON.")
            return
            
    except Exception as e:
        print(f"读取 JSON 失败 / Failed to read JSON: {e}")
        return
        
    print("[3/3] 请选择合并后 SVG 文件的保存位置... / Please select save location for merged SVG...")
    save_path = save_file(
        title="保存由 Geometrize 生成的 SVG / Save generated SVG", 
        filetypes=[("SVG 文件", "*.svg")], 
        initialfile="Geometrize_Livery.svg"
    )
    if not save_path:
        print("已取消 / Cancelled")
        return

    try:
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        ET.register_namespace('inkscape', 'http://www.inkscape.org/namespaces/inkscape')
        ET.register_namespace('sodipodi', 'http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd')
        ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
        
        tree = ET.parse(template_path)
        root = tree.getroot()
        
        canvas_w = float(root.get('width', '1920').replace('px', '').strip())
        canvas_h = float(root.get('height', '1080').replace('px', '').strip())
        
        symbol_dict = {}
        for elem in root.iter():
            if elem.tag.endswith('symbol'):
                symbol_id = elem.get('id')
                viewbox_str = elem.get('viewBox')
                if symbol_id and viewbox_str:
                    vb = viewbox_str.split()
                    if len(vb) == 4: 
                        symbol_dict[f"#{symbol_id}"] = (float(vb[0]), float(vb[1]))
                        
        rect_href, circle_href = None, None
        for k in symbol_dict.keys():
            if k.endswith('_w101'): rect_href = k
            elif k.endswith('_w102'): circle_href = k
            
        if not rect_href or not circle_href:
            print("错误: 模板库中找不到基础矩形(w101)或圆形(w102)的符号引用。 / Error: Cannot find base shape symbols in template.")
            return
            
        layer1 = root.find('.//{http://www.w3.org/2000/svg}g[@id="layer1"]')
        target_container = layer1 if layer1 is not None else root
        
        def append_shape(svg_cx, svg_cy, sx, sy, rot_deg, fill_val, opacity_val, href, node_id):
            min_x, min_y = symbol_dict.get(href, (0.0, 0.0))
            rad = math.radians(rot_deg)
            cos_r, sin_r = math.cos(rad), math.sin(rad)
            
            ma = sx * cos_r
            mb = -sx * sin_r
            mc = sy * sin_r
            md = sy * cos_r
            
            me = svg_cx + ma * min_x + mc * min_y
            mf = svg_cy + mb * min_x + md * min_y
            
            use_elem = ET.Element('{http://www.w3.org/2000/svg}use')
            use_elem.set('{http://www.w3.org/1999/xlink}href', href)
            use_elem.set('x', '0')
            use_elem.set('y', '0')
            use_elem.set('transform', f"matrix({ma:.6f},{mb:.6f},{mc:.6f},{md:.6f},{me:.6f},{mf:.6f})")
            use_elem.set('style', f"fill:{fill_val}; opacity:{opacity_val};")
            use_elem.set('id', node_id)
            target_container.append(use_elem)

        geo_w, geo_h = 2048.0, 2048.0
        for shape in shapes:
            type_code = shape.get("type")
            color = shape.get("color", [])
            data = shape.get("data", [])
            if type_code == 1 and len(color) >= 4 and color[3] == 0 and len(data) >= 4:
                geo_w = float(data[2])
                geo_h = float(data[3])
                break

        min_ext_x, max_ext_x = float('inf'), float('-inf')
        min_ext_y, max_ext_y = float('inf'), float('-inf')
        has_valid_shapes = False
        
        for shape in shapes:
            type_code = shape.get("type")
            data = shape.get("data", [])
            if len(data) >= 4 and type_code in (1, 16):
                has_valid_shapes = True
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
                
        if not has_valid_shapes:
            min_ext_x, max_ext_x, min_ext_y, max_ext_y = 0.0, 0.0, 0.0, 0.0

        valid_count = 0
        deferred_masks = []
        
        for idx, shape in enumerate(shapes):
            type_code = shape.get("type")
            
            if type_code not in (1, 16):
                print(f"跳过不支持的图形类型 (index {idx}): type {type_code}")
                continue
                
            data = shape.get("data", [])
            if len(data) < 4:
                continue
                
            color = shape.get("color", [255, 255, 255, 255])
            if len(color) < 4: color.append(255)
            r, g, b, a = [max(0, min(255, int(v))) for v in color]
            
            if type_code == 1:
                geo_cx = float(data[0]) + float(data[2]) / 2.0
                geo_cy = float(data[1]) + float(data[3]) / 2.0
                sx = float(data[2]) / 127.0
                sy = float(data[3]) / 127.0
                rot_deg = float(data[4]) if len(data) >= 5 else 0.0
                href = rect_href
            else: # type == 16
                geo_cx = float(data[0])
                geo_cy = float(data[1])
                sx = float(data[2]) / 63.0
                sy = float(data[3]) / 63.0
                rot_deg = (360.0 - float(data[4])) % 360.0 if len(data) >= 5 else 0.0
                href = circle_href
                
            svg_cx = geo_cx + (canvas_w / 2.0 - geo_w / 2.0)
            svg_cy = geo_cy + (canvas_h / 2.0 - geo_h / 2.0)
            
            if type_code == 1 and a == 0:
                hw = float(data[2]) / 2.0
                hh = float(data[3]) / 2.0
                
                svg_min_ext_x = min_ext_x + (canvas_w / 2.0 - geo_w / 2.0)
                svg_max_ext_x = max_ext_x + (canvas_w / 2.0 - geo_w / 2.0)
                svg_min_ext_y = min_ext_y + (canvas_h / 2.0 - geo_h / 2.0)
                svg_max_ext_y = max_ext_y + (canvas_h / 2.0 - geo_h / 2.0)
                
                T_top = max(10.0, (svg_cy - hh) - svg_min_ext_y + 20.0)
                T_bottom = max(10.0, svg_max_ext_y - (svg_cy + hh) + 20.0)
                T_left = max(10.0, (svg_cx - hw) - svg_min_ext_x + 20.0)
                T_right = max(10.0, svg_max_ext_x - (svg_cx + hw) + 20.0)
                
                m_w = 2*hw + T_left + T_right
                m_h = T_top
                deferred_masks.append((svg_cx + (T_right - T_left) / 2.0, svg_cy - hh - m_h / 2.0, m_w / 127.0, m_h / 127.0, 0.0, "url(#mask_indicator_dark)", 1.0, rect_href, f"mask_geo_{idx}_top"))
                
                m_h = T_bottom
                deferred_masks.append((svg_cx + (T_right - T_left) / 2.0, svg_cy + hh + m_h / 2.0, m_w / 127.0, m_h / 127.0, 0.0, "url(#mask_indicator_dark)", 1.0, rect_href, f"mask_geo_{idx}_bottom"))
                
                m_w = T_left
                m_h = 2*hh
                deferred_masks.append((svg_cx - hw - m_w / 2.0, svg_cy, m_w / 127.0, m_h / 127.0, 0.0, "url(#mask_indicator_dark)", 1.0, rect_href, f"mask_geo_{idx}_left"))
                
                m_w = T_right
                deferred_masks.append((svg_cx + hw + m_w / 2.0, svg_cy, m_w / 127.0, m_h / 127.0, 0.0, "url(#mask_indicator_dark)", 1.0, rect_href, f"mask_geo_{idx}_right"))
                
                valid_count += 4
                continue
                
            fill_hex = f"#{r:02x}{g:02x}{b:02x}"
            opacity = round(a / 255.0, 4)
                
            append_shape(svg_cx, svg_cy, sx, sy, rot_deg, fill_hex, opacity, href, f"geo_shape_{idx}")
            valid_count += 1
            
        for m_args in deferred_masks:
            append_shape(*m_args)
            
        tree.write(save_path, encoding="utf-8", xml_declaration=True)
        print(f"\n🎉 完美合成！成功写入 {valid_count} 个图形。文件已保存在:\n  {os.path.normpath(save_path)}")
        print("💡 提示: 接下来你可以打开生成的 SVG 进行手动微调，确认无误后使用功能 3 将其注入游戏存档！")
        
    except Exception as e:
        print(f"❌ 转换过程中发生错误 / Conversion error: {e}")

def workflow_inject_svg():
    print("\n[1/4] 请选择您的 GameSave 文件夹... / Please select your GameSave folder...")
    gamesave_dir = select_folder("GameSave")
    if not gamesave_dir:
        print("已取消 / Cancelled")
        return
        
    pgs_dir = os.path.join(gamesave_dir, "pgs")
    if not os.path.exists(pgs_dir):
        print("这不是有效的存档文件夹 / This is not a valid GameSave folder")
        return
        
    u_folders = [f for f in os.listdir(pgs_dir) if f.startswith("u_") and os.path.isdir(os.path.join(pgs_dir, f))]
    if not u_folders:
        print("未找到玩家数据 / No player data found")
        return
        
    u_dir = os.path.join(pgs_dir, u_folders[0])
    containers_root = os.path.join(u_dir, "current", "ContainersRoot")
    
    if not os.path.exists(containers_root):
        print("未找到数据根目录 / No root directory found")
        return

    print(f"已定位到存档 / GameSave: {os.path.normpath(u_dir)}")

    print("[2/4] 为了您的数据安全，建议操作前备份存档。是否进行？ / For your data safety, it's recommended to backup before proceeding. Do you want to backup?")
    backup_choice = input("1. 备份 / Backup\n2. 不备份 / Don't backup\n输入 q 退出程序 / 'q' to quit\n选择 / Choose: ").strip().lower()
    
    if backup_choice in ('q', 'c', 'exit', 'quit'):
        print("\n退出程序 / Exiting program...")
        sys.exit(0)
    elif backup_choice == "1":
        create_backup(u_dir, gamesave_dir)
    else:
        print("已跳过 / Skipped")

    print("[3/4] 请选择要注入的 Inkscape SVG 文件... / Please select your Inkscape SVG file to inject...")
    svg_path = select_file("Inkscape SVG", [("SVG", "*.svg")])
    if not svg_path:
        print("已取消 / Cancelled")
        return
        
    print(f"正在解析 SVG / Parsing SVG: {os.path.basename(svg_path)}")
    try:
        layers_bin_list, prev_was_mask, total_nodes = process_svg(svg_path)
        print(f"识别到 {total_nodes} 个元素，过滤后有效图层数：{len(layers_bin_list)} / Found {total_nodes} elements, {len(layers_bin_list)} valid layers after filtering")
    except Exception as e:
        print(f"解析失败 / Failed to parse SVG: {e}")
        return

    print("[4/4] 扫描可写入的彩绘纹饰分组... / Scanning for writable vinyl groups...")
    target_groups = get_target_layer_groups(containers_root)
    
    if not target_groups:
        print("未找到任何可用彩绘纹饰分组，请先在游戏内创建！ / No available vinyl groups found, please create one in the game first!")
        return

    while True:
        print("\n请选择要被覆盖注入的彩绘纹饰分组 / Please select the vinyl group to be overwritten:")
        print("-" * 10)
        for i, group in enumerate(target_groups):
            print(f"{i+1}. {group['title']} - {group['author']}")
        print("-" * 10)
        
        choice = input("请输入对应的序号或输入 q 退出程序 / Choose or 'q' to quit: ").strip().lower()
        if choice in ('q', 'c', 'exit', 'quit'):
            print("\n退出程序 / Exiting program...")
            sys.exit(0)
            
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(target_groups):
                selected_group = target_groups[choice_idx]
                target_cgroup_path = selected_group["path"]
                
                print(f"准备注入到 / Inject into: {selected_group['title']}")
                if inject_cgroup(target_cgroup_path, layers_bin_list, prev_was_mask):
                    print("注入完成！请回到游戏，打开该彩绘纹饰分组，解组全部图层并重新保存 / Injection complete! Please return to the game, open the vinyl group, ungroup all layers and save again.")
                    break
                else:
                    print("将返回彩绘纹饰分组选择列表... / Returning to vinyl group selection...")
            else:
                print("输入无效 / Invalid input")
        except ValueError:
            print("输入无效 / Invalid input")

def main():
    while True:
        print("\n=== 请选择你的操作 / Please select your operation ===")
        print("1. 建立新的空白 Inkscape SVG 模板 / Create new blank Inkscape SVG template")
        print("2. 从 Geometrize JSON 建立 Inkscape SVG 模板 / Create Inkscape SVG from Geometrize JSON")
        print("3. 将 Inkscape SVG 导入到 FH6 存档 / Inject Inkscape SVG into FH6 save")
        print("Q. 退出 / Quit")
        
        choice = input("\n输入对应序号 / Enter selection: ").strip().lower()
        
        if choice == '1':
            workflow_create_template()
        elif choice == '2':
            workflow_geometrize_to_svg()
        elif choice == '3':
            workflow_inject_svg()
        elif choice in ('q', 'c', 'exit', 'quit'):
            print("\n退出程序 / Exiting program...")
            sys.exit(0)
        else:
            print("\n无效输入，请重新选择 / Invalid input, please try again.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已强制取消 / Force cancelled")
        sys.exit(0)
    except SystemExit:
        pass
    except Exception as e:
        print(f"\n发生未捕获的错误 / Uncaught error: {e}")
        input("\n按回车键退出... / Press Enter to exit...")
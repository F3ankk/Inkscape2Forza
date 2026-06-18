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
import tkinter as tk
from tkinter import filedialog

# config
ANCHOR_BYTES = b"\x00\x02\x66\x00"

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
        
        is_current_mask = elem_id.startswith('mask') or 'destination-out' in style_str or 'mask_indicator' in resolved_href
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

def select_folder(title):
    root = tk.Tk()
    root.withdraw()
    folder_path = filedialog.askdirectory(title=title)
    return folder_path

def select_file(title, filetypes):
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title=title, filetypes=filetypes)
    return file_path

def create_backup(u_dir, gamesave_dir):
    backup_dir = os.path.join(os.path.dirname(gamesave_dir), "Backup")
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    backup_name = f"backup_{timestamp}"
    backup_path_base = os.path.normpath(os.path.join(backup_dir, backup_name))
    
    print("正在打包备份...")
    shutil.make_archive(backup_path_base, 'zip', u_dir)
    print(f"备份完成: {backup_path_base}.zip")

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
        print(f"读取彩绘纹饰分组失败: {e}")
        return False
        
    idx = decomp_data.find(ANCHOR_BYTES)
    if idx == -1:
        print("定位第一层图形失败，该彩绘纹饰分组可能不符合注入要求。")
        return False
        
    original_layer_count = (len(decomp_data) - idx - 2) // 32
    
    if len(layers_bin_list) != original_layer_count:
        print(f"图层数量不匹配！")
        print(f"   SVG 有效图层数 : {len(layers_bin_list)}")
        print(f"   存档图层数 : {original_layer_count}")
        print("为了您的存档安全，请选择一个图层数量一致的彩绘纹饰分组。")
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
    
    print(f"注入成功")
    return True

def main():
    print("")
    
    print("[1/4] 请选择您的 GameSave 文件夹...")
    gamesave_dir = select_folder("GameSave")
    if not gamesave_dir:
        print("已取消")
        return
        
    pgs_dir = os.path.join(gamesave_dir, "pgs")
    if not os.path.exists(pgs_dir):
        print("这不是有效的存档文件夹")
        return
        
    # search for player data
    u_folders = [f for f in os.listdir(pgs_dir) if f.startswith("u_") and os.path.isdir(os.path.join(pgs_dir, f))]
    if not u_folders:
        print("未找到玩家数据")
        return
        
    u_dir = os.path.join(pgs_dir, u_folders[0])
    containers_root = os.path.join(u_dir, "current", "ContainersRoot")
    
    if not os.path.exists(containers_root):
        print("未找到数据根目录")
        return

    # 打印时统一规范化路径显示
    print(f"已定位到存档: {os.path.normpath(u_dir)}")

    # backup
    print("[2/4] 为了您的数据安全，建议操作前备份存档。是否进行？")
    backup_choice = input("1. 备份\n2. 不备份\n请输入数字选择: ").strip()
    
    if backup_choice == "1":
        create_backup(u_dir, gamesave_dir)
    else:
        print("已跳过")

    print("[3/4] 请选择要注入的 Inkscape SVG 文件...")
    svg_path = select_file("Inkscape SVG", [("SVG 文件", "*.svg")])
    if not svg_path:
        print("已取消")
        return
        
    print(f"正在解析 SVG: {os.path.basename(svg_path)}")
    try:
        layers_bin_list, prev_was_mask, total_nodes = process_svg(svg_path)
        print(f"识别到 {total_nodes} 个元素，过滤后有效图层数：{len(layers_bin_list)}")
    except Exception as e:
        print(f"解析失败: {e}")
        return

    # gamesave injection
    print("[4/4] 扫描可写入的彩绘纹饰分组...")
    target_groups = get_target_layer_groups(containers_root)
    
    if not target_groups:
        print("未找到任何可用彩绘纹饰分组，请先在游戏内创建！")
        return

    while True:
        print("请选择要被覆盖注入的彩绘纹饰分组：")
        print("-" * 10)
        for i, group in enumerate(target_groups):
            print(f"{i+1}. {group['title']} - {group['author']}")
        print("-" * 10)
        print("输入 q 退出")
        
        choice = input("请输入对应的序号: ").strip()
        if choice.lower() == 'q':
            print("已退出")
            break
            
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(target_groups):
                selected_group = target_groups[choice_idx]
                target_cgroup_path = selected_group["path"]
                
                print(f"准备注入到: {selected_group['title']}")
                if inject_cgroup(target_cgroup_path, layers_bin_list, prev_was_mask):
                    print("注入完成！请回到游戏，打开该彩绘纹饰分组，解组全部图层并重新保存")
                    break
                else:
                    print("将返回存档选择列表...")
            else:
                print("输入无效")
        except ValueError:
            print("输入无效")

if __name__ == "__main__":
    main()
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
import subprocess
from copy import deepcopy
import tkinter as tk
from tkinter import filedialog
from dataclasses import dataclass, field

# config
ANCHOR_BYTES = b"\x00\x02\x66\x00"
DEFAULT_GAMESAVE_DIR = r"C:\XboxGames\GameSave"
MAX_VINYL_GROUP_LAYERS = 3000
_cached_gamesave_dir = None
_cached_general_dir = None
_has_prompted_backup = False
_symbol_library_cache = None
_pattern_library_cache = None

SVG_NS = 'http://www.w3.org/2000/svg'
XLINK_NS = 'http://www.w3.org/1999/xlink'
INKSCAPE_NS = 'http://www.inkscape.org/namespaces/inkscape'
SODIPODI_NS = 'http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd'

@dataclass
class ShapeNode:
    shape_word: int
    rot: float
    tx: float
    ty: float
    sx: float
    sy: float
    skew: float
    r: int
    g: int
    b: int
    a: int
    is_mask: bool = False

@dataclass
class GroupNode:
    children: list = field(default_factory=list)
    is_mask_group: bool = False
    name: str = ""
    tx: float = 0.0
    ty: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    rot: float = 0.0

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def write_inkscape_svg(tree, svg_path):
    """Write a readable SVG using Inkscape's conventional namespace prefixes."""
    ET.register_namespace('', SVG_NS)
    ET.register_namespace('inkscape', INKSCAPE_NS)
    ET.register_namespace('sodipodi', SODIPODI_NS)
    ET.register_namespace('xlink', XLINK_NS)
    root = tree.getroot()
    root.set(f'{{{SODIPODI_NS}}}docname', os.path.basename(svg_path))
    ET.indent(tree, space='  ')
    tree.write(svg_path, encoding='utf-8', xml_declaration=True, short_empty_elements=True)

def create_inkscape_document():
    root = ET.Element(f'{{{SVG_NS}}}svg', {
        'width': '1920', 'height': '1080', 'viewBox': '0 0 1920 1080',
        'version': '1.1', 'id': 'svg1402',
    })
    root.set(f'{{{INKSCAPE_NS}}}version', '1.4')
    ET.SubElement(root, f'{{{SODIPODI_NS}}}namedview', {
        'id': 'namedview1402', 'pagecolor': '#505050',
        f'{{{INKSCAPE_NS}}}pageopacity': '0',
        f'{{{INKSCAPE_NS}}}pagecheckerboard': '1',
    })
    defs = ET.SubElement(root, f'{{{SVG_NS}}}defs', {'id': 'defs1402'})
    # Keep shapes at SVG root level so generated artwork does not gain a
    # synthetic Inkscape layer that would become an extra FH6 subgroup.
    return ET.ElementTree(root), root, defs, root

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
            
    a = max(0, min(255, int(round(raw_a))))
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

def mult_matrix(M1, M2):
    a1, b1, c1, d1, e1, f1 = M1
    a2, b2, c2, d2, e2, f2 = M2
    return (a1*a2+c1*b2, b1*a2+d1*b2, a1*c2+c1*d2, b1*c2+d1*d2, a1*e2+c1*f2+e1, b1*e2+d1*f2+f1)

def parse_svg_length(value, default):
    match = re.match(r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))', value or '')
    return float(match.group(1)) if match else default

def get_svg_canvas(root):
    viewbox = re.split(r'[\s,]+', root.get('viewBox', '').strip())
    if len(viewbox) == 4:
        try:
            canvas_x, canvas_y, canvas_w, canvas_h = map(float, viewbox)
            if canvas_w > 0 and canvas_h > 0:
                return canvas_x, canvas_y, canvas_w, canvas_h
        except ValueError:
            pass
    return 0.0, 0.0, parse_svg_length(root.get('width'), 1920.0), parse_svg_length(root.get('height'), 1080.0)

def decompose_matrix(a, b, c, d, e, f, min_x, min_y, canvas_x, canvas_y, canvas_w, canvas_h):
    real_svg_cx = a * (-min_x) + c * (-min_y) + e
    real_svg_cy = b * (-min_x) + d * (-min_y) + f
    scale_factor = min(1920.0 / canvas_w, 1080.0 / canvas_h)
    tx = (real_svg_cx - (canvas_x + canvas_w / 2.0)) * scale_factor
    ty = ((canvas_y + canvas_h / 2.0) - real_svg_cy) * scale_factor
    A, B, C, D = a, -b, -c, d
    sx = math.sqrt(A*A + B*B)
    if sx < 1e-6: return tx, ty, 0, 0, 0, 0
    rot_rad = math.atan2(B, A)
    rot_deg = math.degrees(rot_rad) % 360.0
    sy = -C * math.sin(rot_rad) + D * math.cos(rot_rad)
    skew = (C * math.cos(rot_rad) + D * math.sin(rot_rad)) / sy if abs(sy) > 1e-6 else 0.0
    return tx, ty, sx * scale_factor, sy * scale_factor, rot_deg, skew

def build_layer_bytes(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a, is_masked_by_prev=False):
    shape_id = (shape_word << 16) | 0x0200
    if is_masked_by_prev: shape_id |= 0x00000001
    return struct.pack('<IffffffBBBB', shape_id, rot, tx, ty, sx, sy, skew, b, g, r, a)

def get_href(elem):
    return elem.get(f'{{{XLINK_NS}}}href') or elem.get('href', '')

def get_local_name(elem):
    return elem.tag.rsplit('}', 1)[-1] if '}' in elem.tag else elem.tag

def parse_float_attr(elem, name, default=0.0):
    try:
        return float(elem.get(name, default))
    except (TypeError, ValueError):
        return default

def detect_mask_element(elem, pattern_dict):
    elem_id = elem.get('id', '').lower()
    style_str = elem.get('style', '').lower()
    fill_attr = elem.get('fill', '').lower()
    if elem.get('data-forza-mask-group') == '1':
        return True
    url_match = re.search(r'url\((\#[^)]+)\)', style_str) or re.search(r'url\((\#[^)]+)\)', fill_attr)
    resolved_href = pattern_dict.get(url_match.group(1), '').lower() if url_match else ""
    return (
        elem_id.startswith('mask') or
        'destination-out' in style_str or
        'mask_indicator' in resolved_href or
        (url_match and 'mask_indicator' in url_match.group(1).lower())
    )

def is_hidden_or_empty(elem, is_mask):
    style_str = elem.get('style', '').lower().replace(' ', '')
    fill_attr = elem.get('fill', '').lower()
    return (
        ('fill:none' in style_str or fill_attr == 'none') or
        ('display:none' in style_str or elem.get('display', '').lower() == 'none')
    ) and not is_mask

def collect_svg_defs(root):
    symbol_dict, pattern_dict = {}, {}
    for elem in root.iter():
        local = get_local_name(elem)
        if local == 'symbol':
            symbol_id = elem.get('id')
            viewbox_str = elem.get('viewBox')
            if symbol_id and viewbox_str:
                vb = viewbox_str.split()
                if len(vb) == 4:
                    symbol_dict[f"#{symbol_id}"] = (float(vb[0]), float(vb[1]))
        elif local == 'pattern':
            pattern_id = elem.get('id')
            href = get_href(elem)
            if pattern_id and href:
                pattern_dict[f"#{pattern_id}"] = href
    return symbol_dict, pattern_dict

def process_svg_tree(svg_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()
    
    canvas_x, canvas_y, canvas_w, canvas_h = get_svg_canvas(root)
    
    symbol_dict, pattern_dict = collect_svg_defs(root)
    total_fh6_nodes = 0

    def parse_children(parent, parent_matrix, inherited_mask=False):
        nonlocal total_fh6_nodes
        group = GroupNode(name=parent.get('id', ''), is_mask_group=inherited_mask)

        for elem in list(parent):
            local = get_local_name(elem)
            if local in ('defs', 'symbol', 'pattern', 'metadata', 'namedview'):
                continue

            elem_matrix = mult_matrix(parent_matrix, parse_transform(elem.get('transform', '')))

            if local == 'g':
                child_is_mask = inherited_mask or detect_mask_element(elem, pattern_dict)
                child_group = parse_children(elem, elem_matrix, child_is_mask)
                if child_group.children:
                    group.children.append(child_group)
                continue

            if local != 'use':
                continue

            href = get_href(elem)
            match = re.search(r'fh6_t(\d+)_i(\d+)_w(\d+)', href)
            if not match:
                continue

            total_fh6_nodes += 1
            is_current_mask = inherited_mask or detect_mask_element(elem, pattern_dict)
            if is_hidden_or_empty(elem, is_current_mask):
                continue

            shape_word = int(match.group(3))
            r, g, b, a_val = parse_color(elem)
            if is_current_mask:
                r, g, b = 255, 255, 255

            use_x, use_y = parse_float_attr(elem, 'x'), parse_float_attr(elem, 'y')
            ma, mb, mc, md, me, mf = elem_matrix
            me, mf = me + ma * use_x + mc * use_y, mf + mb * use_x + md * use_y
            min_x, min_y = symbol_dict.get(href, (0.0, 0.0))
            tx, ty, sx, sy, rot, skew = decompose_matrix(
                ma, mb, mc, md, me, mf, min_x, min_y,
                canvas_x, canvas_y, canvas_w, canvas_h
            )

            group.children.append(ShapeNode(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a_val, is_current_mask))

        return group

    root_group = parse_children(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), False)
    return root_group, total_fh6_nodes

def flatten_shapes(group):
    out = []
    for child in group.children:
        if isinstance(child, GroupNode):
            out.extend(flatten_shapes(child))
        else:
            out.append(child)
    return out

def process_svg(svg_path):
    root_group, total_fh6_nodes = process_svg_tree(svg_path)
    flat_shapes = flatten_shapes(root_group)
    layers_bin_list, prev_was_mask = [], False

    for shape in flat_shapes:
        layers_bin_list.append(build_layer_bytes(
            shape.shape_word, shape.rot, shape.tx, shape.ty, shape.sx, shape.sy,
            shape.skew, shape.r, shape.g, shape.b, shape.a, prev_was_mask
        ))
        prev_was_mask = shape.is_mask

    return layers_bin_list, prev_was_mask, total_fh6_nodes, root_group

def process_svg_old(svg_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()
    
    canvas_x, canvas_y, canvas_w, canvas_h = get_svg_canvas(root)
    
    symbol_dict, pattern_dict = collect_svg_defs(root)

    layers_bin_list, prev_was_mask, total_fh6_nodes = [], False, 0
    
    for elem in root.iter():
        if not elem.tag.endswith('use'): continue
        href = get_href(elem)
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
        tx, ty, sx, sy, rot, skew = decompose_matrix(
            ma, mb, mc, md, me, mf, min_x, min_y,
            canvas_x, canvas_y, canvas_w, canvas_h
        )
        
        layers_bin_list.append(build_layer_bytes(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a_val, prev_was_mask))
        prev_was_mask = is_current_mask
        
    return layers_bin_list, prev_was_mask, total_fh6_nodes

def child_bitmap(children):
    blocks = (len(children) + 7) // 8
    bitmap = bytearray(blocks)
    for idx, child in enumerate(children):
        if isinstance(child, GroupNode):
            bitmap[idx // 8] |= (1 << (idx % 8))
    return bytes(bitmap)

def encode_shape_node(shape, offset_x=0.0, offset_y=0.0, mark_previous_mask=False, inherited_mask=False, bare=False):
    if bare:
        return struct.pack(
            '<BHffffffBBBB',
            0x02, shape.shape_word, shape.rot, shape.tx - offset_x, shape.ty - offset_y,
            shape.sx, shape.sy, shape.skew, shape.b, shape.g, shape.r, shape.a
        )
    return build_layer_bytes(
        shape.shape_word, shape.rot, shape.tx - offset_x, shape.ty - offset_y, shape.sx, shape.sy,
        shape.skew, shape.r, shape.g, shape.b, shape.a, mark_previous_mask or inherited_mask
    )

def shape_corners(shape):
    hw, hy = 64.0, 64.0
    rad = math.radians(shape.rot)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    out = []
    for x, y in ((-hw, -hy), (hw, -hy), (hw, hy), (-hw, hy)):
        # The game applies scale after the horizontal shear: x' = sx*x + skew*sy*y.
        xs = shape.sx * x + shape.skew * shape.sy * y
        ys = y * shape.sy
        out.append((shape.tx + cos_r * xs - sin_r * ys, shape.ty + sin_r * xs + cos_r * ys))
    return out

def collect_shape_nodes(node, out):
    for child in node.children:
        if isinstance(child, GroupNode):
            collect_shape_nodes(child, out)
        else:
            out.append(child)

def all_shape_nodes_masked(node):
    leaves = []
    collect_shape_nodes(node, leaves)
    return bool(leaves) and all(shape.is_mask for shape in leaves)

def node_origin(node):
    leaves = []
    collect_shape_nodes(node, leaves)
    if not leaves:
        return 0.0, 0.0
    points = []
    for shape in leaves:
        points.extend(shape_corners(shape))
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_y = max(p[1] for p in points)
    return (min_x + max_x) / 2.0, (min_y + max_y) / 2.0

def normalize_groups(node):
    normalized = []
    for child in node.children:
        if isinstance(child, GroupNode):
            normalize_groups(child)
            if len(child.children) == 1:
                only_child = child.children[0]
                if child.is_mask_group:
                    if isinstance(only_child, GroupNode):
                        only_child.is_mask_group = True
                    else:
                        only_child.is_mask = True
                normalized.append(only_child)
            elif child.children:
                normalized.append(child)
        else:
            normalized.append(child)
    node.children = normalized

def terminal_depth(node):
    if not isinstance(node, GroupNode) or not node.children or not isinstance(node.children[-1], GroupNode):
        return 1
    return 1 + terminal_depth(node.children[-1])

def sibling_group_transform_marker(previous_group_depth):
    return b'\x00' + (b'\x01' * max(1, previous_group_depth)) + b'\x03'

def pack_translation_transform(x, y, marker):
    return marker + struct.pack('<ffff', x, y, 1.0, 0.0)

def encode_group_node(group, parent_offset=(0.0, 0.0), transform_marker=b'\x03', inherited_mask=False):
    children = group.children
    blocks = (len(children) + 7) // 8
    is_mask_group = group.is_mask_group or all_shape_nodes_masked(group)
    marker = 0x60 if is_mask_group else 0x20
    origin = node_origin(group)
    group.tx, group.ty = origin
    out = bytearray(pack_translation_transform(origin[0] - parent_offset[0], origin[1] - parent_offset[1], transform_marker))
    out.extend(struct.pack('<BHHH', marker, len(children), blocks, 0))
    out.extend(child_bitmap(children))
    child_bytes, final_mask = encode_children(children, origin, inherited_mask or is_mask_group)
    out.extend(child_bytes)
    return bytes(out), final_mask

def encode_children(children, parent_offset=(0.0, 0.0), inherited_mask=False):
    out = bytearray()
    previous_was_mask = False
    previous_was_group = False
    previous_group_depth = 0
    previous_sibling_seen = False
    for child in children:
        mark_previous = previous_was_mask
        previous_was_mask = False
        if isinstance(child, GroupNode):
            if previous_was_group:
                transform_marker = sibling_group_transform_marker(previous_group_depth)
            elif previous_sibling_seen:
                transform_marker = b'\x00\x03'
            else:
                transform_marker = b'\x03'
            if mark_previous and transform_marker and transform_marker[0] == 0x00:
                transform_marker = b'\x01' + transform_marker[1:]
            group_bytes, group_final_mask = encode_group_node(child, parent_offset, transform_marker, inherited_mask)
            out.extend(group_bytes)
            previous_was_mask = group_final_mask
            previous_was_group = True
            previous_group_depth = terminal_depth(child)
        else:
            if previous_was_group:
                out.append(0x00)
                out.extend(b'\x01' * max(0, previous_group_depth - 1))
            lead_mask = previous_was_group or mark_previous
            out.extend(encode_shape_node(child, parent_offset[0], parent_offset[1], lead_mask, False, not previous_sibling_seen))
            previous_was_mask = child.is_mask
            previous_was_group = False
            previous_group_depth = 0
        previous_sibling_seen = True
    return bytes(out), previous_was_mask

def build_cgroup_payload(root_group):
    normalize_groups(root_group)
    children = root_group.children
    root_blocks = (len(children) + 7) // 8
    if not children:
        raise ValueError("SVG has no valid Forza layers")
    root_origin = node_origin(root_group)
    payload = bytearray()
    payload.extend(b'gyvl')
    payload.extend(struct.pack('<II', 1, 0))
    payload.extend(struct.pack('<Bffff', 0x03, 0.0, 0.0, 1.0, 0.0))
    payload.extend(struct.pack('<BHH2s', 0x20, len(children), root_blocks, b'\x00\x00'))
    payload.extend(child_bitmap(children))
    child_bytes, final_mask = encode_children(children, root_origin, root_group.is_mask_group)
    payload.extend(child_bytes)
    payload.extend(b'\x01' if final_mask else b'\x00')
    terminal = terminal_depth(children[-1]) if isinstance(children[-1], GroupNode) else 0
    payload.extend(b'\x01' * (terminal + 1))
    return bytes(payload)

def wrap_cgroup_payload(payload):
    compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=zlib.MAX_WBITS, memLevel=8, strategy=zlib.Z_DEFAULT_STRATEGY)
    zstream = compressor.compress(payload) + compressor.flush()
    return struct.pack('<II', len(zstream), len(payload)) + zstream

def write_cgroup_file(target_cgroup, root_group):
    new_data = wrap_cgroup_payload(build_cgroup_payload(root_group))
    temp_cgroup = target_cgroup + ".tmp"
    with open(temp_cgroup, 'wb') as f:
        f.write(new_data)
    try:
        shutil.copystat(target_cgroup, temp_cgroup)
    except Exception:
        pass
    os.replace(temp_cgroup, target_cgroup)

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

def unwrap_cgroup_file(cgroup_path):
    data = open(cgroup_path, 'rb').read()
    if len(data) < 8:
        raise ValueError("C_group file is too small")
    comp_len, uncomp_len = struct.unpack_from('<II', data, 0)
    payload = zlib.decompress(data[8:8 + comp_len])
    if uncomp_len and len(payload) != uncomp_len:
        raise ValueError("C_group uncompressed length mismatch")
    if payload[:4] != b'gyvl':
        raise ValueError("Invalid C_group magic")
    return payload

def parse_shape_record(data, offset):
    lead = data[offset]
    if lead in (0x00, 0x01) and offset + 32 <= len(data) and data[offset + 1] == 0x02:
        shape_word = struct.unpack_from('<H', data, offset + 2)[0]
        rot, tx, ty, sx, sy, skew = struct.unpack_from('<ffffff', data, offset + 4)
        b, g, r, a = struct.unpack_from('<BBBB', data, offset + 28)
        return ShapeNode(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a, False), offset + 32, lead == 0x01
    if lead == 0x02 and offset + 31 <= len(data):
        shape_word = struct.unpack_from('<H', data, offset + 1)[0]
        rot, tx, ty, sx, sy, skew = struct.unpack_from('<ffffff', data, offset + 3)
        b, g, r, a = struct.unpack_from('<BBBB', data, offset + 27)
        return ShapeNode(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a, False), offset + 31, False
    raise ValueError(f"Unsupported shape record at 0x{offset:x}")

def parse_optional_transform_record(data, offset):
    markers = [
        b'\x00\x01\x01\x01\x03',
        b'\xdf\x03\x03',
        b'\x00\x01\x01\x03',
        b'\x00\x01\x03',
        b'\x03\x03',
        b'\x00\x03',
        b'\x01\x03',
        b'\x03',
    ]
    for marker in markers:
        end = offset + len(marker)
        payload_end = end + 16
        if payload_end <= len(data) and data[offset:end] == marker:
            px, py, scale_x, rot = struct.unpack_from('<ffff', data, end)
            scale_y = scale_x
            next_offset = payload_end
            if next_offset + 5 <= len(data) and data[next_offset] in (0x30, 0x70):
                scale_y = struct.unpack_from('<f', data, next_offset + 1)[0]
                next_offset += 5
            return (px, py, scale_x, scale_y, rot), next_offset
    return None, offset

def skip_group_to_shape_control(data, offset):
    if offset < len(data) and data[offset] == 0x00 and not (offset + 1 < len(data) and data[offset + 1] == 0x02):
        offset += 1
        while offset < len(data) and data[offset] == 0x01 and not (offset + 1 < len(data) and data[offset + 1] == 0x02):
            offset += 1
    return offset

def apply_group_transform_to_shape(shape, transform):
    px, py, scale_x, scale_y, rot = transform
    rad = math.radians(rot)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    x = shape.tx * scale_x
    y = shape.ty * scale_y
    shape.tx = px + cos_r * x - sin_r * y
    shape.ty = py + sin_r * x + cos_r * y
    shape.sx *= scale_x
    shape.sy *= scale_y
    shape.rot = (shape.rot + rot) % 360.0

def apply_group_transform(group, transform):
    for child in group.children:
        if isinstance(child, GroupNode):
            apply_group_transform(child, transform)
        else:
            apply_group_transform_to_shape(child, transform)

def decode_children(data, offset, count, bitmap, inherited_mask=False):
    children = []
    for idx in range(count):
        if offset < len(data) and data[offset] == 0x01 and (offset + 1 >= len(data) or data[offset + 1] != 0x02):
            if children:
                last = children[-1]
                if isinstance(last, GroupNode):
                    last.is_mask_group = True
                else:
                    last.is_mask = True
            offset += 1

        is_group = bool(bitmap[idx // 8] & (1 << (idx % 8))) if bitmap else False
        if is_group:
            transform, offset = parse_optional_transform_record(data, offset)
            child, offset = decode_group_record(data, offset, inherited_mask)
            if transform:
                apply_group_transform(child, transform)
            children.append(child)
        else:
            offset = skip_group_to_shape_control(data, offset)
            shape, offset, marks_previous = parse_shape_record(data, offset)
            if marks_previous and children:
                last = children[-1]
                if isinstance(last, GroupNode):
                    last.is_mask_group = True
                else:
                    last.is_mask = True
            shape.is_mask = inherited_mask
            children.append(shape)

    if offset < len(data) and data[offset] == 0x01 and (offset + 1 >= len(data) or data[offset + 1] != 0x02):
        if children:
            last = children[-1]
            if isinstance(last, GroupNode):
                last.is_mask_group = True
            else:
                last.is_mask = True
        offset += 1
    return children, offset

def decode_group_record(data, offset, inherited_mask=False):
    marker = data[offset]
    if marker in (0x20, 0x60):
        count = struct.unpack_from('<H', data, offset + 1)[0]
        blocks = struct.unpack_from('<H', data, offset + 3)[0]
        bitmap_start = offset + 7
    else:
        marker = 0x20
        count = struct.unpack_from('<H', data, offset)[0]
        blocks = struct.unpack_from('<H', data, offset + 2)[0]
        bitmap_start = offset + 6
    bitmap = data[bitmap_start:bitmap_start + blocks]
    child_offset = bitmap_start + blocks
    group = GroupNode(is_mask_group=(marker == 0x60) or inherited_mask)
    group.children, child_offset = decode_children(data, child_offset, count, bitmap, group.is_mask_group)
    return group, child_offset

def find_root_group_offset(payload):
    marker_start = 0x0c
    candidates = [
        b'\x00\x01\x01\x01\x03',
        b'\xdf\x03\x03',
        b'\x00\x01\x01\x03',
        b'\x00\x01\x03',
        b'\x03\x03',
        b'\x00\x03',
        b'\x01\x03',
        b'\x03',
    ]
    for marker in candidates:
        end = marker_start + len(marker)
        root_offset = end + 16
        if payload[marker_start:end] == marker and root_offset < len(payload) and payload[root_offset] in (0x20, 0x60):
            return root_offset
    raise ValueError("Unsupported root transform marker")

def decode_cgroup_payload(payload):
    if payload[:4] != b'gyvl':
        raise ValueError("Invalid C_group payload")
    root_offset = find_root_group_offset(payload)
    root_marker = payload[root_offset]
    if root_marker not in (0x20, 0x60):
        raise ValueError("Unsupported root group marker")
    count = struct.unpack_from('<H', payload, root_offset + 1)[0]
    blocks = struct.unpack_from('<H', payload, root_offset + 3)[0]
    bitmap_start = root_offset + 7
    bitmap = payload[bitmap_start:bitmap_start + blocks]
    children, _ = decode_children(payload, bitmap_start + blocks, count, bitmap, root_marker == 0x60)
    return GroupNode(children=children, is_mask_group=(root_marker == 0x60), name="root")

def load_symbol_library():
    global _symbol_library_cache
    if _symbol_library_cache is None:
        library_path = get_resource_path('fh6_vinyl_symbols.svg')
        if not os.path.isfile(library_path):
            raise FileNotFoundError('Cannot find fh6_vinyl_symbols.svg')
        library_root = ET.parse(library_path).getroot()
        symbol_dict, _ = collect_svg_defs(library_root)
        href_by_word, elements_by_id = {}, {}
        for elem in library_root.iter():
            if get_local_name(elem) != 'symbol':
                continue
            symbol_id = elem.get('id', '')
            if not symbol_id:
                continue
            elements_by_id[symbol_id] = elem
            match = re.search(r'fh6_t\d+_i\d+_w(\d+)', symbol_id)
            if match:
                href_by_word[int(match.group(1))] = f'#{symbol_id}'
        _symbol_library_cache = (symbol_dict, href_by_word, elements_by_id)
    return _symbol_library_cache

def load_pattern_library():
    global _pattern_library_cache
    if _pattern_library_cache is None:
        library_path = get_resource_path('fh6_vinyl_patterns.svg')
        if not os.path.isfile(library_path):
            raise FileNotFoundError('Cannot find fh6_vinyl_patterns.svg')
        library_root = ET.parse(library_path).getroot()
        _pattern_library_cache = {
            elem.get('id'): elem for elem in library_root.iter()
            if get_local_name(elem) == 'pattern' and elem.get('id')
        }
    return _pattern_library_cache

def add_referenced_defs(root, defs, symbol_elements):
    pattern_elements = load_pattern_library()
    for definition_id in collect_used_def_ids(root):
        source = symbol_elements.get(definition_id)
        if source is None:
            source = pattern_elements.get(definition_id)
        if source is not None:
            defs.append(deepcopy(source))

def append_svg_shape(parent, shape, href, symbol_dict, canvas_w, canvas_h, node_id):
    min_x, min_y = symbol_dict.get(href, (0.0, 0.0))
    svg_cx = canvas_w / 2.0 + shape.tx
    svg_cy = canvas_h / 2.0 - shape.ty
    rad = math.radians(shape.rot)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    ma = shape.sx * cos_r
    mb = -shape.sx * sin_r
    # C_group uses R * shearX(skew) * scale.  SVG's Y axis is inverted,
    # so conjugating that matrix into SVG space changes the shear terms.
    mc = shape.sy * (sin_r - shape.skew * cos_r)
    md = shape.sy * (cos_r + shape.skew * sin_r)
    me = svg_cx + ma * min_x + mc * min_y
    mf = svg_cy + mb * min_x + md * min_y

    use_elem = ET.Element(f'{{{SVG_NS}}}use')
    use_elem.set(f'{{{XLINK_NS}}}href', href)
    use_elem.set('x', '0')
    use_elem.set('y', '0')
    use_elem.set('transform', f"matrix({ma:.6f},{mb:.6f},{mc:.6f},{md:.6f},{me:.6f},{mf:.6f})")
    if shape.is_mask:
        use_elem.set('style', f"fill:url(#mask_indicator_dark); opacity:{round(shape.a / 255.0, 4)};")
        use_elem.set('id', node_id.replace('shape', 'mask'))
    else:
        use_elem.set('style', f"fill:#{shape.r:02x}{shape.g:02x}{shape.b:02x}; opacity:{round(shape.a / 255.0, 4)};")
        use_elem.set('id', node_id)
    parent.append(use_elem)

def append_svg_group(parent, group, href_by_word, symbol_dict, canvas_w, canvas_h, prefix):
    g_elem = ET.Element(f'{{{SVG_NS}}}g')
    g_elem.set('id', group.name or prefix)
    if group.is_mask_group:
        g_elem.set('data-forza-mask-group', '1')
    parent.append(g_elem)
    for idx, child in enumerate(group.children):
        child_prefix = f"{prefix}_{idx+1}"
        if isinstance(child, GroupNode):
            append_svg_group(g_elem, child, href_by_word, symbol_dict, canvas_w, canvas_h, child_prefix)
        else:
            href = href_by_word.get(child.shape_word)
            if href:
                append_svg_shape(g_elem, child, href, symbol_dict, canvas_w, canvas_h, f"shape_{child_prefix}")

def export_cgroup_to_svg(cgroup_path, svg_path):
    root_group = decode_cgroup_payload(unwrap_cgroup_file(cgroup_path))
    symbol_dict, href_by_word, symbol_elements = load_symbol_library()
    tree, root, defs, target_container = create_inkscape_document()
    canvas_w, canvas_h = 1920.0, 1080.0
    for idx, child in enumerate(root_group.children):
        child_prefix = f"forza_{idx+1}"
        if isinstance(child, GroupNode):
            append_svg_group(target_container, child, href_by_word, symbol_dict, canvas_w, canvas_h, child_prefix)
        else:
            href = href_by_word.get(child.shape_word)
            if href:
                append_svg_shape(target_container, child, href, symbol_dict, canvas_w, canvas_h, f"shape_{child_prefix}")
    add_referenced_defs(root, defs, symbol_elements)
    prune_unused_defs(root)
    write_inkscape_svg(tree, svg_path)

def collect_used_def_ids(root):
    used = set()
    defs_elems = {'symbol', 'pattern'}
    for elem in root.iter():
        local = get_local_name(elem)
        if local in defs_elems:
            continue
        href = get_href(elem)
        if href.startswith('#'):
            used.add(href[1:])
        for value in elem.attrib.values():
            for match in re.findall(r'url\(#([^)]+)\)', value):
                used.add(match)

    changed = True
    while changed:
        changed = False
        for elem in root.iter():
            elem_id = elem.get('id')
            if elem_id not in used:
                continue
            href = get_href(elem)
            if href.startswith('#') and href[1:] not in used:
                used.add(href[1:])
                changed = True
            for value in elem.attrib.values():
                for match in re.findall(r'url\(#([^)]+)\)', value):
                    if match not in used:
                        used.add(match)
                        changed = True
    return used

def prune_unused_defs(root):
    """Remove unused symbols and patterns from an in-memory SVG tree."""
    used = collect_used_def_ids(root)
    parent_map = {child: parent for parent in root.iter() for child in list(parent)}
    removed = 0
    for elem in list(root.iter()):
        if get_local_name(elem) not in ('symbol', 'pattern'):
            continue
        elem_id = elem.get('id')
        if elem_id and elem_id not in used:
            parent = parent_map.get(elem)
            if parent is not None:
                parent.remove(elem)
                removed += 1
    return removed

# ================= UI & Workflow Helpers =================

def select_folder(title, initialdir=None):
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    if not initialdir:
        initialdir = DEFAULT_GAMESAVE_DIR if os.path.exists(DEFAULT_GAMESAVE_DIR) else "C:\\"
    folder_path = filedialog.askdirectory(title=title, initialdir=initialdir)
    root.destroy()
    return folder_path

def select_file(title, filetypes):
    global _cached_general_dir
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    init_dir = _cached_general_dir if _cached_general_dir and os.path.exists(_cached_general_dir) else os.path.expanduser('~/Documents')
    if not os.path.exists(init_dir):
        init_dir = os.path.expanduser('~')
        
    file_path = filedialog.askopenfilename(title=title, filetypes=filetypes, initialdir=init_dir)
    if file_path:
        _cached_general_dir = os.path.dirname(file_path)
        
    root.destroy()
    return file_path

def save_file(title, filetypes, initialfile):
    global _cached_general_dir
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    init_dir = _cached_general_dir if _cached_general_dir and os.path.exists(_cached_general_dir) else os.path.expanduser('~/Documents')
    if not os.path.exists(init_dir):
        init_dir = os.path.expanduser('~')

    file_path = filedialog.asksaveasfilename(
        title=title, 
        filetypes=filetypes, 
        initialfile=initialfile, 
        initialdir=init_dir,
        defaultextension=".svg"
    )
    if file_path:
        _cached_general_dir = os.path.dirname(file_path)
        
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

def choose_containers_root():
    global _cached_gamesave_dir
    if _cached_gamesave_dir and os.path.exists(_cached_gamesave_dir):
        gamesave_dir = _cached_gamesave_dir
        print(f"自动使用上次选择的路径 / Automatically using previously path:\n  {gamesave_dir}")
    elif os.path.exists(DEFAULT_GAMESAVE_DIR) and os.path.exists(os.path.join(DEFAULT_GAMESAVE_DIR, "pgs")):
        gamesave_dir = DEFAULT_GAMESAVE_DIR
        print(f"自动使用默认存档路径 / Automatically using default GameSave path:\n  {gamesave_dir}")
    else:
        gamesave_dir = select_folder("GameSave")
        if not gamesave_dir:
            print("已取消 / Cancelled")
            return None, None, None

    pgs_dir = os.path.join(gamesave_dir, "pgs")
    if not os.path.exists(pgs_dir):
        print("这不是有效的存档文件夹 / This is not a valid GameSave folder")
        _cached_gamesave_dir = None
        return None, None, None

    _cached_gamesave_dir = gamesave_dir
    u_folders = [f for f in os.listdir(pgs_dir) if f.startswith("u_") and f.endswith("_16D460") and os.path.isdir(os.path.join(pgs_dir, f))]
    if not u_folders:
        print("未找到玩家数据 / No player data found")
        _cached_gamesave_dir = None
        return None, None, None

    if len(u_folders) == 1:
        u_dir = os.path.join(pgs_dir, u_folders[0])
    else:
        print("发现多个玩家存档 / Multiple player profiles found:")
        for i, folder in enumerate(u_folders):
            print(f"{i+1}. {folder}")
        while True:
            choice = input("请选择要操作的存档序号，或输入 q 返回主菜单 / Choose player index or 'q' to return to main menu: ").strip().lower()
            if choice in ('q', 'c', 'exit', 'quit'):
                print("已取消 / Cancelled")
                return None, None, None
            try:
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(u_folders):
                    u_dir = os.path.join(pgs_dir, u_folders[choice_idx])
                    break
                print("输入无效 / Invalid input")
            except ValueError:
                print("输入无效 / Invalid input")

    containers_root = os.path.join(u_dir, "current", "ContainersRoot")
    if not os.path.exists(containers_root):
        print("未找到数据根目录 / No root directory found")
        return None, None, None
    return gamesave_dir, u_dir, containers_root

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

def inject_cgroup(target_cgroup, root_group):
    try:
        write_cgroup_file(target_cgroup, root_group)
    except Exception as e:
        print(f"写入彩绘纹饰分组失败 / Failed to write vinyl group: {e}")
        return False

    print(f"注入成功 / Injection successful")
    return True

# ================= Workflows =================

def find_inkscape_user_data_dir():
    """Find the active Inkscape profile without assuming its installation path."""
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

def workflow_install_inkscape_symbols():
    print("\n准备安装 FH6 Inkscape 符号库... / Preparing to install the FH6 Inkscape symbol library...")
    source_libraries = (
        ("fh6_vinyl_symbols.svg", "symbols", "FH6_Vinyl_Symbols.svg"),
        ("fh6_vinyl_patterns.svg", "paint", "FH6_Vinyl_Patterns.svg"),
    )
    missing = [filename for filename, _, _ in source_libraries if not os.path.isfile(get_resource_path(filename))]
    if missing:
        print(f"错误: 找不到资源文件 / Error: Missing resource files: {', '.join(missing)}")
        return

    data_dir = find_inkscape_user_data_dir()
    if data_dir:
        print(f"检测到 Inkscape 用户目录 / Inkscape user directory detected:\n  {data_dir}")
    else:
        initialdir = os.environ.get("APPDATA", "C:\\")
        print("未能自动定位 Inkscape 用户目录，请选择 Symbols 文件夹。 / Could not locate the Inkscape profile; select its Symbols folder.")
        symbols_dir = select_folder("选择 Inkscape Symbols 文件夹 / Select Inkscape Symbols folder", initialdir)
        if not symbols_dir:
            print("已取消 / Cancelled")
            return
        data_dir = os.path.dirname(symbols_dir)

    destinations = [
        (get_resource_path(filename), os.path.join(data_dir, folder, installed_name))
        for filename, folder, installed_name in source_libraries
    ]
    existing = [destination for _, destination in destinations if os.path.exists(destination)]
    if existing:
        choice = input("已有 FH6 符号库或图案库，是否覆盖？ / Existing FH6 libraries found. Overwrite? [y/N]: ").strip().lower()
        if choice not in ("y", "yes"):
            print("已取消 / Cancelled")
            return

    try:
        for source, destination in destinations:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)
            print(f"已安装 / Installed:\n  {destination}")
        print("请重启 Inkscape 或重新打开 Symbols/Fill and Stroke 面板以加载新资源。 / Restart Inkscape or reopen the Symbols/Fill and Stroke panels to load the libraries.")
    except Exception as e:
        print(f"安装失败 / Installation failed: {e}")

def workflow_geometrize_to_svg():
    print("\n[1/3] 请选择 Geometrize 导出的 JSON 文件... / Please select Geometrize JSON file...")
    json_path = select_file("Geometrize JSON", [("JSON 文件", "*.json")])
    if not json_path:
        print("已取消 / Cancelled")
        return
        
    print("[2/3] 正在加载内部符号库进行合成... / Loading the internal symbol library for synthesis...")
        
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

    layer_count = 0
    for shape in shapes:
        type_code = shape.get("type")
        data = shape.get("data", [])
        if type_code not in (1, 16) or len(data) < 4:
            continue
        color = shape.get("color", [])
        layer_count += 4 if type_code == 1 and len(color) >= 4 and color[3] == 0 else 1
    default_name = f"{os.path.splitext(os.path.basename(json_path))[0]}.{layer_count}.svg"
        
    print("[3/3] 请选择合并后 SVG 文件的保存位置... / Please select save location for merged SVG...")
    save_path = save_file(
        title="保存由 Geometrize 生成的 SVG / Save generated SVG", 
        filetypes=[("SVG 文件", "*.svg")], 
        initialfile=default_name
    )
    if not save_path:
        print("已取消 / Cancelled")
        return

    try:
        symbol_dict, _, symbol_elements = load_symbol_library()
        tree, root, defs, target_container = create_inkscape_document()
        canvas_w, canvas_h = 1920.0, 1080.0
                        
        rect_href, circle_href = None, None
        for k in symbol_dict.keys():
            if k.endswith('_w101'): rect_href = k
            elif k.endswith('_w102'): circle_href = k
            
        if not rect_href or not circle_href:
            print("错误: 模板库中找不到基础矩形(w101)或圆形(w102)的符号引用。 / Error: Cannot find base shape symbols in template.")
            return
            
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
                print(f"跳过不支持的元素 / Skiped: (index {idx}): type {type_code}")
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
            
        add_referenced_defs(root, defs, symbol_elements)
        prune_unused_defs(root)
        write_inkscape_svg(tree, save_path)
        print(f"成功写入 {valid_count} 个图形 / Wrote {valid_count}\n文件已保存在 / Saved: {os.path.normpath(save_path)}")
        
    except Exception as e:
        print(f"错误 / Error: {e}")

def workflow_vinylizer_to_svg():
    print("\n[1/3] 请选择 Vinylizer 导出的 JSON 文件... / Please select Vinylizer JSON file...")
    json_path = select_file("Vinylizer JSON", [("JSON", "*.json")])
    if not json_path:
        print("已取消 / Cancelled")
        return
        
    print("[2/3] 正在加载内部符号库进行合成... / Loading the internal symbol library for synthesis...")
        
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            vin_data = json.load(f)
            
        shapes = vin_data.get("shapes", vin_data if isinstance(vin_data, list) else [])
        if isinstance(vin_data, dict) and "shapes" not in vin_data:
            shapes = []
            
        if not shapes:
            print("错误: JSON 文件中没有找到有效的形状数据 / Error: No valid shapes found in JSON.")
            return
            
    except Exception as e:
        print(f"读取 JSON 失败 / Failed to read JSON: {e}")
        return

    supported_types = {1, 16, 103, 228}
    layer_count = sum(
        1 for shape in shapes
        if shape.get("type") in supported_types and len(shape.get("data", [])) >= 4
    )
    default_name = f"{os.path.splitext(os.path.basename(json_path))[0]}.{layer_count}.svg"
        
    print("[3/3] 请选择合并后 SVG 文件的保存位置... / Please select save location for merged SVG...")
    save_path = save_file(
        title="保存由 Vinylizer 生成的 SVG / Save generated SVG", 
        filetypes=[("SVG", "*.svg")], 
        initialfile=default_name
    )
    if not save_path:
        print("已取消 / Cancelled")
        return

    try:
        symbol_dict, _, symbol_elements = load_symbol_library()
        tree, root, defs, target_container = create_inkscape_document()
        canvas_w, canvas_h = 1920.0, 1080.0
                        
        # Vinylizer type -> (FH6 shape word, X divisor, Y divisor).
        # Triangle size_x is its half-base while size_y is its full height.
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
            print(f"错误: 符号库中找不到 {missing_words} / Error: Missing symbols: {missing_words}")
            return
            
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

        # Canvas bound
        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')
        has_valid_shapes = False
        
        for shape in shapes:
            if shape.get("type") not in shape_specs:
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
                print(f"跳过不支持的元素 / Skipped unsupported shape (index {idx}): type {type_code}")
                continue
                
            data = shape.get("data", [])
            if len(data) < 4:
                continue
                
            color = list(shape.get("color", [255, 255, 255, 255]))
            color.extend([255] * (4 - len(color)))
            r, g, b, a = [max(0, min(255, int(v))) for v in color]

            # Vinylizer 1.0.0: [cx, cy, size_x, size_y, angle].
            # Vinylizer <= 0.1.2 rectangles may omit angle.
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
            
        add_referenced_defs(root, defs, symbol_elements)
        prune_unused_defs(root)
        write_inkscape_svg(tree, save_path)
        print(f"成功写入 {valid_count} 个图形 / Wrote {valid_count}\n文件已保存在 / Saved: {os.path.normpath(save_path)}")
        
    except Exception as e:
        print(f"错误 / Error: {e}")

def workflow_inject_svg():
    global _cached_gamesave_dir, _has_prompted_backup
    print("\n[1/4] 请选择您的 GameSave 文件夹... / Please select your GameSave folder...")
    
    if _cached_gamesave_dir and os.path.exists(_cached_gamesave_dir):
        gamesave_dir = _cached_gamesave_dir
        print(f"自动使用上次选择的路径 / Automatically using previously path:\n  {gamesave_dir}")
    elif os.path.exists(DEFAULT_GAMESAVE_DIR) and os.path.exists(os.path.join(DEFAULT_GAMESAVE_DIR, "pgs")):
        gamesave_dir = DEFAULT_GAMESAVE_DIR
        print(f"自动使用默认存档路径 / Automatically using default GameSave path:\n  {gamesave_dir}")
    else:
        gamesave_dir = select_folder("GameSave")
        if not gamesave_dir:
            print("已取消 / Cancelled")
            return
            
    pgs_dir = os.path.join(gamesave_dir, "pgs")
    if not os.path.exists(pgs_dir):
        print("这不是有效的存档文件夹 / This is not a valid GameSave folder")
        _cached_gamesave_dir = None
        return
        
    _cached_gamesave_dir = gamesave_dir
        
    u_folders = [f for f in os.listdir(pgs_dir) if f.startswith("u_") and f.endswith("_16D460") and os.path.isdir(os.path.join(pgs_dir, f))]
    if not u_folders:
        print("未找到玩家数据 / No player data found")
        _cached_gamesave_dir = None
        return
        
    if len(u_folders) == 1:
        u_dir = os.path.join(pgs_dir, u_folders[0])
    else:
        print("发现多个玩家存档 / Multiple player profiles found:")
        for i, folder in enumerate(u_folders):
            print(f"{i+1}. {folder}")
            
        while True:
            choice = input("请选择要操作的存档序号，或输入 q 返回主菜单 / Choose player index or 'q' to return to main menu: ").strip().lower()
            if choice in ('q', 'c', 'exit', 'quit'):
                print("已取消 / Cancelled")
                return
            try:
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(u_folders):
                    u_dir = os.path.join(pgs_dir, u_folders[choice_idx])
                    break
                else:
                    print("输入无效 / Invalid input")
            except ValueError:
                print("输入无效 / Invalid input")
                
    containers_root = os.path.join(u_dir, "current", "ContainersRoot")
    
    if not os.path.exists(containers_root):
        print("未找到数据根目录 / No root directory found")
        return

    print(f"已定位到存档 / GameSave: {os.path.normpath(u_dir)}")

    if not _has_prompted_backup:
        print("[2/4] 为了您的数据安全，建议操作前备份存档。是否进行？ / For your data safety, it's recommended to backup before proceeding. Do you want to backup?")
        backup_choice = input("1. 备份 / Backup\n2. 不备份 / Don't backup\n输入 q 返回主菜单 / 'q' to return to main menu\n选择 / Choose: ").strip().lower()
        
        if backup_choice in ('q', 'c', 'exit', 'quit'):
            print("已取消 / Cancelled")
            return
        elif backup_choice == "1":
            create_backup(u_dir, gamesave_dir)
        else:
            print("已跳过 / Skipped")
        
        _has_prompted_backup = True

    print("[3/4] 请选择要注入的 Inkscape SVG 文件... / Please select your Inkscape SVG file to inject...")
    svg_path = select_file("Inkscape SVG", [("SVG", "*.svg")])
    if not svg_path:
        print("已取消 / Cancelled")
        return
        
    print(f"正在解析 SVG / Parsing SVG: {os.path.basename(svg_path)}")
    try:
        layers_bin_list, prev_was_mask, total_nodes, root_group = process_svg(svg_path)
        print(f"识别到 {total_nodes} 个元素，过滤后有效图层数：{len(layers_bin_list)} / Found {total_nodes} elements, {len(layers_bin_list)} valid layers after filtering")
    except Exception as e:
        print(f"解析失败 / Failed to parse SVG: {e}")
        return

    if len(layers_bin_list) > MAX_VINYL_GROUP_LAYERS:
        print(
            f"错误：有效图层数 {len(layers_bin_list)} 超过 FH6 彩绘纹饰分组上限 {MAX_VINYL_GROUP_LAYERS}，无法注入。\n"
            f"Error: {len(layers_bin_list)} valid layers exceeds the FH6 vinyl group limit of {MAX_VINYL_GROUP_LAYERS}. Injection cancelled."
        )
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
        
        choice = input("请输入对应的序号或输入 q 返回主菜单 / Choose or 'q' to return to main menu: ").strip().lower()
        if choice in ('q', 'c', 'exit', 'quit'):
            print("已取消 / Cancelled")
            return
            
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(target_groups):
                selected_group = target_groups[choice_idx]
                target_cgroup_path = selected_group["path"]
                
                confirmation = input(
                    f"注入：{selected_group['title']} - {selected_group['author']}，是否确认？按回车键继续，其他键返回选择列表\n"
                    "Inject selected vinyl group? Press Enter to continue; any other key returns to the list: "
                )
                if confirmation:
                    continue
                print(f"准备注入到 / Inject into: {selected_group['title']}")
                if inject_cgroup(target_cgroup_path, root_group):
                    print("注入完成！请回到游戏打开该彩绘纹饰分组并重新保存以刷新缩略图 / Injection complete! Please open this vinyl group in game and save again to refresh thumbnail.")
                    break
                else:
                    print("将返回彩绘纹饰分组选择列表... / Returning to vinyl group selection...")
            else:
                print("输入无效 / Invalid input")
        except ValueError:
            print("输入无效 / Invalid input")

def workflow_export_svg():
    print("\n[1/3] 正在定位 GameSave 文件夹... / Locating GameSave folder...")
    _, _, containers_root = choose_containers_root()
    if not containers_root:
        return

    print("[2/3] 扫描可导出的彩绘纹饰分组... / Scanning exportable vinyl groups...")
    target_groups = get_target_layer_groups(containers_root)
    if not target_groups:
        print("未找到任何可导出的彩绘纹饰分组 / No exportable vinyl groups found")
        return

    while True:
        print("\n请选择要导出的彩绘纹饰分组 / Please select the vinyl group to export:")
        print("-" * 10)
        for i, group in enumerate(target_groups):
            print(f"{i+1}. {group['title']} - {group['author']}")
        print("-" * 10)

        choice = input("请输入对应的序号或输入 q 返回主菜单 / Choose or 'q' to return to main menu: ").strip().lower()
        if choice in ('q', 'c', 'exit', 'quit'):
            print("已取消 / Cancelled")
            return
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(target_groups):
                selected_group = target_groups[choice_idx]
                safe_title = re.sub(r'[\\/:*?\"<>|]+', '_', selected_group['title']).strip() or "Exported_Forza_VinylGroup"
                try:
                    exported_root = decode_cgroup_payload(unwrap_cgroup_file(selected_group["path"]))
                    layer_count = len(flatten_shapes(exported_root))
                except Exception as e:
                    print(f"读取图层数量失败 / Failed to count layers: {e}")
                    return
                save_path = save_file(
                    title="保存导出的 Inkscape SVG / Save exported Inkscape SVG",
                    filetypes=[("SVG", "*.svg")],
                    initialfile=f"{safe_title}.{layer_count}.svg"
                )
                if not save_path:
                    print("已取消 / Cancelled")
                    return
                print("[3/3] 正在导出 SVG... / Exporting SVG...")
                export_cgroup_to_svg(selected_group["path"], save_path)
                print(f"导出完成 / Export complete:\n  {os.path.normpath(save_path)}")
                return
            print("输入无效 / Invalid input")
        except ValueError:
            print("输入无效 / Invalid input")
        except Exception as e:
            print(f"导出失败 / Export failed: {e}")
            return

def main():
    while True:
        print("\n=== 请选择你的操作 / Please select your operation ===")
        print("1. 安装 FH6 Inkscape 符号库 / Install FH6 Inkscape symbol library")
        print("2. 从 Geometrize JSON 生成 Inkscape SVG / Create Inkscape SVG from Geometrize JSON")
        print("3. 从 Vinylizer JSON 生成 Inkscape SVG / Create Inkscape SVG from Vinylizer JSON")
        print("4. 将 Inkscape SVG 导入到 FH6 存档 / Inject Inkscape SVG into FH6 save")
        print("5. 从 FH6 存档导出 Inkscape SVG / Export Inkscape SVG from FH6 save")
        print("Q. 退出 / Quit")
        
        choice = input("\n输入对应序号 / Enter selection: ").strip().lower()
        
        if choice == '1':
            workflow_install_inkscape_symbols()
        elif choice == '2':
            workflow_geometrize_to_svg()
        elif choice == '3':
            workflow_vinylizer_to_svg()
        elif choice == '4':
            workflow_inject_svg()
        elif choice == '5':
            workflow_export_svg()
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

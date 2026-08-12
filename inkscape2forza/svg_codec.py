"""SVG parsing and generation."""
import math
import os
import re
import xml.etree.ElementTree as ET

from .common import INKSCAPE_NS, SODIPODI_NS, SVG_NS, XLINK_NS
from .model import GroupNode, ShapeNode


# Attributes

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


def get_href(elem):
    return elem.get(f'{{{XLINK_NS}}}href') or elem.get('href', '')


def get_local_name(elem):
    return elem.tag.rsplit('}', 1)[-1] if '}' in elem.tag else elem.tag


def parse_float_attr(elem, name, default=0.0):
    try:
        return float(elem.get(name, default))
    except (TypeError, ValueError):
        return default


# Transforms

def mult_matrix(M1, M2):
    a1, b1, c1, d1, e1, f1 = M1
    a2, b2, c2, d2, e2, f2 = M2
    return (a1*a2+c1*b2, b1*a2+d1*b2, a1*c2+c1*d2, b1*c2+d1*d2, a1*e2+c1*f2+e1, b1*e2+d1*f2+f1)


def parse_transform(transform_str):
    current_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not transform_str:
        return current_matrix

    for cmd, args in re.findall(r'([a-zA-Z]+)\s*\(([^)]+)\)', transform_str):
        vals = [float(x) for x in args.replace(',', ' ').split()]
        if not vals:
            continue
        if cmd == 'matrix' and len(vals) == 6:
            m = tuple(vals)
        elif cmd == 'translate':
            m = (1.0, 0.0, 0.0, 1.0, vals[0], vals[1] if len(vals) > 1 else 0.0)
        elif cmd == 'scale':
            m = (vals[0], 0.0, 0.0, vals[1] if len(vals) > 1 else vals[0], 0.0, 0.0)
        elif cmd == 'rotate':
            a = math.radians(vals[0])
            ca, sa = math.cos(a), math.sin(a)
            if len(vals) >= 3:
                cx, cy = vals[1], vals[2]
                m = (ca, sa, -sa, ca, cx - cx*ca + cy*sa, cy - cx*sa - cy*ca)
            else:
                m = (ca, sa, -sa, ca, 0.0, 0.0)
        elif cmd == 'skewX':
            m = (1.0, 0.0, math.tan(math.radians(vals[0])), 1.0, 0.0, 0.0)
        elif cmd == 'skewY':
            m = (1.0, math.tan(math.radians(vals[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        current_matrix = mult_matrix(current_matrix, m)
    return current_matrix


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
    if sx < 1e-6:
        return tx, ty, 0, 0, 0, 0
    rot_rad = math.atan2(B, A)
    rot_deg = math.degrees(rot_rad) % 360.0
    sy = -C * math.sin(rot_rad) + D * math.cos(rot_rad)
    skew = (C * math.cos(rot_rad) + D * math.sin(rot_rad)) / sy if abs(sy) > 1e-6 else 0.0
    return tx, ty, sx * scale_factor, sy * scale_factor, rot_deg, skew


# Visibility

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


# Parsing

def collect_svg_defs(root):
    """Collect symbols and pattern references."""
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


def process_svg(svg_path):
    """Return the model root and FH6 node count."""
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


# Generation

def write_inkscape_svg(tree, svg_path):
    """Write an Inkscape-compatible SVG."""
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
    # Avoid an extra FH6 subgroup.
    return ET.ElementTree(root), root, defs, root


def append_shape_use(parent, href, symbol_dict, svg_cx, svg_cy, sx, sy, rot_deg,
                     fill, opacity, node_id, skew=0.0):
    """Append a shared SVG use element."""
    min_x, min_y = symbol_dict.get(href, (0.0, 0.0))
    rad = math.radians(rot_deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    ma = sx * cos_r
    mb = -sx * sin_r
    # Convert C_group shear into inverted SVG Y space.
    mc = sy * (sin_r - skew * cos_r)
    md = sy * (cos_r + skew * sin_r)
    me = svg_cx + ma * min_x + mc * min_y
    mf = svg_cy + mb * min_x + md * min_y

    use_elem = ET.Element(f'{{{SVG_NS}}}use')
    use_elem.set(f'{{{XLINK_NS}}}href', href)
    use_elem.set('x', '0')
    use_elem.set('y', '0')
    use_elem.set('transform', f"matrix({ma:.6f},{mb:.6f},{mc:.6f},{md:.6f},{me:.6f},{mf:.6f})")
    use_elem.set('style', f"fill:{fill}; opacity:{opacity};")
    use_elem.set('id', node_id)
    parent.append(use_elem)


def append_svg_shape(parent, shape, href, symbol_dict, canvas_w, canvas_h, node_id):
    svg_cx = canvas_w / 2.0 + shape.tx
    svg_cy = canvas_h / 2.0 - shape.ty
    if shape.is_mask:
        fill = "url(#mask_indicator_dark)"
        node_id = node_id.replace('shape', 'mask')
    else:
        fill = f"#{shape.r:02x}{shape.g:02x}{shape.b:02x}"
    append_shape_use(parent, href, symbol_dict, svg_cx, svg_cy, shape.sx, shape.sy,
                     shape.rot, fill, round(shape.a / 255.0, 4), node_id, shape.skew)


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


# Definition cleanup

def collect_used_def_ids(root):
    used, dependencies = set(), {}

    def references(elem):
        result = set()
        href = get_href(elem)
        if href.startswith('#'):
            result.add(href[1:])
        for value in elem.attrib.values():
            result.update(re.findall(r'url\(#([^)]+)\)', value))
        return result

    def walk(elem, definition_id=None):
        local = get_local_name(elem)
        if local in ('symbol', 'pattern') and elem.get('id'):
            definition_id = elem.get('id')
            dependencies.setdefault(definition_id, set())
        refs = references(elem)
        if definition_id is None:
            used.update(refs)
        else:
            dependencies[definition_id].update(refs)
        for child in elem:
            walk(child, definition_id)

    walk(root)
    pending = list(used)
    while pending:
        definition_id = pending.pop()
        for dependency in dependencies.get(definition_id, ()):
            if dependency not in used:
                used.add(dependency)
                pending.append(dependency)
    return used


def prune_unused_defs(root):
    """Remove unused symbols and patterns."""
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


# C_group export

def export_cgroup_to_svg(cgroup_path, svg_path):
    from .library import add_referenced_defs, load_symbol_library
    from .cgroup_codec import decode_cgroup_payload, unwrap_cgroup_file

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

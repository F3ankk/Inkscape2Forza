"""SVG parsing and generation."""
import bisect
import heapq
import math
import os
import re
import struct
import tempfile
import xml.etree.ElementTree as ET

from PIL import ImageColor

from .common import SVG_NS, XLINK_NS
from .model import GroupNode, ShapeNode, iter_shapes


# Attributes

def style_properties(elem):
    properties = {}
    for declaration in elem.get('style', '').split(';'):
        name, separator, value = declaration.partition(':')
        if separator:
            properties[name.strip().lower()] = value.strip()
    return properties


def collect_stylesheet_rules(root):
    rules = []
    order = 0
    for element in root.iter():
        if get_local_name(element) != 'style' or not element.text:
            continue
        css = re.sub(r'/\*.*?\*/', '', element.text, flags=re.DOTALL)
        if '@' in css:
            raise ValueError('SVG CSS at-rules are not supported')
        for selector_text, declaration_text in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
            declarations = style_properties(ET.Element('style', {'style': declaration_text}))
            for selector in selector_text.split(','):
                selector = selector.strip()
                if not selector or re.search(r'[\s>+~:\[]', selector):
                    raise ValueError(f"Unsupported SVG CSS selector: {selector!r}")
                specificity = 100 * selector.count('#') + 10 * selector.count('.')
                tag = re.match(r'^[A-Za-z_][\w-]*', selector)
                specificity += int(tag is not None)
                rules.append((specificity, order, selector, declarations))
                order += 1
        if css.count('{') != css.count('}'):
            raise ValueError('Malformed SVG stylesheet')
    return sorted(rules)


def selector_matches(elem, selector):
    tag = re.match(r'^[A-Za-z_][\w-]*|^\*', selector)
    if tag and tag.group() != '*' and get_local_name(elem) != tag.group():
        return False
    ids = re.findall(r'#([\w-]+)', selector)
    if ids and elem.get('id') not in ids:
        return False
    classes = set((elem.get('class') or '').split())
    return all(name in classes for name in re.findall(r'\.([\w-]+)', selector))


def computed_style(elem, stylesheet_rules):
    chosen = {}
    def offer(name, value, specificity, order):
        important = bool(re.search(r'!important\s*$', value, re.I))
        value = re.sub(r'!important\s*$', '', value, flags=re.I).strip()
        rank = (important, specificity, order)
        if name not in chosen or rank >= chosen[name][0]:
            chosen[name] = (rank, value)
    for specificity, order, selector, declarations in stylesheet_rules:
        if selector_matches(elem, selector):
            for name, value in declarations.items():
                offer(name, value, specificity, order)
    for name, value in style_properties(elem).items():
        offer(name, value, 1000, len(stylesheet_rules))
    return {name: value for name, (_, value) in chosen.items()}


def style_value(elem, name, properties=None):
    properties = properties if properties is not None else style_properties(elem)
    return properties.get(name, elem.get(name))


def opacity_value(value, default=1.0):
    if value is None:
        return default
    try:
        text = str(value).strip()
        opacity = float(text[:-1]) / 100.0 if text.endswith('%') else float(text)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(opacity):
        return default
    return max(0.0, min(1.0, opacity))


def parse_css_color(value):
    value = str(value or '').strip()
    if value.lower() == 'transparent':
        return 0, 0, 0, 0.0
    functional = re.fullmatch(r'rgba?\(\s*(.*?)\s*\)', value, re.I)
    if functional:
        parts = [part for part in re.split(r'\s*,\s*|\s+', functional.group(1)) if part]
        if len(parts) not in (3, 4) or (value[:4].lower() == 'rgba' and len(parts) != 4):
            raise ValueError(f"Unsupported SVG color: {value}")
        def channel(part):
            number = float(part[:-1]) * 255 / 100 if part.endswith('%') else float(part)
            if not math.isfinite(number) or not 0 <= number <= 255:
                raise ValueError(f"Invalid SVG color channel: {part}")
            return round(number)
        rgb = tuple(channel(part) for part in parts[:3])
        if len(parts) == 4:
            try:
                alpha = (float(parts[3][:-1]) / 100 if parts[3].endswith('%')
                         else float(parts[3]))
            except ValueError as exc:
                raise ValueError(f"Invalid SVG alpha: {parts[3]}") from exc
            if not math.isfinite(alpha) or not 0 <= alpha <= 1:
                raise ValueError(f"Invalid SVG alpha: {parts[3]}")
        else:
            alpha = 1.0
        return *rgb, alpha
    try:
        rgba = ImageColor.getrgb(value)
    except (TypeError, ValueError):
        raise ValueError(f"Unsupported SVG color: {value}")
    if len(rgba) == 3:
        return *rgba, 1.0
    return *rgba[:3], rgba[3] / 255.0


def parse_color(elem, inherited_opacity=1.0, inherited_fill_opacity=1.0,
                inherited_fill=None, properties=None, inherited_color=None,
                allow_mask=False):
    r, g, b = 0, 0, 0
    properties = properties if properties is not None else style_properties(elem)
    fill = style_value(elem, 'fill', properties)
    if fill is None or str(fill).strip().lower() == 'inherit':
        fill = inherited_fill
    if fill and str(fill).strip().lower() == 'currentcolor':
        fill = style_value(elem, 'color', properties) or inherited_color or 'black'
        if str(fill).strip().lower() in ('currentcolor', 'inherit'):
            fill = inherited_color or 'black'
    color_alpha = 1.0
    if fill and str(fill).strip().lower().startswith('url('):
        if not allow_mask or not re.fullmatch(r'''url\(\s*['"]?#mask_indicator_(?:dark|light)['"]?\s*\)''', str(fill).strip(), re.I):
            raise ValueError(f"Unsupported SVG paint: {fill}")
        fill = 'white'
    if fill and str(fill).strip().lower() != 'none':
        r, g, b, color_alpha = parse_css_color(fill)

    fill_opacity = opacity_value(
        style_value(elem, 'fill-opacity', properties), inherited_fill_opacity
    )
    object_opacity = opacity_value(style_value(elem, 'opacity', properties))
    raw_a = 255.0 * color_alpha * fill_opacity * object_opacity * inherited_opacity
    a = max(0, min(255, int(round(raw_a))))
    return r, g, b, a


def get_href(elem):
    return elem.get('href') if 'href' in elem.attrib else elem.get(f'{{{XLINK_NS}}}href', '')


def get_local_name(elem):
    return elem.tag.rsplit('}', 1)[-1] if '}' in elem.tag else elem.tag


def parse_float_attr(elem, name, default=0.0):
    raw = elem.get(name)
    if raw is None:
        return default
    return parse_svg_coordinate(raw, name)


def parse_svg_coordinate(raw, name):
    match = re.fullmatch(r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(px|in|cm|mm|pt|pc|q)?\s*', raw, re.I)
    if not match:
        if raw.strip().lower() in ('nan', '+nan', '-nan', 'inf', '+inf', '-inf',
                                    'infinity', '+infinity', '-infinity'):
            raise ValueError(f"SVG {name} contains a non-finite number")
        raise ValueError(f"Unsupported SVG {name} length: {raw}")
    try:
        value = float(match.group(1)) * {'': 1, 'px': 1, 'in': 96,
            'cm': 96 / 2.54, 'mm': 96 / 25.4, 'pt': 96 / 72,
            'pc': 16, 'q': 96 / 101.6}[str(match.group(2) or '').lower()]
    except (TypeError, ValueError):
        raise ValueError(f"Invalid SVG {name} length: {raw}")
    if not math.isfinite(value):
        raise ValueError(f"SVG {name} contains a non-finite number")
    return value


# Transforms

def mult_matrix(M1, M2):
    a1, b1, c1, d1, e1, f1 = M1
    a2, b2, c2, d2, e2, f2 = M2
    return (a1*a2+c1*b2, b1*a2+d1*b2, a1*c2+c1*d2, b1*c2+d1*d2, a1*e2+c1*f2+e1, b1*e2+d1*f2+f1)


def parse_transform(transform_str):
    current_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not transform_str:
        return current_matrix

    number = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?')
    command = re.compile(r'([A-Za-z]+)\s*\(([^()]*)\)')
    pos = 0
    for match in command.finditer(transform_str):
        separator = transform_str[pos:match.start()]
        if pos == 0:
            valid_separator = not separator.strip()
        else:
            valid_separator = bool(re.fullmatch(r'\s+|\s*,\s*', separator))
        if not valid_separator:
            raise ValueError(f"Invalid SVG transform near {transform_str[pos:match.start()]!r}")
        cmd, args = match.groups()
        vals = []
        cursor = 0
        for token in number.finditer(args):
            separator = args[cursor:token.start()]
            if not vals:
                valid_separator = not separator.strip()
            else:
                valid_separator = (bool(re.fullmatch(r'\s+|\s*,\s*', separator))
                                   or (not separator and token.group()[0] in '+-'))
            if not valid_separator:
                raise ValueError(f"Invalid SVG transform arguments: {args!r}")
            vals.append(float(token.group()))
            cursor = token.end()
        if args[cursor:].strip():
            raise ValueError(f"Invalid SVG transform arguments: {args!r}")
        if not all(math.isfinite(value) for value in vals):
            raise ValueError("SVG transform contains a non-finite number")
        if cmd == 'matrix' and len(vals) == 6:
            m = tuple(vals)
        elif cmd == 'translate' and len(vals) in (1, 2):
            m = (1.0, 0.0, 0.0, 1.0, vals[0], vals[1] if len(vals) > 1 else 0.0)
        elif cmd == 'scale' and len(vals) in (1, 2):
            m = (vals[0], 0.0, 0.0, vals[1] if len(vals) > 1 else vals[0], 0.0, 0.0)
        elif cmd == 'rotate' and len(vals) in (1, 3):
            a = math.radians(vals[0])
            ca, sa = math.cos(a), math.sin(a)
            if len(vals) >= 3:
                cx, cy = vals[1], vals[2]
                m = (ca, sa, -sa, ca, cx - cx*ca + cy*sa, cy - cx*sa - cy*ca)
            else:
                m = (ca, sa, -sa, ca, 0.0, 0.0)
        elif cmd == 'skewX' and len(vals) == 1:
            m = (1.0, 0.0, math.tan(math.radians(vals[0])), 1.0, 0.0, 0.0)
        elif cmd == 'skewY' and len(vals) == 1:
            m = (1.0, math.tan(math.radians(vals[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            raise ValueError(f"Unsupported SVG transform: {cmd}({args})")
        current_matrix = mult_matrix(current_matrix, m)
        pos = match.end()
    if transform_str[pos:].strip():
        raise ValueError(f"Invalid SVG transform near {transform_str[pos:]!r}")
    return current_matrix


def parse_svg_length(value, default):
    if value is None:
        return default
    parsed = parse_svg_coordinate(value, 'canvas')
    if parsed <= 0:
        raise ValueError('SVG canvas length must be positive')
    return parsed


def get_svg_canvas(root):
    raw_viewbox = root.get('viewBox')
    if raw_viewbox is not None:
        viewbox = re.split(r'[\s,]+', raw_viewbox.strip())
        if len(viewbox) != 4:
            raise ValueError('Invalid SVG viewBox')
        try:
            canvas_x, canvas_y, canvas_w, canvas_h = map(float, viewbox)
            if (all(math.isfinite(value) for value in
                    (canvas_x, canvas_y, canvas_w, canvas_h))
                    and canvas_w > 0 and canvas_h > 0):
                return canvas_x, canvas_y, canvas_w, canvas_h
        except ValueError:
            raise ValueError('Invalid SVG viewBox')
        raise ValueError('Invalid SVG viewBox')
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
        raise ValueError('SVG transform has a degenerate X scale')
    rot_rad = math.atan2(B, A)
    rot_deg = math.degrees(rot_rad) % 360.0
    sy = -C * math.sin(rot_rad) + D * math.cos(rot_rad)
    if abs(sy) < 1e-6:
        raise ValueError('SVG transform has a degenerate Y scale')
    skew = (C * math.cos(rot_rad) + D * math.sin(rot_rad)) / sy
    result = (tx, ty, sx * scale_factor, sy * scale_factor, rot_deg, skew)
    if not (all(math.isfinite(value) for value in result)
            and abs(tx) < 50000 and abs(ty) < 50000
            and 1e-6 < abs(result[2]) < 200
            and 1e-6 < abs(result[3]) < 5000 and abs(skew) < 200):
        raise ValueError('SVG transform is outside FH6 numeric range')
    try:
        qtx, qty, qsx, qsy, qrot, qskew = struct.unpack('<6f', struct.pack('<6f', *result))
    except (OverflowError, struct.error) as exc:
        raise ValueError('SVG transform cannot be stored as FH6 FP32') from exc
    angle = math.radians(qrot)
    cosine, sine = math.cos(angle), math.sin(angle)
    reconstructed = (qsx * cosine / scale_factor,
                     -qsx * sine / scale_factor,
                     -qsy * (cosine * qskew - sine) / scale_factor,
                     qsy * (sine * qskew + cosine) / scale_factor)
    if any(not math.isclose(expected, actual, rel_tol=2e-5, abs_tol=1e-5)
           for expected, actual in zip((a, b, c, d), reconstructed)):
        raise ValueError('SVG transform loses precision in FH6 parameters')
    return result


# Visibility

def detect_mask_element(elem, pattern_dict, inherited_fill=None, properties=None):
    properties = properties if properties is not None else style_properties(elem)
    fill = style_value(elem, 'fill', properties)
    if fill is None or str(fill).strip().lower() == 'inherit':
        fill = inherited_fill
    match = re.fullmatch(r'''url\(\s*['"]?#([^'"\s)]+)['"]?\s*\)''', str(fill or '').strip(), re.IGNORECASE)
    if not match:
        return False
    reference = f'#{match.group(1)}'
    indicators = {'#mask_indicator_dark', '#mask_indicator_light'}
    seen = set()
    while reference in pattern_dict and reference not in seen:
        if reference in indicators:
            return True
        seen.add(reference)
        reference = pattern_dict[reference]
    return False


def element_visibility(elem, inherited_visibility='visible', properties=None):
    properties = properties if properties is not None else style_properties(elem)
    display = str(style_value(elem, 'display', properties) or '').strip().lower()
    raw_visibility = style_value(elem, 'visibility', properties)
    if raw_visibility is None or str(raw_visibility).strip().lower() == 'inherit':
        visibility = inherited_visibility
    else:
        visibility = str(raw_visibility).strip().lower()
    return display != 'none', visibility


def is_empty_fill(elem, is_mask, inherited_fill=None, properties=None):
    if is_mask:
        return False
    properties = properties if properties is not None else style_properties(elem)
    fill = style_value(elem, 'fill', properties)
    if fill is None or str(fill).strip().lower() == 'inherit':
        fill = inherited_fill
    return str(fill or '').strip().lower() == 'none'


# Parsing

def collect_svg_defs(root):
    """Collect symbol viewBoxes and pattern references from the parsed SVG."""
    symbol_dict, pattern_dict, symbol_extents = {}, {}, {}
    for elem in root.iter():
        local = get_local_name(elem)
        if local == 'symbol':
            symbol_id = elem.get('id')
            viewbox_str = elem.get('viewBox')
            if symbol_id and viewbox_str:
                vb = re.split(r'[\s,]+', viewbox_str.strip())
                if len(vb) == 4:
                    try:
                        values = tuple(map(float, vb))
                    except ValueError:
                        continue
                    if (all(math.isfinite(value) for value in values)
                            and values[2] > 0 and values[3] > 0):
                        symbol_dict[f"#{symbol_id}"] = values[:2]
                        side = max(values[2:])
                        shape_word = _shape_word_from_symbol_id(symbol_id)
                        if shape_word is not None:
                            symbol_extents[shape_word] = (64 * values[2] / side,
                                                          64 * values[3] / side)
        elif local == 'pattern':
            pattern_id = elem.get('id')
            if pattern_id:
                pattern_dict[f"#{pattern_id}"] = get_href(elem)
    return symbol_dict, pattern_dict, symbol_extents


_FH6_SYMBOL_ID = re.compile(r'fh6_t([0-9]+)_i([0-9]+)_w([0-9]+)\Z')


def _shape_word_from_symbol_id(symbol_id):
    match = _FH6_SYMBOL_ID.fullmatch(symbol_id)
    if match is None or int(match.group(1)) == 0 or int(match.group(2)) == 0:
        return None
    return int(match.group(3))


def is_known_fh6_shape_word(word):
    """FH6 families are 40 IDs wide, starting at 101..901 and 1301..3801."""
    family, index = divmod(word - 1, 100)
    return (1 <= family <= 9 or 13 <= family <= 38) and index < 40


def boxes_do_not_overlap(boxes):
    """Check the same conservative AABBs with an X-axis sweep."""
    if any(x0 >= x1 or y0 >= y1 for x0, y0, x1, y1 in boxes):
        # Degenerate boxes have unusual overlap semantics in the original
        # conservative test. Keep them exact; valid shapes use the sweep.
        return all(
            left[2] <= right[0] or right[2] <= left[0]
            or left[3] <= right[1] or right[3] <= left[1]
            for index, left in enumerate(boxes) for right in boxes[:index]
        )
    active_by_y = []
    expiry = []
    for index, (x0, y0, x1, y1) in sorted(enumerate(boxes), key=lambda item: item[1][0]):
        while expiry and expiry[0][0] <= x0:
            _, old_index, old_y0 = heapq.heappop(expiry)
            position = bisect.bisect_left(active_by_y, (old_y0, old_index))
            active_by_y.pop(position)
        position = bisect.bisect_left(active_by_y, (y0, index))
        if position and active_by_y[position - 1][2] > y0:
            return False
        if position < len(active_by_y) and y1 > active_by_y[position][0]:
            return False
        active_by_y.insert(position, (y0, index, y1))
        heapq.heappush(expiry, (x1, index, y0))
    return True


def process_svg(svg_path):
    """Return the model root and FH6 node count."""
    tree = ET.parse(svg_path)
    root = tree.getroot()
    if get_local_name(root) != 'svg':
        raise ValueError('SVG root element is required')
    ids = set()
    for element in root.iter():
        element_id = element.get('id')
        if element_id:
            if element_id in ids:
                raise ValueError('SVG contains duplicate element IDs')
            ids.add(element_id)
    if root.get('transform'):
        raise ValueError('Root SVG transform is not supported')
    aspect = root.get('preserveAspectRatio', 'xMidYMid meet').strip()
    if aspect not in ('', 'xMidYMid meet'):
        raise ValueError(f"Unsupported root preserveAspectRatio: {aspect}")

    canvas_x, canvas_y, canvas_w, canvas_h = get_svg_canvas(root)
    if root.get('viewBox') and ((root.get('width') is None) != (root.get('height') is None)):
        raise ValueError('Root SVG width and height must both be specified')
    if root.get('viewBox') and root.get('width') and root.get('height'):
        viewport_w = parse_svg_length(root.get('width'), canvas_w)
        viewport_h = parse_svg_length(root.get('height'), canvas_h)
        if not math.isclose(viewport_w / viewport_h, canvas_w / canvas_h,
                            rel_tol=1e-9):
            raise ValueError('Root viewport aspect ratio differs from viewBox')

    symbol_dict, pattern_dict, half_extents = collect_svg_defs(root)
    from .cgroup_codec import shape_matrix

    def check_symbol(href):
        if not href.startswith('#'):
            raise ValueError(f"Invalid SVG symbol reference: {href!r}")
        shape_word = _shape_word_from_symbol_id(href[1:])
        if shape_word is None:
            raise ValueError(f"Invalid FH6 symbol ID: {href}")
        if not is_known_fh6_shape_word(shape_word):
            raise ValueError(f"Unknown FH6 ShapeWord: {shape_word}")
        if href not in symbol_dict:
            raise ValueError(f"Missing FH6 symbol definition or viewBox: {href}")
        return shape_word

    def opacity_can_flatten(group):
        boxes = []
        for shape in iter_shapes(group):
            if shape.is_mask:
                return False
            half_x, half_y = half_extents.get(shape.shape_word, (64.0, 64.0))
            a, b, c, d = shape_matrix(shape)
            radius_x = abs(a) * half_x + abs(c) * half_y
            radius_y = abs(b) * half_x + abs(d) * half_y
            box = (shape.tx - radius_x, shape.ty - radius_y,
                   shape.tx + radius_x, shape.ty + radius_y)
            boxes.append(box)
        return boxes_do_not_overlap(boxes)
    stylesheet_rules = collect_stylesheet_rules(root)

    def properties_for(element):
        properties = computed_style(element, stylesheet_rules)
        unsupported = ('transform', 'transform-origin', 'transform-box', 'filter',
                       'clip-path', 'mask', 'mix-blend-mode', 'isolation')
        for name in unsupported:
            value = (properties.get(name) if name == 'transform'
                     else style_value(element, name, properties))
            if value and str(value).strip().lower() not in ('none', 'normal', 'initial'):
                raise ValueError(f"Unsupported SVG {name} on {element.get('id') or get_local_name(element)}")
        stroke = style_value(element, 'stroke', properties)
        if stroke and str(stroke).strip().lower() not in ('none', 'initial'):
            raise ValueError(f"Unsupported SVG stroke on {element.get('id') or get_local_name(element)}")
        return properties

    total_fh6_nodes = 0

    def parse_children(parent, parent_matrix, inherited_opacity=1.0,
                       inherited_fill_opacity=1.0,
                       inherited_fill=None, inherited_visibility='visible',
                       inherited_color='black'):
        nonlocal total_fh6_nodes
        group = GroupNode(name=parent.get('id', ''))

        for elem in parent:
            local = get_local_name(elem)
            if local in ('defs', 'symbol', 'pattern', 'metadata', 'namedview', 'style', 'title', 'desc'):
                continue
            try:
                elem_matrix = mult_matrix(parent_matrix, parse_transform(elem.get('transform', '')))
            except ValueError as exc:
                raise ValueError(f"SVG element {elem.get('id') or local}: {exc}") from exc

            if local in ('g', 'a'):
                properties = properties_for(elem)
                displayed, visibility = element_visibility(
                    elem, inherited_visibility, properties
                )
                if not displayed:
                    continue
                group_opacity = inherited_opacity * opacity_value(
                    style_value(elem, 'opacity', properties)
                )
                group_fill_opacity = opacity_value(
                    style_value(elem, 'fill-opacity', properties), inherited_fill_opacity
                )
                group_fill = style_value(elem, 'fill', properties)
                if group_fill is None or str(group_fill).strip().lower() == 'inherit':
                    group_fill = inherited_fill
                group_color = style_value(elem, 'color', properties)
                if group_color is None or str(group_color).strip().lower() == 'inherit':
                    group_color = inherited_color
                if str(group_color).strip().lower() == 'currentcolor':
                    group_color = inherited_color
                child_group = parse_children(
                    elem, elem_matrix, group_opacity, group_fill_opacity,
                    group_fill, visibility, group_color
                )
                if opacity_value(style_value(elem, 'opacity', properties)) < 1 and not opacity_can_flatten(child_group):
                    raise ValueError(f"Group opacity cannot be represented without compositing: {elem.get('id') or local}")
                if child_group.children:
                    group.children.append(child_group)
                continue

            if local != 'use':
                properties = properties_for(elem)
                displayed, visibility = element_visibility(
                    elem, inherited_visibility, properties)
                if not displayed or (visibility in ('hidden', 'collapse') and not list(elem)):
                    continue
                raise ValueError(f"Unsupported visible SVG element: {elem.get('id') or local}")

            href = get_href(elem)
            shape_word = check_symbol(href)
            if elem.get('width') is not None or elem.get('height') is not None:
                raise ValueError(f"Unsupported use viewport size: {elem.get('id') or href}")

            total_fh6_nodes += 1
            properties = properties_for(elem)
            is_current_mask = detect_mask_element(elem, pattern_dict, inherited_fill, properties)
            displayed, visibility = element_visibility(
                elem, inherited_visibility, properties
            )
            if (not displayed or visibility in ('hidden', 'collapse')
                    or is_empty_fill(elem, is_current_mask, inherited_fill, properties)):
                continue

            r, g, b, a_val = parse_color(
                elem, inherited_opacity, inherited_fill_opacity,
                inherited_fill, properties, inherited_color, is_current_mask
            )
            if a_val == 0:
                continue
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

    root_properties = properties_for(root)
    root_displayed, root_visibility = element_visibility(root, 'visible', root_properties)
    if not root_displayed:
        return GroupNode(name=root.get('id', '')), total_fh6_nodes
    root_opacity = opacity_value(style_value(root, 'opacity', root_properties))
    root_fill_opacity = opacity_value(style_value(root, 'fill-opacity', root_properties))
    root_fill = style_value(root, 'fill', root_properties)
    root_group = parse_children(
        root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        root_opacity, root_fill_opacity, root_fill, root_visibility,
        style_value(root, 'color', root_properties) or 'black'
    )
    if root_opacity < 1 and not opacity_can_flatten(root_group):
        raise ValueError('Root opacity cannot be represented without compositing')
    return root_group, total_fh6_nodes


# Generation

def write_inkscape_svg(tree, svg_path):
    """Write an Inkscape-compatible SVG."""
    ET.register_namespace('', SVG_NS)
    ET.register_namespace('xlink', XLINK_NS)
    root = tree.getroot()
    validate_generated_svg(root)
    ET.indent(tree, space='  ')
    output_dir = os.path.dirname(os.path.abspath(svg_path))
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='wb', dir=output_dir, prefix='.inkscape2forza_',
                suffix='.svg.tmp', delete=False) as temp_file:
            temp_path = temp_file.name
            tree.write(
                temp_file, encoding='utf-8', xml_declaration=True,
                short_empty_elements=True
            )
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, svg_path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def validate_generated_svg(root):
    """Keep exported documents free of private fields and broken references."""
    if root.tag != f'{{{SVG_NS}}}svg':
        raise ValueError('Generated SVG has an invalid root')
    allowed = {'svg', 'defs', 'symbol', 'pattern', 'mask', 'image', 'rect',
               'circle', 'ellipse', 'path', 'polygon', 'polyline', 'line',
               'g', 'use'}
    ids = set()
    symbol_ids = set()
    uses = []
    for element in root.iter():
        local = get_local_name(element)
        if element.tag != f'{{{SVG_NS}}}{local}' or local not in allowed:
            raise ValueError(f'Unsupported generated SVG element: {element.tag}')
        element_id = element.get('id')
        if element_id:
            if element_id in ids:
                raise ValueError(f'Duplicate generated SVG ID: {element_id}')
            ids.add(element_id)
            if local == 'symbol':
                symbol_ids.add(element_id)
        for name in element.attrib:
            namespace = name[1:].split('}', 1)[0] if name.startswith('{') else ''
            if name.startswith('data-') or namespace not in ('', SVG_NS, XLINK_NS):
                raise ValueError(f'Unsupported generated SVG attribute: {name}')
        if local == 'use':
            uses.append(get_href(element))
    for href in uses:
        if not href.startswith('#') or href[1:] not in symbol_ids:
            raise ValueError(f'Unresolved generated SVG reference: {href}')


def create_inkscape_document():
    root = ET.Element(f'{{{SVG_NS}}}svg', {
        'width': '1920', 'height': '1080', 'viewBox': '0 0 1920 1080',
        'version': '1.1', 'id': 'svg1402',
    })
    defs = ET.SubElement(root, f'{{{SVG_NS}}}defs', {'id': 'defs1402'})
    # Avoid an extra FH6 subgroup.
    return ET.ElementTree(root), root, defs


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
    use_elem.set('transform', 'matrix(' + ','.join(format(value, '.9g') for value in
                     (ma, mb, mc, md, me, mf)) + ')')
    use_elem.set('style', f"fill:{fill}; opacity:{opacity};")
    use_elem.set('id', node_id)
    parent.append(use_elem)


def append_svg_shape(parent, shape, href, symbol_dict, canvas_w, canvas_h, node_id,
                     inherited_mask=False):
    svg_cx = canvas_w / 2.0 + shape.tx
    svg_cy = canvas_h / 2.0 - shape.ty
    if inherited_mask or shape.is_mask:
        fill = "url(#mask_indicator_dark)"
    else:
        fill = f"#{shape.r:02x}{shape.g:02x}{shape.b:02x}"
    append_shape_use(parent, href, symbol_dict, svg_cx, svg_cy, shape.sx, shape.sy,
                     shape.rot, fill, format(shape.a / 255.0, '.9g'), node_id, shape.skew)


def append_svg_group(parent, group, href_by_word, symbol_dict, canvas_w, canvas_h,
                     prefix, inherited_mask=False):
    effective_mask = inherited_mask or group.is_mask_group
    g_elem = ET.Element(f'{{{SVG_NS}}}g')
    g_elem.set('id', group.name or prefix)
    parent.append(g_elem)
    for idx, child in enumerate(group.children):
        child_prefix = f"{prefix}_{idx+1}"
        if isinstance(child, GroupNode):
            append_svg_group(
                g_elem, child, href_by_word, symbol_dict, canvas_w, canvas_h,
                child_prefix, effective_mask
            )
        else:
            href = href_by_word.get(child.shape_word)
            if href:
                append_svg_shape(
                    g_elem, child, href, symbol_dict, canvas_w, canvas_h,
                    f"shape_{child_prefix}", effective_mask
                )


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

def export_group_to_svg(root_group, svg_path):
    from .library import add_referenced_defs, load_symbol_library
    from .model import iter_shapes

    symbol_dict, href_by_word, symbol_elements = load_symbol_library()
    missing_words = sorted({
        shape.shape_word for shape in iter_shapes(root_group)
        if shape.shape_word not in href_by_word
    })
    if missing_words:
        formatted = ', '.join(f'0x{word:04x}' for word in missing_words)
        raise ValueError(f"C_group uses unsupported shape IDs: {formatted}")

    tree, root, defs = create_inkscape_document()
    target_container = root
    canvas_w, canvas_h = 1920.0, 1080.0
    for idx, child in enumerate(root_group.children):
        child_prefix = f"forza_{idx+1}"
        if isinstance(child, GroupNode):
            append_svg_group(
                target_container, child, href_by_word, symbol_dict,
                canvas_w, canvas_h, child_prefix, root_group.is_mask_group
            )
        else:
            href = href_by_word.get(child.shape_word)
            append_svg_shape(
                target_container, child, href, symbol_dict, canvas_w, canvas_h,
                f"shape_{child_prefix}", root_group.is_mask_group
            )
    add_referenced_defs(root, defs, symbol_elements)
    write_inkscape_svg(tree, svg_path)


def export_cgroup_to_svg(cgroup_path, svg_path):
    from .cgroup_codec import decode_cgroup_payload, unwrap_cgroup_file

    root_group = decode_cgroup_payload(unwrap_cgroup_file(cgroup_path))
    export_group_to_svg(root_group, svg_path)

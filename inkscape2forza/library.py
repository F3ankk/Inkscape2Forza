"""Cached FH6 symbol and pattern libraries."""
import math
import os
import re
import threading
import xml.etree.ElementTree as ET
from copy import deepcopy

from .common import SVG_NS, XLINK_NS, get_resource_path
from .svg_codec import collect_used_def_ids, get_local_name

_symbol_library_cache = None
_shape_half_extents_cache = None
_pattern_library_cache = None
_symbol_library_lock = threading.Lock()
_symbol_id_pattern = re.compile(r'fh6_t\d+_i\d+_w(\d+)')


def load_symbol_library():
    global _symbol_library_cache
    if _symbol_library_cache is not None:
        return _symbol_library_cache
    with _symbol_library_lock:
        if _symbol_library_cache is not None:
            return _symbol_library_cache
        library_path = get_resource_path('fh6_vinyl_symbols.svg')
        if not os.path.isfile(library_path):
            raise FileNotFoundError('Cannot find fh6_vinyl_symbols.svg')
        library_root = ET.parse(library_path).getroot()
        symbol_dict, href_by_word, elements_by_id = {}, {}, {}
        for elem in library_root.iter():
            if get_local_name(elem) != 'symbol':
                continue
            symbol_id = elem.get('id', '')
            if not symbol_id:
                continue
            elements_by_id[symbol_id] = elem
            view_box = elem.get('viewBox', '').split()
            if len(view_box) == 4:
                try:
                    symbol_dict[f'#{symbol_id}'] = (float(view_box[0]), float(view_box[1]))
                except ValueError:
                    pass
            match = _symbol_id_pattern.search(symbol_id)
            if match:
                href_by_word[int(match.group(1))] = f'#{symbol_id}'
        _symbol_library_cache = (symbol_dict, href_by_word, elements_by_id)
    return _symbol_library_cache


def load_shape_half_extents():
    """Read shape dimensions without parsing the 49 MB symbol definitions."""
    global _shape_half_extents_cache
    if _shape_half_extents_cache is not None:
        return _shape_half_extents_cache
    from ._symbol_index import SYMBOL_INDEX

    extents = {}
    for shape_word, _, _, _, width, height in SYMBOL_INDEX:
        width, height = abs(width), abs(height)
        side = max(width, height)
        if math.isfinite(width) and math.isfinite(height) and side > 0:
            extents[shape_word] = (64.0 * width / side, 64.0 * height / side)
    _shape_half_extents_cache = extents
    return _shape_half_extents_cache


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
    for definition_id in sorted(collect_used_def_ids(root)):
        source = symbol_elements.get(definition_id)
        if source is None:
            source = pattern_elements.get(definition_id)
        if source is not None:
            element = deepcopy(source)
            for child in element.iter():
                for name in tuple(child.attrib):
                    namespace = name[1:].split('}', 1)[0] if name.startswith('{') else ''
                    if name.startswith('data-') or namespace not in (
                            '', SVG_NS, XLINK_NS, 'http://www.w3.org/XML/1998/namespace'):
                        del child.attrib[name]
            for parent in element.iter():
                for child in list(parent):
                    if get_local_name(child) in ('title', 'desc', 'metadata'):
                        parent.remove(child)
            defs.append(element)

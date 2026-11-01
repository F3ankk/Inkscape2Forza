"""FH6 C_group codec and file I/O."""
import ctypes
import base64
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import zlib
import uuid
from ctypes import wintypes

from .common import MAX_VINYL_GROUP_LAYERS
from .model import GroupNode, ShapeNode, count_shapes, iter_shapes

if os.name == 'nt':
    import msvcrt

# Group markers: normal and masked.
GROUP_MARKER_NORMAL = 0x20
GROUP_MARKER_MASK = 0x60
MAX_CGROUP_PAYLOAD_BYTES = 16 * 1024 * 1024
# Fixed shape ID flags.
SHAPE_ID_FIXED_BITS = 0x0200
SHAPE_ID_MASK_BIT = 0x00000001
SHAPE_ID_ALIASES = {2000: 2001, 3000: 3001}

if os.name == 'nt':
    class _FileTime(ctypes.Structure):
        _fields_ = (
            ('low', wintypes.DWORD),
            ('high', wintypes.DWORD),
        )

    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
    _get_file_attributes = _kernel32.GetFileAttributesW
    _get_file_attributes.argtypes = (wintypes.LPCWSTR,)
    _get_file_attributes.restype = wintypes.DWORD
    _set_file_attributes = _kernel32.SetFileAttributesW
    _set_file_attributes.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    _set_file_attributes.restype = wintypes.BOOL
    _set_file_time = _kernel32.SetFileTime
    _set_file_time.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
    )
    _set_file_time.restype = wintypes.BOOL
    _create_file = _kernel32.CreateFileW
    _create_file.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    _create_file.restype = wintypes.HANDLE
    _close_handle = _kernel32.CloseHandle
    _close_handle.argtypes = (wintypes.HANDLE,)
    _close_handle.restype = wintypes.BOOL
    _get_file_security = _advapi32.GetFileSecurityW
    _get_file_security.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    )
    _get_file_security.restype = wintypes.BOOL

_DACL_SECURITY_INFORMATION = 0x00000004
_ERROR_INSUFFICIENT_BUFFER = 122
_FILE_ATTRIBUTE_READONLY = 0x00000001
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_GENERIC_READ = 0x80000000
_FILE_WRITE_ATTRIBUTES = 0x00000100
_FILE_SHARE_ALL = 0x00000007
_OPEN_EXISTING = 3

def build_layer_bytes(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a, is_masked_by_prev=False):
    shape_id = (shape_word << 16) | SHAPE_ID_FIXED_BITS
    if is_masked_by_prev:
        shape_id |= SHAPE_ID_MASK_BIT
    return struct.pack('<IffffffBBBB', shape_id, rot, tx, ty, sx, sy, skew, b, g, r, a)


# Encoding

def encode_shape_node(shape, offset_x=0.0, offset_y=0.0, mark_previous_mask=False,
                      inherited_mask=False, bare=False):
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


def shape_matrix(shape):
    radians = math.radians(shape.rot)
    cos_r, sin_r = math.cos(radians), math.sin(radians)
    return (
        cos_r * shape.sx,
        sin_r * shape.sx,
        shape.sy * (cos_r * shape.skew - sin_r),
        shape.sy * (sin_r * shape.skew + cos_r),
    )


def decompose_linear_matrix(a, b, c, d):
    sx_magnitude = math.hypot(a, b)
    if sx_magnitude <= 1e-12:
        return 0.0, math.hypot(c, d), 0.0, 0.0
    if a * d - b * c < 0.0:
        sx = -sx_magnitude
        radians = math.atan2(-b, -a)
    else:
        sx = sx_magnitude
        radians = math.atan2(b, a)
    cos_r, sin_r = math.cos(radians), math.sin(radians)
    transformed_c = cos_r * c + sin_r * d
    sy = -sin_r * c + cos_r * d
    skew = transformed_c / sy if abs(sy) > 1e-12 else 0.0
    return sx, sy, math.degrees(radians) % 360.0, skew


def validate_model_tree(root_group):
    if not isinstance(root_group, GroupNode):
        raise ValueError("C_group root must be a group")
    seen = set()
    stack = [(root_group, 0)]
    layers = 0
    while stack:
        node, depth = stack.pop()
        node_id = id(node)
        if node_id in seen:
            raise ValueError("C_group model contains a cycle")
        seen.add(node_id)
        if isinstance(node, GroupNode):
            if depth > 128:
                raise ValueError('C_group nesting exceeds the project safety limit of 128')
            if len(node.children) > 0xffff:
                raise ValueError("C_group has too many direct children")
            stack.extend((child, depth + 1) for child in node.children)
            continue
        if not isinstance(node, ShapeNode):
            raise ValueError("C_group model contains an unsupported node")
        layers += 1
        if layers > MAX_VINYL_GROUP_LAYERS:
            raise ValueError(f"C_group exceeds {MAX_VINYL_GROUP_LAYERS} layers")
        if not isinstance(node.shape_word, int) or not 0 <= node.shape_word <= 0xffff:
            raise ValueError("C_group shape ID is out of range")
        node.shape_word = SHAPE_ID_ALIASES.get(node.shape_word, node.shape_word)
        values = (node.rot, node.tx, node.ty, node.sx, node.sy, node.skew)
        if not all(isinstance(value, (int, float)) and math.isfinite(value)
                   for value in values):
            raise ValueError("C_group shape contains a non-finite transform")
        color = (node.r, node.g, node.b, node.a)
        if not all(isinstance(value, int) and 0 <= value <= 255 for value in color):
            raise ValueError("C_group shape color is out of range")
    if layers == 0:
        raise ValueError("SVG has no valid Forza layers")


def node_metrics(node, shape_half_extents=None):
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    all_masked = True
    for shape in iter_shapes(node):
        all_masked = all_masked and shape.is_mask
        half_x, half_y = (shape_half_extents or {}).get(shape.shape_word, (64.0, 64.0))
        if not all(math.isfinite(value) and value > 0 for value in (half_x, half_y)):
            half_x = half_y = 64.0
        a, b, c, d = shape_matrix(shape)
        for x, y in ((-half_x, -half_y), (half_x, -half_y),
                     (half_x, half_y), (-half_x, half_y)):
            px = shape.tx + a * x + c * y
            py = shape.ty + b * x + d * y
            min_x = min(min_x, px)
            max_x = max(max_x, px)
            min_y = min(min_y, py)
            max_y = max(max_y, py)
    if min_x == float("inf"):
        return (0.0, 0.0), False
    return ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0), all_masked


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


def encode_group_node(group, parent_offset=(0.0, 0.0), transform_marker=b'\x03',
                      inherited_mask=False, shape_half_extents=None):
    children = group.children
    bitmap = child_bitmap(children)
    origin, all_masked = node_metrics(group, shape_half_extents)
    is_mask_group = group.is_mask_group or all_masked
    marker = GROUP_MARKER_MASK if is_mask_group else GROUP_MARKER_NORMAL
    group.tx, group.ty = origin
    out = bytearray(pack_translation_transform(origin[0] - parent_offset[0], origin[1] - parent_offset[1], transform_marker))
    out.extend(struct.pack('<BHHH', marker, len(children), len(bitmap), 0))
    out.extend(bitmap)
    child_bytes, final_mask = encode_children(
        children, origin, inherited_mask or is_mask_group, shape_half_extents
    )
    out.extend(child_bytes)
    return bytes(out), final_mask


def child_bitmap(children):
    blocks = (len(children) + 7) // 8
    bitmap = bytearray(blocks)
    for idx, child in enumerate(children):
        if isinstance(child, GroupNode):
            bitmap[idx // 8] |= (1 << (idx % 8))
    return bytes(bitmap)


def encode_children(children, parent_offset=(0.0, 0.0), inherited_mask=False,
                    shape_half_extents=None):
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
            group_bytes, group_final_mask = encode_group_node(
                child, parent_offset, transform_marker, inherited_mask, shape_half_extents
            )
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


def build_cgroup_payload(root_group, shape_half_extents=None):
    validate_model_tree(root_group)
    normalize_groups(root_group)
    validate_model_tree(root_group)
    children = root_group.children
    bitmap = child_bitmap(children)
    root_origin, _ = node_metrics(root_group, shape_half_extents)
    payload = bytearray()
    payload.extend(b'gyvl')
    payload.extend(struct.pack('<II', 1, 0))
    payload.extend(struct.pack('<Bffff', 0x03, 0.0, 0.0, 1.0, 0.0))
    payload.extend(struct.pack('<BHH2s', GROUP_MARKER_NORMAL, len(children), len(bitmap), b'\x00\x00'))
    payload.extend(bitmap)
    child_bytes, final_mask = encode_children(
        children, root_origin, root_group.is_mask_group, shape_half_extents
    )
    payload.extend(child_bytes)
    payload.extend(b'\x01' if final_mask else b'\x00')
    terminal = terminal_depth(children[-1]) if isinstance(children[-1], GroupNode) else 0
    payload.extend(b'\x01' * (terminal + 1))
    return bytes(payload)


def wrap_cgroup_payload(payload):
    compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=zlib.MAX_WBITS,
                                  memLevel=8, strategy=zlib.Z_DEFAULT_STRATEGY)
    zstream = compressor.compress(payload) + compressor.flush()
    return struct.pack('<II', len(zstream), len(payload)) + zstream


# File I/O

def update_header_layer_count(header_data, layer_count):
    """Update the header leaf count."""
    if not 0 <= layer_count <= MAX_VINYL_GROUP_LAYERS:
        raise ValueError(f"Invalid vinyl group layer count: {layer_count}")

    def require(size, offset, label):
        if offset < 0 or offset + size > len(header_data):
            raise ValueError(f"C_group header is truncated at {label}")

    require(8, 0, "name header")
    if struct.unpack_from('<I', header_data, 0)[0] != 7:
        raise ValueError('Only FH6 Header v7 can be modified')
    name_length = struct.unpack_from('<I', header_data, 4)[0]
    if name_length > 4096:
        raise ValueError('Header name length is invalid')
    offset = 8 + name_length * 2

    require(4, offset, "description length")
    description_length = struct.unpack_from('<I', header_data, offset)[0]
    if description_length > 16384:
        raise ValueError('Header description length is invalid')
    offset += 4 + description_length * 2

    require(28, offset, 'date and asset metadata')
    if struct.unpack_from('<I', header_data, offset + 16)[0] != 2:
        raise ValueError('Header asset type is not a vinyl group')
    offset += 4 + 16 + 8
    require(4, offset, "creator length")
    creator_length = struct.unpack_from('<I', header_data, offset)[0]
    if creator_length > 4096:
        raise ValueError('Header creator length is invalid')
    offset += 4 + creator_length * 2

    section_marker_offset = offset + 28
    require(9 + 4, section_marker_offset, "section metadata")
    if header_data[section_marker_offset:section_marker_offset + 2] != b'\x01\x02':
        raise ValueError("C_group header section marker is invalid")
    if header_data[section_marker_offset + 2:section_marker_offset + 9] != b'\x00' * 7:
        raise ValueError('C_group Header v7 padding is invalid')
    layer_count_offset = section_marker_offset + 9
    require(20, layer_count_offset, 'layer count and GUID')
    if header_data[layer_count_offset + 4:layer_count_offset + 20] == b'\x00' * 16:
        raise ValueError('C_group Header GUID is empty')
    updated = bytearray(header_data)
    struct.pack_into('<I', updated, layer_count_offset, layer_count)
    return bytes(updated)


def snapshot_file_metadata(path):
    stat_result = os.stat(path)
    attributes = None
    dacl = None
    if os.name == 'nt':
        absolute_path = os.path.abspath(path)
        attributes = _get_file_attributes(absolute_path)
        if attributes == 0xffffffff:
            raise ctypes.WinError(ctypes.get_last_error())
        required = wintypes.DWORD()
        ctypes.set_last_error(0)
        _get_file_security(
            absolute_path, _DACL_SECURITY_INFORMATION,
            None, 0, ctypes.byref(required),
        )
        error = ctypes.get_last_error()
        if not required.value or error != _ERROR_INSUFFICIENT_BUFFER:
            raise ctypes.WinError(error)
        descriptor = ctypes.create_string_buffer(required.value)
        if not _get_file_security(
                absolute_path, _DACL_SECURITY_INFORMATION,
                descriptor, required.value, ctypes.byref(required)):
            raise ctypes.WinError(ctypes.get_last_error())
        dacl = descriptor.raw[:required.value]
    return {
        'file_id': stat_result.st_ino,
        'atime_ns': stat_result.st_atime_ns,
        'mtime_ns': stat_result.st_mtime_ns,
        'birthtime_ns': getattr(stat_result, 'st_birthtime_ns', None),
        'attributes': attributes,
        'dacl': dacl,
    }


def prevent_automatic_time_updates(file_obj, access=True, write=False):
    if os.name != 'nt':
        return
    unchanged = _FileTime(0xffffffff, 0xffffffff)
    access_time = ctypes.byref(unchanged) if access else None
    write_time = ctypes.byref(unchanged) if write else None
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(file_obj.fileno()))
    if not _set_file_time(handle, None, access_time, write_time):
        raise ctypes.WinError(ctypes.get_last_error())


def read_file_read_only(path):
    if os.name == 'nt':
        handle = _create_file(
            os.path.abspath(path), _GENERIC_READ | _FILE_WRITE_ATTRIBUTES,
            _FILE_SHARE_ALL, None, _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, None,
        )
        if handle != wintypes.HANDLE(-1).value:
            unchanged = _FileTime(0xffffffff, 0xffffffff)
            if _set_file_time(handle, None, ctypes.byref(unchanged), None):
                try:
                    descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                except Exception:
                    _close_handle(handle)
                    raise
                with os.fdopen(descriptor, 'rb') as file_obj:
                    return file_obj.read()
            _close_handle(handle)
    with open(path, 'rb') as file_obj:
        return file_obj.read()


def _filetime_from_ns(timestamp_ns):
    ticks = timestamp_ns // 100 + 116444736000000000
    return _FileTime(ticks & 0xffffffff, ticks >> 32)


def restore_file_metadata(path, metadata):
    absolute_path = os.path.abspath(path)
    if os.name == 'nt':
        with open(path, 'r+b') as file_obj:
            handle = wintypes.HANDLE(msvcrt.get_osfhandle(file_obj.fileno()))
            creation = (_filetime_from_ns(metadata['birthtime_ns'])
                        if metadata['birthtime_ns'] is not None else None)
            access = _filetime_from_ns(metadata['atime_ns'])
            write = _filetime_from_ns(metadata['mtime_ns'])
            if not _set_file_time(
                    handle,
                    ctypes.byref(creation) if creation is not None else None,
                    ctypes.byref(access), ctypes.byref(write)):
                raise ctypes.WinError(ctypes.get_last_error())
        if not _set_file_attributes(absolute_path, metadata['attributes']):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.utime(path, ns=(metadata['atime_ns'], metadata['mtime_ns']))
    current_metadata = snapshot_file_metadata(path)
    if current_metadata['file_id'] != metadata['file_id']:
        raise OSError("Failed to preserve file identity")
    birthtime_ns = metadata['birthtime_ns']
    if (birthtime_ns is not None
            and current_metadata['birthtime_ns'] != birthtime_ns):
        raise OSError("Failed to preserve file creation time")
    if os.name == 'nt':
        if current_metadata['attributes'] != metadata['attributes']:
            raise OSError("Failed to preserve Windows file attributes")
        if current_metadata['dacl'] != metadata['dacl']:
            raise OSError("Failed to preserve file permissions")
    if current_metadata['atime_ns'] != metadata['atime_ns']:
        raise OSError("Failed to preserve file access time")
    if current_metadata['mtime_ns'] != metadata['mtime_ns']:
        raise OSError("Failed to preserve file modification time")


def overwrite_file_preserving_metadata(target, replacement, metadata):
    attributes_changed = False
    if os.name == 'nt' and metadata['attributes'] & _FILE_ATTRIBUTE_READONLY:
        writable_attributes = metadata['attributes'] & ~_FILE_ATTRIBUTE_READONLY
        if writable_attributes == 0:
            writable_attributes = _FILE_ATTRIBUTE_NORMAL
        if not _set_file_attributes(os.path.abspath(target), writable_attributes):
            raise ctypes.WinError(ctypes.get_last_error())
        attributes_changed = True
    try:
        with open(replacement, 'rb') as source, open(target, 'r+b') as destination:
            prevent_automatic_time_updates(destination, access=True, write=True)
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.truncate()
            destination.flush()
            os.fsync(destination.fileno())
        restore_file_metadata(target, metadata)
    except Exception:
        if attributes_changed:
            _set_file_attributes(os.path.abspath(target), metadata['attributes'])
        raise


def _recovery_base(target_cgroup):
    key = hashlib.sha256(os.path.normcase(os.path.abspath(target_cgroup)).encode('utf-8')).hexdigest()[:24]
    return Path.home() / '.inkscape2forza' / 'recovery' / key


@contextlib.contextmanager
def _save_lock(target_cgroup):
    base = _recovery_base(target_cgroup)
    base.mkdir(parents=True, exist_ok=True)
    with open(base / 'write.lock', 'a+b') as lock:
        lock.seek(0)
        if lock.read(1) == b'':
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another Inkscape2Forza save write is in progress') from exc
        try:
            yield base
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write_durable(path, data):
    with open(path, 'wb') as file_obj:
        file_obj.write(data)
        file_obj.flush()
        os.fsync(file_obj.fileno())


def _write_journal(directory, journal):
    temporary = directory / 'journal.tmp'
    _write_durable(temporary, json.dumps(journal, sort_keys=True).encode('utf-8'))
    os.replace(temporary, directory / 'journal.json')


def _json_metadata(metadata):
    result = dict(metadata)
    result['dacl'] = base64.b64encode(metadata['dacl']).decode('ascii') if metadata['dacl'] else None
    return result


def _restore_transaction(directory, journal):
    originals = {}
    for name in ('C_group', 'header'):
        info = journal['files'][name]
        source = directory / (name + '.original')
        original = source.read_bytes()
        if hashlib.sha256(original).hexdigest() != info['sha256']:
            raise RuntimeError(f'Recovery copy is damaged: {source}')
        originals[name] = original
    for name in ('C_group', 'header'):
        info = journal['files'][name]
        source = directory / (name + '.original')
        metadata = dict(info['metadata'])
        metadata['dacl'] = base64.b64decode(metadata['dacl']) if metadata['dacl'] else None
        overwrite_file_preserving_metadata(info['path'], source, metadata)
        if read_file_read_only(info['path']) != originals[name]:
            raise RuntimeError(f'Recovery verification failed: {info["path"]}')
    journal['state'] = 'rolled_back'
    _write_journal(directory, journal)


def _recover_pending_locked(target_cgroup, base):
    for directory in sorted(base.iterdir()):
        journal_path = directory / 'journal.json'
        if not directory.is_dir() or not journal_path.is_file():
            continue
        journal = json.loads(journal_path.read_text(encoding='utf-8'))
        if journal['state'] != 'prepared':
            continue
        if (journal['files']['C_group']['path'] != os.path.abspath(target_cgroup)
                or journal['files']['header']['path'] != os.path.join(
                    os.path.dirname(os.path.abspath(target_cgroup)), 'header')):
            raise RuntimeError(f'Recovery target mismatch: {directory}')
        try:
            _restore_transaction(directory, journal)
        except Exception as exc:
            raise RuntimeError(f'Unfinished save could not be recovered; copies remain in {directory}: {exc}') from exc


def recover_pending_cgroup(target_cgroup):
    """Restore both original files from any interrupted transaction."""
    with _save_lock(target_cgroup) as base:
        _recover_pending_locked(target_cgroup, base)


def _assert_encoded_model(expected, actual):
    def structure(node):
        if isinstance(node, ShapeNode):
            return 'shape'
        return tuple(structure(child) for child in node.children)
    if structure(expected) != structure(actual):
        raise ValueError('Generated C_group nesting/order mismatch')
    left, right = list(iter_shapes(expected)), list(iter_shapes(actual))
    if len(left) != len(right):
        raise ValueError('Generated C_group layer count mismatch')
    delta = ((right[0].tx - left[0].tx), (right[0].ty - left[0].ty))
    for index, (before, after) in enumerate(zip(left, right), 1):
        if (before.shape_word, before.r, before.g, before.b, before.a, before.is_mask) != (
                after.shape_word, after.r, after.g, after.b, after.a, after.is_mask):
            raise ValueError(f'Generated C_group layer {index} identity/color/mask mismatch')
        actual_values = (*shape_matrix(after), after.tx - delta[0], after.ty - delta[1])
        expected_values = (*shape_matrix(before), before.tx, before.ty)
        if any(not math.isclose(a, b, rel_tol=2e-5, abs_tol=2e-3)
               for a, b in zip(actual_values, expected_values)):
            raise ValueError(f'Generated C_group layer {index} transform mismatch')


def write_cgroup_file(target_cgroup, root_group, shape_half_extents=None):
    """Write both registered files with durable original copies and recovery state."""
    target_cgroup = os.path.abspath(target_cgroup)
    header_path = os.path.join(os.path.dirname(target_cgroup), 'header')
    with _save_lock(target_cgroup) as base:
        _recover_pending_locked(target_cgroup, base)
        paths = {'C_group': target_cgroup, 'header': header_path}
        old = {name: read_file_read_only(path) for name, path in paths.items()}
        metadata = {name: snapshot_file_metadata(path) for name, path in paths.items()}
        decode_cgroup_payload(validate_cgroup_data(old['C_group']))
        layer_count = count_shapes(root_group)
        new = {
            'C_group': wrap_cgroup_payload(build_cgroup_payload(root_group, shape_half_extents)),
            'header': update_header_layer_count(old['header'], layer_count),
        }
        _assert_encoded_model(root_group, decode_cgroup_payload(validate_cgroup_data(new['C_group'])))
        directory = base / uuid.uuid4().hex
        directory.mkdir()
        journal = {'state': 'prepared', 'files': {}}
        for name, path in paths.items():
            _write_durable(directory / (name + '.original'), old[name])
            _write_durable(directory / (name + '.new'), new[name])
            journal['files'][name] = {
                'path': path, 'sha256': hashlib.sha256(old[name]).hexdigest(),
                'metadata': _json_metadata(metadata[name]),
            }
        for name in paths:
            if ((directory / (name + '.original')).read_bytes() != old[name]
                    or (directory / (name + '.new')).read_bytes() != new[name]):
                raise RuntimeError(f'Transaction copy verification failed: {name}')
        _write_journal(directory, journal)
        try:
            for name, path in paths.items():
                current = snapshot_file_metadata(path)
                if read_file_read_only(path) != old[name] or any(
                        current[key] != metadata[name][key]
                        for key in ('file_id', 'mtime_ns', 'birthtime_ns', 'attributes', 'dacl')):
                    raise RuntimeError(f'{name} changed during preparation')
                overwrite_file_preserving_metadata(path, directory / (name + '.new'), metadata[name])
                actual = read_file_read_only(path)
                if (len(actual) != len(new[name])
                        or hashlib.sha256(actual).digest() != hashlib.sha256(new[name]).digest()):
                    raise RuntimeError(f'{name} did not match after write')
            final_cgroup = read_file_read_only(target_cgroup)
            if hashlib.sha256(final_cgroup).digest() != hashlib.sha256(new['C_group']).digest():
                raise RuntimeError('C_group changed during final verification')
            actual_payload = validate_cgroup_data(final_cgroup)
            _assert_encoded_model(root_group, decode_cgroup_payload(actual_payload))
            actual_header = read_file_read_only(header_path)
            if (len(actual_header) != len(new['header'])
                    or hashlib.sha256(actual_header).digest()
                    != hashlib.sha256(new['header']).digest()):
                raise RuntimeError('Header did not match after write')
            for name, path in paths.items():
                current = snapshot_file_metadata(path)
                if any(current[key] != metadata[name][key]
                       for key in ('file_id', 'mtime_ns', 'birthtime_ns', 'attributes', 'dacl')):
                    raise RuntimeError(f'{name} identity or metadata changed after write')
            journal['state'] = 'committed'
            _write_journal(directory, journal)
        except Exception as write_error:
            try:
                _restore_transaction(directory, journal)
            except Exception as recovery_error:
                raise RuntimeError(f'Save failed; recovery copies retained in {directory}: {recovery_error}') from write_error
            raise


# Decoding

def read_u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def read_utf16(data, offset, char_count):
    return data[offset:offset + char_count*2].decode("utf-16le", errors="replace").strip("\x00"), offset + char_count*2


def parse_header(header_path):
    try:
        data = read_file_read_only(header_path)
        if len(data) < 8:
            return "Error", "Error"
        magic, off = read_u32(data, 0)
        if magic != 7:
            return "Invalid Magic", "Unknown"

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


def validate_cgroup_data(data):
    """Validate the wrapper, zlib stream, length, and root."""
    if len(data) < 8:
        raise ValueError("C_group file is too small")
    comp_len, uncomp_len = struct.unpack_from('<II', data, 0)
    if (comp_len <= 0 or uncomp_len <= 0 or uncomp_len > MAX_CGROUP_PAYLOAD_BYTES
            or comp_len != len(data) - 8):
        raise ValueError("Invalid C_group container")
    stream = zlib.decompressobj()
    payload = stream.decompress(data[8:], MAX_CGROUP_PAYLOAD_BYTES + 1)
    if len(payload) > MAX_CGROUP_PAYLOAD_BYTES or stream.unconsumed_tail:
        raise ValueError("C_group payload is too large")
    payload += stream.flush()
    if not stream.eof or stream.unused_data:
        raise ValueError("Invalid C_group compressed stream")
    if len(payload) != uncomp_len:
        raise ValueError("C_group uncompressed length mismatch")
    if len(payload) <= 0x1d or payload[:4] != b'gyvl':
        raise ValueError("Invalid C_group magic")
    if struct.unpack_from('<I', payload, 4)[0] != 1:
        raise ValueError('Unsupported C_group payload version')
    if payload[0x1d] not in (GROUP_MARKER_NORMAL, GROUP_MARKER_MASK):
        raise ValueError("Invalid C_group root marker")
    if len(payload) < 0x24:
        raise ValueError("Truncated C_group root header")
    root_marker = payload[0x0c]
    if root_marker not in (0x02, 0x03):
        raise ValueError("Unsupported root transform marker")
    px, py, scale, rot = struct.unpack_from('<ffff', payload, 0x0d)
    if not (all(math.isfinite(value) for value in (px, py, scale, rot))
            and abs(px) < 50000.0 and abs(py) < 50000.0
            and 0.0001 <= abs(scale) <= 200.0 and abs(rot) <= 10000.0):
        raise ValueError("Invalid root transform")
    count = struct.unpack_from('<H', payload, 0x1e)[0]
    blocks = struct.unpack_from('<H', payload, 0x20)[0]
    if count <= 0 or blocks != (count + 7) // 8 or 0x24 + blocks > len(payload):
        raise ValueError("Invalid root child bitmap")
    return payload


def unwrap_cgroup_file(cgroup_path):
    data = read_file_read_only(cgroup_path)
    return validate_cgroup_data(data)


def parse_shape_record(data, offset, shape_marker=0x02):
    if offset >= len(data):
        raise ValueError(f"Missing shape record at 0x{offset:x}")
    lead = data[offset]
    if (lead in (0x00, 0x01) and offset + 32 <= len(data)
            and data[offset + 1] == shape_marker):
        encoded_word = struct.unpack_from('<H', data, offset + 2)[0]
        shape_word = SHAPE_ID_ALIASES.get(encoded_word, encoded_word)
        rot, tx, ty, sx, sy, skew = struct.unpack_from('<ffffff', data, offset + 4)
        b, g, r, a = struct.unpack_from('<BBBB', data, offset + 28)
        next_offset = offset + 32
        marks_previous = lead == 0x01
    elif lead == shape_marker and offset + 31 <= len(data):
        encoded_word = struct.unpack_from('<H', data, offset + 1)[0]
        shape_word = SHAPE_ID_ALIASES.get(encoded_word, encoded_word)
        rot, tx, ty, sx, sy, skew = struct.unpack_from('<ffffff', data, offset + 3)
        b, g, r, a = struct.unpack_from('<BBBB', data, offset + 27)
        next_offset = offset + 31
        marks_previous = False
    else:
        raise ValueError(f"Unsupported shape record at 0x{offset:x}")
    values = (rot, tx, ty, sx, sy, skew)
    if not (all(math.isfinite(value) for value in values)
            and abs(rot) <= 10000.0 and abs(tx) < 50000.0 and abs(ty) < 50000.0
            and 1e-6 < abs(sx) < 200.0 and 1e-6 < abs(sy) < 5000.0
            and abs(skew) < 200.0):
        raise ValueError(f"Invalid shape transform at 0x{offset:x}")
    return (
        ShapeNode(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a, False),
        next_offset, marks_previous,
    )


def transform_markers_at(data, offset, terminator=0x03):
    markers = []
    if offset >= len(data):
        return markers
    if data[offset] == 0x00:
        cursor = offset + 1
        while cursor < len(data) and data[cursor] == 0x01:
            cursor += 1
        if cursor < len(data) and data[cursor] == terminator:
            markers.append(bytes(data[offset:cursor + 1]))
    lead = data[offset]
    if lead & 0x01:
        if (offset + 3 <= len(data)
                and data[offset + 1] == terminator
                and data[offset + 2] == terminator):
            markers.append(bytes(data[offset:offset + 3]))
        if offset + 2 <= len(data) and data[offset + 1] == terminator:
            markers.append(bytes(data[offset:offset + 2]))
    if lead == terminator and offset + 2 <= len(data) and data[offset + 1] == terminator:
        markers.append(bytes(data[offset:offset + 2]))
    if lead == terminator:
        markers.append(bytes(data[offset:offset + 1]))
    return sorted(set(markers), key=len, reverse=True)


def parse_optional_transform_record(data, offset, terminator=0x03):
    for marker in transform_markers_at(data, offset, terminator):
        end = offset + len(marker)
        payload_end = end + 16
        if payload_end <= len(data):
            px, py, scale_x, rot = struct.unpack_from('<ffff', data, end)
            if not (all(math.isfinite(value) for value in (px, py, scale_x, rot))
                    and abs(px) < 50000.0 and abs(py) < 50000.0
                    and 0.0001 <= abs(scale_x) <= 200.0 and abs(rot) <= 10000.0):
                continue
            scale_y = scale_x
            next_offset = payload_end
            if next_offset + 5 <= len(data) and data[next_offset] in (0x30, 0x70):
                scale_y = struct.unpack_from('<f', data, next_offset + 1)[0]
                if not math.isfinite(scale_y) or not 0.0001 <= abs(scale_y) <= 5000.0:
                    continue
                next_offset += 5
            return (px, py, scale_x, scale_y, rot), next_offset, marker
    return None, offset, b''


def skip_group_to_shape_control(data, offset, shape_marker=0x02):
    start = offset
    while offset < len(data) and data[offset] in (0x00, 0x01):
        try:
            parse_shape_record(data, offset, shape_marker)
            break
        except ValueError:
            pass
        offset += 1
    control = data[start:offset]
    if control and (control[0] != 0 or any(byte != 1 for byte in control[1:])
                    or len(control) > 129):
        raise ValueError(f'Invalid group-to-shape control at 0x{start:x}')
    return offset


def apply_group_transform_to_shape(shape, transform):
    px, py, scale_x, scale_y, rot = transform
    rad = math.radians(rot)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    pa, pb = cos_r * scale_x, sin_r * scale_x
    pc, pd = -sin_r * scale_y, cos_r * scale_y
    shape.tx, shape.ty = (
        px + pa * shape.tx + pc * shape.ty,
        py + pb * shape.tx + pd * shape.ty,
    )
    ca, cb, cc, cd = shape_matrix(shape)
    a, b = pa * ca + pc * cb, pb * ca + pd * cb
    c, d = pa * cc + pc * cd, pb * cc + pd * cd
    shape.sx, shape.sy, shape.rot, shape.skew = decompose_linear_matrix(a, b, c, d)


def apply_group_transform(group, transform):
    for child in group.children:
        if isinstance(child, GroupNode):
            apply_group_transform(child, transform)
        else:
            apply_group_transform_to_shape(child, transform)


def terminal_shape(node):
    current = node
    while isinstance(current, GroupNode):
        if not current.children:
            return None
        current = current.children[-1]
    return current if isinstance(current, ShapeNode) else None


def mark_previous_mask(children, through_groups=False):
    if not children:
        return
    previous = children[-1]
    if isinstance(previous, GroupNode) and not through_groups:
        return
    shape = terminal_shape(previous)
    # FH6 trailing control bytes can also describe a normal colored shape.
    # The reference flattener treats only grayscale RGB as a direct mask.
    if shape is not None and shape.r == shape.g == shape.b:
        shape.is_mask = True


def decode_children(data, offset, count, bitmap, inherited_mask=False,
                    shape_marker=0x02, transform_terminator=0x03,
                    trailing_mask_state=True):
    children = []
    for idx in range(count):
        is_group = bool(bitmap[idx // 8] & (1 << (idx % 8))) if bitmap else False
        if is_group:
            transform, offset, transform_marker = parse_optional_transform_record(
                data, offset, transform_terminator
            )
            if (trailing_mask_state and transform_marker
                    and transform_marker[0] & 0x01):
                mark_previous_mask(children, through_groups=True)
            if (transform is None and (offset >= len(data) or data[offset] not in (
                    GROUP_MARKER_NORMAL, GROUP_MARKER_MASK))):
                raise ValueError(f"Markerless group without transform at 0x{offset:x}")
            child, offset = decode_group_record(
                data, offset, inherited_mask, shape_marker,
                transform_terminator, trailing_mask_state
            )
            if transform:
                apply_group_transform(child, transform)
            children.append(child)
        else:
            offset = skip_group_to_shape_control(
                data, offset, shape_marker
            )
            shape, offset, marks_previous = parse_shape_record(data, offset, shape_marker)
            if trailing_mask_state and marks_previous:
                mark_previous_mask(children)
            shape.is_mask = inherited_mask
            children.append(shape)

    if (trailing_mask_state and offset < len(data) and data[offset] == 0x01
            and (offset + 1 >= len(data) or data[offset + 1] != shape_marker)):
        mark_previous_mask(children, through_groups=True)
        offset += 1
    return children, offset


def decode_group_record(data, offset, inherited_mask=False, shape_marker=0x02,
                        transform_terminator=0x03, trailing_mask_state=True):
    if offset >= len(data):
        raise ValueError(f"Missing group record at 0x{offset:x}")
    marker = data[offset]
    if marker in (GROUP_MARKER_NORMAL, GROUP_MARKER_MASK):
        if offset + 7 > len(data):
            raise ValueError(f"Truncated group header at 0x{offset:x}")
        count = struct.unpack_from('<H', data, offset + 1)[0]
        blocks = struct.unpack_from('<H', data, offset + 3)[0]
        bitmap_start = offset + 7
    else:
        marker = GROUP_MARKER_NORMAL
        if offset + 6 > len(data):
            raise ValueError(f"Truncated markerless group at 0x{offset:x}")
        count = struct.unpack_from('<H', data, offset)[0]
        blocks = struct.unpack_from('<H', data, offset + 2)[0]
        bitmap_start = offset + 6
    expected_blocks = (count + 7) // 8
    if count <= 0 or blocks != expected_blocks:
        raise ValueError(f"Invalid group child bitmap at 0x{offset:x}")
    if bitmap_start + blocks > len(data):
        raise ValueError(f"Truncated group bitmap at 0x{offset:x}")
    bitmap = data[bitmap_start:bitmap_start + blocks]
    child_offset = bitmap_start + blocks
    group_transform = None
    if not (bitmap[0] & 0x01):
        candidate, candidate_offset, _ = parse_optional_transform_record(
            data, child_offset, transform_terminator
        )
        if candidate is not None:
            shape_offset = skip_group_to_shape_control(
                data, candidate_offset, shape_marker
            )
            try:
                parse_shape_record(data, shape_offset, shape_marker)
            except ValueError:
                pass
            else:
                group_transform = candidate
                child_offset = candidate_offset
    group = GroupNode(is_mask_group=(marker == GROUP_MARKER_MASK) or inherited_mask)
    group.children, child_offset = decode_children(
        data, child_offset, count, bitmap, group.is_mask_group,
        shape_marker, transform_terminator, trailing_mask_state
    )
    if group_transform is not None:
        apply_group_transform(group, group_transform)
    return group, child_offset


def decode_cgroup_payload(payload):
    if len(payload) < 0x24 or payload[:4] != b'gyvl':
        raise ValueError("Invalid C_group payload")
    root_transform_marker = payload[0x0c]
    if root_transform_marker not in (0x02, 0x03):
        raise ValueError("Unsupported root transform marker")
    root_offset = 0x1d
    root_marker = payload[root_offset]
    if root_marker not in (GROUP_MARKER_NORMAL, GROUP_MARKER_MASK):
        raise ValueError("Unsupported root group marker")
    count = struct.unpack_from('<H', payload, root_offset + 1)[0]
    blocks = struct.unpack_from('<H', payload, root_offset + 3)[0]
    expected_blocks = (count + 7) // 8
    if count <= 0 or blocks != expected_blocks:
        raise ValueError("Invalid root child bitmap")
    bitmap_start = root_offset + 7
    if bitmap_start + blocks > len(payload):
        raise ValueError("Truncated root child bitmap")
    bitmap = payload[bitmap_start:bitmap_start + blocks]
    generation2 = root_transform_marker == 0x02
    children, end = decode_children(
        payload, bitmap_start + blocks, count, bitmap,
        root_marker == GROUP_MARKER_MASK,
        0x01 if generation2 else 0x02,
        0x02 if generation2 else 0x03,
        not generation2,
    )
    tail = payload[end:]
    if not tail or (tail[0] not in (0, 1)) or any(byte != 1 for byte in tail[1:]):
        raise ValueError(f'Unexpected C_group trailing data at 0x{end:x}')
    root = GroupNode(
        children=children,
        is_mask_group=(root_marker == GROUP_MARKER_MASK),
        name="root",
    )
    px, py, scale, rot = struct.unpack_from('<ffff', payload, 0x0d)
    root_transform = (px, py, scale, scale, rot)
    if not (all(math.isfinite(value) for value in root_transform)
            and abs(px) < 50000.0 and abs(py) < 50000.0
            and 0.0001 <= abs(scale) <= 200.0 and abs(rot) <= 10000.0):
        raise ValueError("Invalid root transform")
    apply_group_transform(root, root_transform)
    if count_shapes(root) > MAX_VINYL_GROUP_LAYERS:
        raise ValueError(f"C_group exceeds {MAX_VINYL_GROUP_LAYERS} layers")
    return root

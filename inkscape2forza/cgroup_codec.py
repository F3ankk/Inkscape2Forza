"""FH6 C_group codec and file I/O."""
import math
import os
import shutil
import struct
import zlib

from .common import MAX_VINYL_GROUP_LAYERS
from .model import GroupNode, ShapeNode, count_shapes, iter_shapes

# Group markers: normal and masked.
GROUP_MARKER_NORMAL = 0x20
GROUP_MARKER_MASK = 0x60
MAX_CGROUP_PAYLOAD_BYTES = 16 * 1024 * 1024
# Fixed shape ID flags.
SHAPE_ID_FIXED_BITS = 0x0200
SHAPE_ID_MASK_BIT = 0x00000001
TRANSFORM_MARKERS = (
    b'\x00\x01\x01\x01\x03', b'\xdf\x03\x03', b'\x00\x01\x01\x03',
    b'\x00\x01\x03', b'\x03\x03', b'\x00\x03', b'\x01\x03', b'\x03',
)

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


def node_metrics(node):
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    all_masked = True
    for shape in iter_shapes(node):
        all_masked = all_masked and shape.is_mask
        rad = math.radians(shape.rot)
        cos_r, sin_r = math.cos(rad), math.sin(rad)
        for x, y in ((-64.0, -64.0), (64.0, -64.0), (64.0, 64.0), (-64.0, 64.0)):
            xs = shape.sx * x + shape.skew * shape.sy * y
            ys = y * shape.sy
            px = shape.tx + cos_r * xs - sin_r * ys
            py = shape.ty + sin_r * xs + cos_r * ys
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


def encode_group_node(group, parent_offset=(0.0, 0.0), transform_marker=b'\x03', inherited_mask=False):
    children = group.children
    bitmap = child_bitmap(children)
    origin, all_masked = node_metrics(group)
    is_mask_group = group.is_mask_group or all_masked
    marker = GROUP_MARKER_MASK if is_mask_group else GROUP_MARKER_NORMAL
    group.tx, group.ty = origin
    out = bytearray(pack_translation_transform(origin[0] - parent_offset[0], origin[1] - parent_offset[1], transform_marker))
    out.extend(struct.pack('<BHHH', marker, len(children), len(bitmap), 0))
    out.extend(bitmap)
    child_bytes, final_mask = encode_children(children, origin, inherited_mask or is_mask_group)
    out.extend(child_bytes)
    return bytes(out), final_mask


def child_bitmap(children):
    blocks = (len(children) + 7) // 8
    bitmap = bytearray(blocks)
    for idx, child in enumerate(children):
        if isinstance(child, GroupNode):
            bitmap[idx // 8] |= (1 << (idx % 8))
    return bytes(bitmap)


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
    if not children:
        raise ValueError("SVG has no valid Forza layers")
    bitmap = child_bitmap(children)
    root_origin, _ = node_metrics(root_group)
    payload = bytearray()
    payload.extend(b'gyvl')
    payload.extend(struct.pack('<II', 1, 0))
    payload.extend(struct.pack('<Bffff', 0x03, 0.0, 0.0, 1.0, 0.0))
    payload.extend(struct.pack('<BHH2s', GROUP_MARKER_NORMAL, len(children), len(bitmap), b'\x00\x00'))
    payload.extend(bitmap)
    child_bytes, final_mask = encode_children(children, root_origin, root_group.is_mask_group)
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
    name_length = struct.unpack_from('<I', header_data, 4)[0]
    offset = 8 + name_length * 2

    require(4, offset, "description length")
    description_length = struct.unpack_from('<I', header_data, offset)[0]
    offset += 4 + description_length * 2

    offset += 4 + 16 + 8
    require(4, offset, "creator length")
    creator_length = struct.unpack_from('<I', header_data, offset)[0]
    offset += 4 + creator_length * 2

    section_marker_offset = offset + 28
    require(9 + 4, section_marker_offset, "section metadata")
    if header_data[section_marker_offset:section_marker_offset + 2] != b'\x01\x02':
        raise ValueError("C_group header section marker is invalid")

    layer_count_offset = section_marker_offset + 9
    updated = bytearray(header_data)
    struct.pack_into('<I', updated, layer_count_offset, layer_count)
    return bytes(updated)


def write_cgroup_file(target_cgroup, root_group):
    """Replace a valid C_group and its header atomically."""
    with open(target_cgroup, 'rb') as f:
        checked_data = f.read()
    validate_cgroup_data(checked_data)

    new_data = wrap_cgroup_payload(build_cgroup_payload(root_group))
    validate_cgroup_data(new_data)
    layer_count = count_shapes(root_group)
    header_path = os.path.join(os.path.dirname(target_cgroup), "header")
    with open(header_path, 'rb') as f:
        old_header_data = f.read()
    new_header_data = update_header_layer_count(old_header_data, layer_count)

    temp_cgroup = target_cgroup + ".tmp"
    temp_header = header_path + ".tmp"
    old_cgroup_data = None
    try:
        with open(temp_cgroup, 'wb') as f:
            f.write(new_data)
        with open(temp_header, 'wb') as f:
            f.write(new_header_data)

        try:
            shutil.copystat(target_cgroup, temp_cgroup)
            shutil.copystat(header_path, temp_header)
        except Exception:
            pass

        with open(target_cgroup, 'rb') as f:
            old_cgroup_data = f.read()
        validate_cgroup_data(old_cgroup_data)
        os.replace(temp_cgroup, target_cgroup)
        try:
            os.replace(temp_header, header_path)
        except Exception:
            with open(target_cgroup, 'wb') as f:
                f.write(old_cgroup_data)
            raise
    finally:
        for temp_path in (temp_cgroup, temp_header):
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass


# Decoding

def read_u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def read_utf16(data, offset, char_count):
    return data[offset:offset + char_count*2].decode("utf-16le", errors="replace").strip("\x00"), offset + char_count*2


def parse_header(header_path):
    try:
        with open(header_path, 'rb') as header_file:
            data = header_file.read()
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
    if payload[0x1d] not in (GROUP_MARKER_NORMAL, GROUP_MARKER_MASK):
        raise ValueError("Invalid C_group root marker")
    return payload


def unwrap_cgroup_file(cgroup_path):
    with open(cgroup_path, 'rb') as f:
        data = f.read()
    return validate_cgroup_data(data)


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
    for marker in TRANSFORM_MARKERS:
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
    if marker in (GROUP_MARKER_NORMAL, GROUP_MARKER_MASK):
        count = struct.unpack_from('<H', data, offset + 1)[0]
        blocks = struct.unpack_from('<H', data, offset + 3)[0]
        bitmap_start = offset + 7
    else:
        marker = GROUP_MARKER_NORMAL
        count = struct.unpack_from('<H', data, offset)[0]
        blocks = struct.unpack_from('<H', data, offset + 2)[0]
        bitmap_start = offset + 6
    bitmap = data[bitmap_start:bitmap_start + blocks]
    child_offset = bitmap_start + blocks
    group = GroupNode(is_mask_group=(marker == GROUP_MARKER_MASK) or inherited_mask)
    group.children, child_offset = decode_children(data, child_offset, count, bitmap, group.is_mask_group)
    return group, child_offset


def find_root_group_offset(payload):
    marker_start = 0x0c
    for marker in TRANSFORM_MARKERS:
        end = marker_start + len(marker)
        root_offset = end + 16
        if payload[marker_start:end] == marker and root_offset < len(payload) and payload[root_offset] in (GROUP_MARKER_NORMAL, GROUP_MARKER_MASK):
            return root_offset
    raise ValueError("Unsupported root transform marker")


def decode_cgroup_payload(payload):
    if payload[:4] != b'gyvl':
        raise ValueError("Invalid C_group payload")
    root_offset = find_root_group_offset(payload)
    root_marker = payload[root_offset]
    if root_marker not in (GROUP_MARKER_NORMAL, GROUP_MARKER_MASK):
        raise ValueError("Unsupported root group marker")
    count = struct.unpack_from('<H', payload, root_offset + 1)[0]
    blocks = struct.unpack_from('<H', payload, root_offset + 3)[0]
    bitmap_start = root_offset + 7
    bitmap = payload[bitmap_start:bitmap_start + blocks]
    children, _ = decode_children(payload, bitmap_start + blocks, count, bitmap, root_marker == GROUP_MARKER_MASK)
    return GroupNode(children=children, is_mask_group=(root_marker == GROUP_MARKER_MASK), name="root")

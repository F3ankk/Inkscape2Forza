import xml.etree.ElementTree as ET
import math
import re
import struct
import zlib
import os
import shutil

# config
SVG_FILE = "test.svg"
TARGET_CGROUP = "C_group"

ANCHOR_BYTES = b"\x00\x02\x66\x00"

def quantize_alpha(a):
    """
    Alpha in forza is quantized to multiples of 3, with a minimum of 2, and a maximum of 255.
    """
    if a >= 255:
        return 255
        
    quantized = int(round(a / 3.0) * 3)
    
    if quantized < 2:
        return 2
        
    return quantized

def parse_color(elem):
    """R, G, B, A (0-255)"""
    r, g, b, a = 0, 0, 0, 255 
    
    style_str = elem.get('style', '')
    
    # Match regular solid color fills
    fill_match = re.search(r'fill:\s*#([0-9a-fA-F]{6})', style_str)
    if not fill_match:
        fill_attr = elem.get('fill', '')
        # Avoid matching patterns like url(#pattern123456) by ensuring the hex color is a standalone word
        fill_match = re.search(r'#([0-9a-fA-F]{6})\b', fill_attr)
        
    if fill_match:
        hex_color = fill_match.group(1)
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
    # Transparency
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
    """
    SVG transform parser (affine)
    """
    # Initialize as the standard identity matrix
    current_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    
    if not transform_str:
        return current_matrix
        
    def mult_matrix(M1, M2):
        """Matrix multiplication: M1 * M2"""
        a1, b1, c1, d1, e1, f1 = M1
        a2, b2, c2, d2, e2, f2 = M2
        return (
            a1*a2 + c1*b2,
            b1*a2 + d1*b2,
            a1*c2 + c1*d2,
            b1*c2 + d1*d2,
            a1*e2 + c1*f2 + e1,
            b1*e2 + d1*f2 + f1
        )
        
    # Extract all transform commands
    for cmd, args in re.findall(r'([a-zA-Z]+)\s*\(([^)]+)\)', transform_str):
        vals = [float(x) for x in args.replace(',', ' ').split()]
        if not vals:
            continue
            
        if cmd == 'matrix' and len(vals) == 6:
            m = tuple(vals)
        elif cmd == 'translate':
            x = vals[0]
            y = vals[1] if len(vals) > 1 else 0.0
            m = (1.0, 0.0, 0.0, 1.0, x, y)
        elif cmd == 'scale':
            x = vals[0]
            y = vals[1] if len(vals) > 1 else vals[0]
            m = (x, 0.0, 0.0, y, 0.0, 0.0)
        elif cmd == 'rotate':
            a = math.radians(vals[0])
            ca, sa = math.cos(a), math.sin(a)
            if len(vals) >= 3:
                cx, cy = vals[1], vals[2]
                m = (ca, sa, -sa, ca, cx - cx*ca + cy*sa, cy - cx*sa - cy*ca)
            else:
                m = (ca, sa, -sa, ca, 0.0, 0.0)
        elif cmd == 'skewX':
            a = math.radians(vals[0])
            m = (1.0, 0.0, math.tan(a), 1.0, 0.0, 0.0)
        elif cmd == 'skewY':
            a = math.radians(vals[0])
            m = (1.0, math.tan(a), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
            
        current_matrix = mult_matrix(current_matrix, m)
        
    return current_matrix

def decompose_matrix(a, b, c, d, e, f, min_x, min_y, canvas_w, canvas_h):
    """
    SVG matrix -> ForzaTech vinyl layers
    """
    real_svg_cx = a * (-min_x) + c * (-min_y) + e
    real_svg_cy = b * (-min_x) + d * (-min_y) + f
    
    tx = real_svg_cx - (canvas_w / 2.0)
    ty = (canvas_h / 2.0) - real_svg_cy
    
    A = a
    B = -b
    C = -c
    D = d
    
    sx = math.sqrt(A*A + B*B)
    if sx < 1e-6:
        return tx, ty, 0, 0, 0, 0
        
    rot_rad = math.atan2(B, A)
    rot_deg = math.degrees(rot_rad) % 360.0
    
    sy = -C * math.sin(rot_rad) + D * math.cos(rot_rad)
    
    if abs(sy) > 1e-6:
        k_sy = C * math.cos(rot_rad) + D * math.sin(rot_rad)
        skew = k_sy / sy
    else:
        skew = 0.0

    return tx, ty, sx, sy, rot_deg, skew

def build_layer_bytes(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a, is_masked_by_prev=False):
    """
    Pack layer data into a 32byte little-endian binary format.
    """
    shape_id = (shape_word << 16) | 0x0200
    
    # mask_flag
    if is_masked_by_prev:
        shape_id |= 0x00000001
        
    layer_bin = struct.pack('<IffffffBBBB', 
                            shape_id, rot, tx, ty, sx, sy, skew, 
                            b, g, r, a)
    return layer_bin

def process_svg():
    """SVG Parser"""
    tree = ET.parse(SVG_FILE)
    root = tree.getroot()
    
    width_str = root.get('width', '2048').replace('px', '').strip()
    height_str = root.get('height', '2048').replace('px', '').strip()
    canvas_w = float(width_str)
    canvas_h = float(height_str)
    
    print(f"Inkscape SVG canvas size: {canvas_w}*{canvas_h}\nRecommended: 1920*1080")
    
    symbol_dict = {}
    pattern_dict = {} 
    
    for elem in root.iter():
        if elem.tag.endswith('symbol'):
            symbol_id = elem.get('id')
            viewbox_str = elem.get('viewBox')
            if symbol_id and viewbox_str:
                vb_parts = viewbox_str.split()
                if len(vb_parts) == 4:
                    symbol_dict[f"#{symbol_id}"] = (float(vb_parts[0]), float(vb_parts[1]))
                    
        if elem.tag.endswith('pattern'):
            pattern_id = elem.get('id')
            href = elem.get('{http://www.w3.org/1999/xlink}href') or elem.get('href', '')
            if pattern_id and href:
                pattern_dict[f"#{pattern_id}"] = href

    layers_bin_list = []
    prev_was_mask = False  
    total_fh6_nodes = 0
    
    for elem in root.iter():
        if not elem.tag.endswith('use'):
            continue
            
        href = elem.get('{http://www.w3.org/1999/xlink}href') or elem.get('href', '')
        match = re.search(r'fh6_t(\d+)_i(\d+)_w(\d+)', href)
        if not match:
            continue
            
        total_fh6_nodes += 1
        shape_word = int(match.group(3))
        
        elem_id = elem.get('id', '').lower()
        style_str = elem.get('style', '').lower()
        fill_attr = elem.get('fill', '').lower()
        
        url_match = re.search(r'url\((\#[^)]+)\)', style_str)
        if not url_match:
            url_match = re.search(r'url\((\#[^)]+)\)', fill_attr)
            
        resolved_href = ""
        if url_match:
            pattern_ref = url_match.group(1) 
            resolved_href = pattern_dict.get(pattern_ref, '').lower()
        
        is_current_mask = (
            elem_id.startswith('mask') or 
            'destination-out' in style_str or 
            'mask_indicator' in resolved_href
        )
        
        # ignore invisible layers, except for those explicitly marked as masks (either by id or by pattern reference)
        has_fill_none = ('fill:none' in style_str.replace(' ', '')) or (fill_attr == 'none')
        is_hidden = ('display:none' in style_str.replace(' ', '')) or (elem.get('display', '').lower() == 'none')
        
        if (has_fill_none or is_hidden) and not is_current_mask:
            continue
        
        r, g, b, a_val = parse_color(elem)
        if is_current_mask:
            r, g, b = 255, 255, 255
            
        transform_str = elem.get('transform', '')
        use_x = float(elem.get('x', '0'))
        use_y = float(elem.get('y', '0'))
        
        ma, mb, mc, md, me, mf = parse_transform(transform_str)
        min_x, min_y = symbol_dict.get(href, (0.0, 0.0))
        
        me = me + ma * use_x + mc * use_y
        mf = mf + mb * use_x + md * use_y
        
        tx, ty, sx, sy, rot, skew = decompose_matrix(
            ma, mb, mc, md, me, mf, 
            min_x, min_y, 
            canvas_w, canvas_h
        )
        
        layer_bin = build_layer_bytes(shape_word, rot, tx, ty, sx, sy, skew, r, g, b, a_val, prev_was_mask)
        layers_bin_list.append(layer_bin)
        
        prev_was_mask = is_current_mask
        
    return layers_bin_list, prev_was_mask, total_fh6_nodes

def main():
    if not os.path.exists(SVG_FILE) or not os.path.exists(TARGET_CGROUP):
        print("Can't find source files! Please ensure test.svg and target C_group file exist.")
        return

    layers_bin_list, last_was_mask, total_fh6_nodes = process_svg()
    print(f"{total_fh6_nodes} possible layers detected, after filtering {len(layers_bin_list)} valid layers remain.")

    with open(TARGET_CGROUP, 'rb') as f:
        cgroup_data = f.read()
        
    # comp_size, decomp_size = struct.unpack('<II', cgroup_data[:8])
    zstream = cgroup_data[8:]
    
    try:
        decomp_data = zlib.decompress(zstream)
    except Exception as e:
        print(f"Read gamesave failed: {e}")
        return
        
    idx = decomp_data.find(ANCHOR_BYTES)
    if idx == -1:
        print("Cannot find the initial anchor point for first layer! Please confirm that you are using a valid vinyl group!")
        return
        
    print(f"Located first layer, offset: {idx}")
    
    original_layer_data_len = len(decomp_data) - idx - 2
    original_layer_count = original_layer_data_len // 32
    
    print(f"SVG valid layer count [{len(layers_bin_list)}] - vinyl group layer count [{original_layer_count}]。")
    
    if len(layers_bin_list) != original_layer_count:
        print("Valid layer count mismatch, injection terminated for safety!")
        return
    
    header_data = decomp_data[:idx]
    
    # EOF
    footer_data = bytearray(decomp_data[idx + original_layer_count * 32:])
    if len(footer_data) > 0:
        if last_was_mask:
            footer_data[0] |= 0x01  # EOF=0x0101 if the last layer is a mask
        else:
            footer_data[0] &= ~0x01 # EOF=0x0001 if the last layer is not a mask
    
    new_layers_data = b"".join(layers_bin_list)
    new_decomp_data = header_data + new_layers_data + bytes(footer_data)
    new_decomp_size = len(new_decomp_data)
    
    compressor = zlib.compressobj(
        level=6,
        method=zlib.DEFLATED,
        wbits=zlib.MAX_WBITS,
        memLevel=8,
        strategy=zlib.Z_DEFAULT_STRATEGY
    )
    new_zstream = compressor.compress(new_decomp_data) + compressor.flush()
    new_comp_size = len(new_zstream)
    
    new_header_8bytes = struct.pack('<II', new_comp_size, new_decomp_size)
    
    temp_cgroup = TARGET_CGROUP + ".tmp"
    with open(temp_cgroup, 'wb') as f:
        f.write(new_header_8bytes + new_zstream)

    # Make sure the injected file has the same permissions and metadata as the original 
    try:
        shutil.copystat(TARGET_CGROUP, temp_cgroup)
    except Exception as e:
        print(f"Warning: Failed to copy file metadata, but temporary file was created: {e}")
        
    try:
        os.replace(temp_cgroup, TARGET_CGROUP)
    except Exception as e:
        print(f"Failed to overwrite original file, please check if the file is accessible: {e}")
        return

    print(f"Successfully overwritten file: {TARGET_CGROUP}")

if __name__ == "__main__":
    main()
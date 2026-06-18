import os
import zlib
import struct

# config
TARGET_CGROUP = "C_group"

LAYER_SIZE = 32
ANCHOR_BYTES = b"\x00\x02\x66\x00"

def find_layer_start(data):
    pos = data.find(ANCHOR_BYTES)
    return pos if pos >= 0 else None

def is_eof(data, pos):
    remain = len(data) - pos

    if remain == 2:
        return True

    if remain < LAYER_SIZE:
        return True

    return False

def dump_cgroup(path):
    with open(path, "rb") as f:
        raw = f.read()

    compressed_size = struct.unpack_from("<I", raw, 0)[0]
    decompressed_size = struct.unpack_from("<I", raw, 4)[0]

    print(f"Compressed: {compressed_size}")
    print(f"Decompressed: {decompressed_size}")

    payload = raw[8:]
    decompressed = zlib.decompress(payload)
    start = find_layer_start(decompressed)

    if start is None:
        print("Could not find first layer")
        return

    print(f"Layer block starts at 0x{start:X}\n")

    print("      00 01 02 03")
    print("     +-----------")

    layer_index = 1
    pos = start

    while pos < len(decompressed):

        if is_eof(decompressed, pos):
            eof_bytes = decompressed[pos:]

            hexstr = " ".join(f"{b:02X}" for b in eof_bytes)

            print(f"{pos:04X} |{hexstr:<11} - EOF")
            break

        for row in range(8):
            off = pos + row * 4
            chunk = decompressed[off:off + 4]

            hexstr = " ".join(f"{b:02X}" for b in chunk)

            print(
                f"{off:04X} |{hexstr}",
                end=""
            )

            if row == 0:
                print(f"  - layer{layer_index}")
            else:
                print()

        pos += LAYER_SIZE
        layer_index += 1

def main():

    if not os.path.isfile(TARGET_CGROUP):
        print(f"File not found: {TARGET_CGROUP}")
        return

    dump_cgroup(TARGET_CGROUP)

if __name__ == "__main__":
    main()
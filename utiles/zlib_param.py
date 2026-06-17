import os
import zlib
import hashlib
from pathlib import Path

SAMPLES = [
    "C_group_1",
    "C_group_2",
    "C_group_3",
    "C_group_4",
    "C_group_5",
]

STRATEGIES = {
    "DEFAULT": zlib.Z_DEFAULT_STRATEGY,
    "FILTERED": zlib.Z_FILTERED,
    "HUFFMAN": zlib.Z_HUFFMAN_ONLY,
    "RLE": zlib.Z_RLE,
    "FIXED": zlib.Z_FIXED,
}

def md5(data):
    return hashlib.md5(data).hexdigest()

def load_cgroup(path):

    blob = Path(path).read_bytes()
    compressed_size = int.from_bytes(blob[0:4], "little")
    raw_size = int.from_bytes(blob[4:8], "little")
    official = blob[8:]

    return compressed_size, raw_size, official

def recompress(raw, level, memlevel, strategy):

    obj = zlib.compressobj(
        level=level,
        method=zlib.DEFLATED,
        wbits=zlib.MAX_WBITS,
        memLevel=memlevel,
        strategy=strategy
    )

    comp = obj.compress(raw)
    comp += obj.flush()

    return comp

def test_file(path):

    print("=" * 10)
    print(path)

    compressed_size, raw_size, official = load_cgroup(path)

    raw = zlib.decompress(official)

    print("Official compressed:", len(official))
    print("Official raw:", len(raw))
    print("Header compressed:", compressed_size)
    print("Header raw:", raw_size)

    if len(raw) != raw_size:
        print("Raw size mismatch")

    found = []

    for level in range(10):
        for memlevel in range(1, 10):
            for name, strategy in STRATEGIES.items():
                comp = recompress(raw,level,memlevel,strategy)

                if comp == official:
                    found.append({
                        "level": level,
                        "memlevel": memlevel,
                        "strategy": name
                    })

                    print(
                        f"MATCH"
                        f"level={level} "
                        f"mem={memlevel} "
                        f"strategy={name}"
                    )

    if not found:

        print("No exact match found")

        best = None

        for level in range(10):
            comp = zlib.compress(raw, level)
            diff = abs(len(comp) - len(official))
            if best is None or diff < best[0]:
                best = (
                    diff,
                    level,
                    len(comp)
                )

        print(
            f"Closest size:"
            f" level={best[1]}"
            f" size={best[2]}"
            f" official={len(official)}"
        )

    return found


def main():
    all_matches = {}
    for file in SAMPLES:
        matches = test_file(file)
        all_matches[file] = matches

    print("\n")
    print("=" * 10)

    for k, v in all_matches.items():
        print(k)
        if not v:
            print("  no exact match")
            continue

        for item in v:
            print(
                f"  level={item['level']} "
                f"mem={item['memlevel']} "
                f"strategy={item['strategy']}"
            )

if __name__ == "__main__":
    main()
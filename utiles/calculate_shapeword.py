import json
import shutil
from pathlib import Path
from tkinter import Tk, filedialog


# Type -> ShapeWord(id=1)
TYPE_BASES = {
    1048677: 101,   # Primitives
    1050677: 2101,  # Community_Vinyls_1
    1050777: 2201,  # Community_Vinyls_2
    1050877: 2301,  # Community_Vinyls_3
    1050977: 2401,  # Community_Vinyls_4
    1048777: 201,   # Gradient_Shapes
    1048877: 301,   # Stripes
    1048977: 401,   # Tears
    1049077: 501,   # Racing_Icons
    1049177: 601,   # Flames
    1049277: 701,   # Paint_Splats
    1049377: 801,   # Tribal
    1049477: 901,   # Nature
    1050477: 1901,  # Upper_Letters_1
    1050577: 2001,  # Lower_Letters_1
    1049877: 1301,  # Upper_Letters_2
    1049977: 1401,  # Lower_Letters_2
    1050077: 1501,  # Upper_Letters_3
    1050177: 1601,  # Lower_Letters_3
    1050277: 1701,  # Upper_Letters_4
    1050377: 1801,  # Lower_Letters_4
    1051077: 2501,  # Upper_Letters_5
    1051177: 2601,  # Lower_Letters_5
    1051277: 2701,  # Upper_Letters_6
    1051377: 2801,  # Lower_Letters_6
    1051477: 2901,  # Upper_Letters_7
    1051577: 3001,  # Lower_Letters_7
    1051677: 3101,  # Upper_Letters_8
    1051777: 3201,  # Lower_Letters_8
    1051877: 3301,  # Upper_Letters_9
    1051977: 3401,  # Lower_Letters_9
    1052077: 3501,  # Upper_Letters_10
    1052177: 3601,  # Lower_Letters_10
    1052277: 3701,  # Upper_Letters_11
    1052377: 3801,  # Lower_Letters_11
}

def calc_shape_word(type_code, type_index):
    return TYPE_BASES[type_code] + type_index - 1

def process_file(path: Path):
    print(f"\nProcessing {path.name}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    count = 0
    for item in data:
        info = item.get("Info")
        if not info:
            continue

        type_code = info.get("Type")
        type_index = info.get("TypeIndex")

        if type_code not in TYPE_BASES:
            print(f"  Skip id={item.get('id')} (unknown type {type_code})")
            continue

        info["ShapeWord"] = calc_shape_word(type_code, type_index)
        count += 1

    #  UTF-8 withot BOM
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"Updated {count} entries")

def main():
    folder = Path(".")
    files = sorted(folder.glob("*.json"))

    print(f"\nFound {len(files)} json files")

    for file in files:
        process_file(file)

    print("\nDone.")

if __name__ == "__main__":
    main()
import json
from pathlib import Path

def read_and_flatten_json(file_path: Path, id_value: int):
    with open(file_path, "r", encoding="utf-8") as f:
        obj = json.load(f)

    flat = {"id": id_value}
    flat.update(obj)
    return flat


def process_folder(folder: Path, out_dir: Path):
    items = []

    for file in folder.iterdir():
        if file.is_file() and file.name.isdigit():
            id_value = int(file.name)
            flat = read_and_flatten_json(file, id_value)
            items.append(flat)

    items.sort(key=lambda x: x["id"])

    out_path = out_dir / f"{folder.name}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=4)

    print(f"Generated {out_path}")


def main():
    root = Path(".")
    out_dir = root / "json" / "full"
    out_dir.mkdir(exist_ok=True)

    for folder in root.iterdir():
        if folder.is_dir():
            process_folder(folder, out_dir)

    print("Done.")

if __name__ == "__main__":
    main()
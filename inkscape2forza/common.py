"""Shared constants and helpers."""
import sys
from pathlib import Path

SVG_NS = 'http://www.w3.org/2000/svg'
XLINK_NS = 'http://www.w3.org/1999/xlink'

DEFAULT_GAMESAVE_DIR = r"C:\XboxGames\GameSave"
MAX_VINYL_GROUP_LAYERS = 3000


def get_resource_path(relative_path):
    """Resolve a source or bundled resource."""
    if hasattr(sys, '_MEIPASS'):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    return str(base / relative_path)

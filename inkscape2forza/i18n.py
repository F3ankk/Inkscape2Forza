"""Language helpers."""
import locale
import re
import sys


def _system_locale_name():
    if sys.platform == "win32":
        try:
            import ctypes

            language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            language = locale.windows_locale.get(language_id)
            if language:
                return language
            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                return buffer.value
        except (AttributeError, OSError):
            pass
    language, _ = locale.getlocale()
    return language or ""


IS_SIMPLIFIED_CHINESE = _system_locale_name().replace("_", "-").lower() == "zh-cn"
_CJK = re.compile(r"[\u3400-\u9fff]")


def tr(chinese, english):
    return chinese if IS_SIMPLIFIED_CHINESE else english


def localize(message):
    """Localize legacy bilingual text."""
    message = str(message)
    if " / " in message:
        chinese, english = message.split(" / ", 1)
        if IS_SIMPLIFIED_CHINESE:
            shared_suffix = english[english.find("\n"):] if "\n" in english else ""
            return chinese + shared_suffix
        return english

    lines = message.splitlines(keepends=True)
    has_chinese = any(_CJK.search(line) for line in lines)
    has_english = any(line.strip() and not _CJK.search(line) for line in lines)
    if len(lines) > 1 and has_chinese and has_english:
        selected = []
        for line in lines:
            stripped = line.strip()
            is_shared = not stripped or line[:1].isspace()
            if is_shared or bool(_CJK.search(line)) == IS_SIMPLIFIED_CHINESE:
                selected.append(line)
        return "".join(selected).rstrip("\r\n")
    return message

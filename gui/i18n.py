"""Presentation-only localization; file names and persisted model values stay intact."""
from __future__ import annotations

from functools import lru_cache
import re
from string import Formatter
from weakref import ref

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QComboBox

from gui.translations import ENGLISH

_language: str | None = None
# Qt table items are unhashable, so use identity keys with weak references.
_bindings: dict[int, tuple[ref, dict]] = {}


def _properties(target) -> dict:
    key = id(target)
    existing = _bindings.get(key)
    if existing is None or existing[0]() is not target:
        _bindings[key] = (ref(target, lambda _ref, identity=key: _bindings.pop(identity, None)), {})
    return _bindings[key][1]


class _LanguageEvents(QObject):
    changed = Signal(str)


language_events = _LanguageEvents()


def get_language() -> str:
    global _language
    if _language is None:
        saved = QSettings("PicMedic", "PicMedic").value("language", "ko")
        _language = saved if saved in ("ko", "en") else "ko"
    return _language


class Message(str):
    """Keep the Korean value for logic; render translated text only at the UI boundary."""

    def __new__(cls, template: str, *args):
        source = template.format(*args) if args else template
        obj = super().__new__(cls, source)
        obj.template = template
        obj.args = args
        return obj

    def render(self) -> str:
        template = ENGLISH.get(self.template, self.template) if get_language() == "en" else self.template
        args = [value.render() if isinstance(value, Message) else value for value in self.args]
        return template.format(*args) if args else template

    def __add__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return message("{0}{1}", self, other)

    def __radd__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return message("{0}{1}", other, self)


def message(template: str, *args) -> Message:
    if isinstance(template, Message) and not args:
        return template
    return Message(template, *args)


def render(value) -> str:
    return value.render() if isinstance(value, Message) else value


def _apply(target, prop: str, source) -> None:
    if prop == "horizontalHeaderLabels":
        target.setHorizontalHeaderLabels([render(value) for value in source])
    elif prop == "items":
        # Display text is translated; userData remains the stable application value.
        blocked = target.blockSignals(True)
        try:
            for index, value in enumerate(source):
                target.setItemText(index, render(value))
        finally:
            target.blockSignals(blocked)
    elif isinstance(target, QObject):
        target.setProperty(prop, render(source))
    else:  # QTableWidgetItem is not a QObject.
        getattr(target, "set" + prop[0].upper() + prop[1:])(render(source))


def set_ui(target, prop: str, source) -> None:
    """Bind only explicit messages. Plain user data is never translated."""
    localized = isinstance(source, Message) or (
        isinstance(source, (list, tuple)) and any(isinstance(value, Message) for value in source)
    )
    if localized:
        _properties(target)[prop] = source
    elif id(target) in _bindings:
        _properties(target).pop(prop, None)
    _apply(target, prop, source)


def localized_widget(cls, *args, **kwargs):
    result = cls(*args, **kwargs)
    if args and isinstance(args[0], Message):
        set_ui(result, "text", args[0])
    return result


def add_action(menu, text, *args):
    result = menu.addAction(render(text), *args)
    if isinstance(text, Message):
        set_ui(result, "text", text)
    return result


def add_items(combo: QComboBox, values) -> None:
    old = _properties(combo).get("items", [])
    # Store canonical text as item data when no explicit userData is provided.
    for value in values:
        combo.addItem(render(value), str(value))
    sources = list(old) + list(values)
    if any(isinstance(value, Message) for value in sources):
        _properties(combo)["items"] = sources


def add_item(combo: QComboBox, text, user_data=None) -> None:
    old = _properties(combo).get("items", [])
    combo.addItem(render(text), str(text) if user_data is None else user_data)
    sources = list(old) + [text]
    if any(isinstance(value, Message) for value in sources):
        _properties(combo)["items"] = sources


def set_language(language: str) -> None:
    global _language
    if language not in ("ko", "en"):
        raise ValueError(f"Unsupported UI language: {language}")
    if get_language() == language:
        return
    _language = language
    QSettings("PicMedic", "PicMedic").setValue("language", language)
    for identity, (reference, properties) in list(_bindings.items()):
        target = reference()
        if target is None:
            continue
        try:
            for prop, source in list(properties.items()):
                _apply(target, prop, source)
        except RuntimeError:
            # Qt may have destroyed a C++ object while its Python wrapper survives.
            _bindings.pop(identity, None)
    language_events.changed.emit(language)


def file_dialog(method, *args, **kwargs):
    """Render captions and filters; leave returned file-system paths untouched."""
    return method(*(render(value) for value in args), **kwargs)


def join_messages(separator: str, values) -> Message:
    values = tuple(values)
    return message(separator.join("{" + str(index) + "}" for index in range(len(values))), *values)


class _MappedMessage(Message):
    def __new__(cls, source: Message, transform):
        obj = super().__new__(cls, "{0}", source)
        obj.transform = transform
        return obj

    def render(self) -> str:
        return self.transform(super().render())


def map_message(source, transform):
    return _MappedMessage(source, transform) if isinstance(source, Message) else transform(source)


@lru_cache(maxsize=1)
def _system_patterns():
    patterns = []
    for template in ENGLISH:
        parts = list(Formatter().parse(template))
        literals = sum(len(literal) for literal, *_ in parts)
        fields = [field for _, field, _, _ in parts if field is not None]
        if not fields or literals < 4 or any(not field.isdigit() for field in fields):
            continue
        pattern = "".join(re.escape(literal) + ("(.*?)" if field is not None else "") for literal, field, _, _ in parts)
        patterns.append((template, fields, re.compile(pattern, flags=re.DOTALL)))
    return patterns


def system_message(source: str) -> Message:
    """Localize known system explanations, including ones reloaded from session JSON.

    Use only for application messages, never file names or user-entered text.
    """
    if isinstance(source, Message) or source in ENGLISH:
        return message(source)
    for template, fields, pattern in _system_patterns():
        match = pattern.fullmatch(source)
        if match:
            args = [""] * (max(map(int, fields)) + 1)
            for field, value in zip(fields, match.groups()):
                args[int(field)] = value
            return message(template, *args)
    return message(source)


def place_message(label: str) -> Message:
    """Translate geographic display labels without changing grouping keys or folders."""
    match = re.fullmatch(r"(.*)( \([\d,]+\))", label)
    if match:
        return message("{0}{1}", place_message(match[1]), match[2])
    return join_messages(", ", [message(part) for part in label.split(", ")])

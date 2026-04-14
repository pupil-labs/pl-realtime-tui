import re
from collections.abc import Iterable
from typing import Any

from textual import events


class KeyUp(events.Event):
    def __init__(self, key: str, character: str | None = None) -> None:
        super().__init__()
        self.key = key
        self.character = character


def apply_keyboard_patch() -> None:  # noqa: C901
    try:
        import textual._xterm_parser
        from textual._keyboard_protocol import FUNCTIONAL_KEYS
        from textual.keys import _character_to_key

        _orig_re_extended_key = textual._xterm_parser._re_extended_key
        _kitty_re_extended_key = re.compile(
            r"\x1b\[(?:(\d+)(?:(?:;(\d+))?(?::(\d+))?)?)?([u~ABCDEFHPQRS])"
        )
        _orig_seq_to_key = textual._xterm_parser.XTermParser._sequence_to_key_events

        def _patched_seq_to_key(  # noqa: C901
            self: Any, sequence: str, alt: bool = False
        ) -> Iterable[events.Event]:
            if (match := _kitty_re_extended_key.fullmatch(sequence)) is not None:
                number, modifiers, event_type, end = match.groups()
                if event_type == "2":
                    return
                elif event_type == "3":
                    number = number or 1
                    if not (key := FUNCTIONAL_KEYS.get(f"{number}{end}", "")):
                        try:
                            key = _character_to_key(chr(int(number)))
                        except Exception:
                            key = chr(int(number))
                    key_tokens = []
                    if modifiers:
                        modifier_bits = int(modifiers) - 1
                        MODIFIERS = ("shift", "alt", "ctrl", "super", "hyper", "meta")
                        for bit, modifier in enumerate(MODIFIERS):
                            if modifier_bits & (1 << bit):
                                key_tokens.append(modifier)
                    key_tokens.sort()
                    key_tokens.append(key.lower())

                    try:
                        character = (
                            chr(int(number))
                            if number and int(number) < 1114112
                            else None
                        )
                    except ValueError:
                        character = None

                    yield KeyUp(key="-".join(key_tokens), character=character)
                    return
                elif event_type == "1":
                    modifiers = modifiers or "1"
                    sequence = f"\x1b[{number or ''};{modifiers}{end}"

            yield from _orig_seq_to_key(self, sequence, alt)

        textual._xterm_parser.XTermParser._sequence_to_key_events = _patched_seq_to_key  # type: ignore

    except Exception:  # noqa: S110
        pass

import textual._xterm_parser
from textual import events

from pupil_labs.realtime_tui.terminal_patch import KeyUp, apply_keyboard_patch


def test_kitty_keyboard_protocol_patch():
    # Apply the patch
    apply_keyboard_patch()

    # Initialize the parser
    parser = textual._xterm_parser.XTermParser()

    # Simulate a Key Press (event type 1) for the 'a' key (unicode 97)
    press_events = list(parser._sequence_to_key_events("\x1b[97;1:1u"))
    assert len(press_events) == 1
    assert isinstance(press_events[0], events.Key)
    assert not isinstance(press_events[0], KeyUp)
    assert press_events[0].key == "a"
    assert press_events[0].character == "a"

    # Simulate a Key Repeat (event type 2) for the 'a' key
    # The patch should ignore repeat events, so it should yield nothing
    repeat_events = list(parser._sequence_to_key_events("\x1b[97;1:2u"))
    assert len(repeat_events) == 0

    # Simulate a Key Release (event type 3) for the 'a' key
    release_events = list(parser._sequence_to_key_events("\x1b[97;1:3u"))
    assert len(release_events) == 1
    assert isinstance(release_events[0], KeyUp)
    assert release_events[0].key == "a"
    assert release_events[0].character == "a"

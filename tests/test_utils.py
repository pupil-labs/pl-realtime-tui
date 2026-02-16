import math

from pupil_labs.pl_deck.utils import byte_size_to_gb, get_offset_age_color


def test_byte_size_to_gb():
    assert math.isclose(byte_size_to_gb(1024**3), 1.0)
    assert math.isclose(byte_size_to_gb(0), 0.0)
    assert math.isclose(byte_size_to_gb(512 * 1024**2), 0.5)


def test_get_offset_age_color():
    assert get_offset_age_color(10) == "green"
    assert get_offset_age_color(275) == "yellow"
    assert get_offset_age_color(300) == "bold red"

from pupil_labs.pl_deck.settings import load_settings

DEFAULT_EVENT_MAP = {
    "1": "custom_event_1",
    "2": "custom_event_2",
    "3": "custom_event_3",
    "4": "custom_event_4",
    "5": "custom_event_5",
    "6": "custom_event_6",
    "7": "custom_event_7",
    "8": "custom_event_8",
    "9": "custom_event_9",
    "0": "custom_event_0",
}

settings = load_settings()
EVENT_MAP = (
    settings.get("event_map", DEFAULT_EVENT_MAP) if settings else DEFAULT_EVENT_MAP
)

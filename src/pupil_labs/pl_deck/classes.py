from collections import deque
from dataclasses import dataclass, field

from pupil_labs.realtime_api.device import Device
from pupil_labs.realtime_api.time_echo import TimeEchoEstimates, TimeOffsetEstimator


@dataclass
class DeviceClass:
    """Holds all state for a single connected device."""

    device: Device
    address: str
    phone_name: str
    sn: str
    estimate: TimeEchoEstimates
    estimator: TimeOffsetEstimator
    clock_offset_ns: int
    is_recording: bool
    is_online: bool
    last_status_update_time: float
    last_offset_update_time: float
    battery_level: float
    storage: float
    last_event_name: str
    last_event_time: float
    last_event_pupil_ts: float
    rec_duration_ns: int = 0
    rtt_history: deque = field(default_factory=lambda: deque(maxlen=15))

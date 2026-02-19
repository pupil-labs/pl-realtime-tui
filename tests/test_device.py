from unittest.mock import MagicMock

from pupil_labs.realtime_tui.classes import DeviceClass


def test_device_class_init():
    mock_device = MagicMock()
    mock_estimate = MagicMock()
    mock_estimator = MagicMock()

    device_info = DeviceClass(
        device=mock_device,
        address="192.168.1.42:8080",
        phone_name="Test Phone",
        sn="SN123",
        estimate=mock_estimate,
        estimator=mock_estimator,
        clock_offset_ns=1000,
        is_recording=False,
        is_online=True,
        last_status_update_time=123456789,
        last_offset_update_time=123456789,
        battery_level=80,
        storage=10.5,
        last_event_name="test_event",
        last_event_time=123456789,
        last_event_pupil_ts=123456789,
    )

    assert device_info.phone_name == "Test Phone"
    assert device_info.is_online is True
    assert len(device_info.rtt_history) == 0

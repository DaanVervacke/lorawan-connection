"""Exercise device codec fixtures and invalid event handling."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from dragino_lorawan import LHT65
from lorawan_connection import Device, DeviceDescriptor, UplinkEvent
from milesight_lorawan import TS201, UC51x
from sensecap_lorawan import S2102


def descriptor(model: type[Device]) -> DeviceDescriptor:
    brand_id, model_id = model.identifiers["tts"]
    return DeviceDescriptor(
        network_id="network",
        dev_eui="0201010101010101",
        name="Codec fixture",
        application_id="application",
        profile_id="profile",
        stack="tts",
        brand_id=brand_id,
        model_id=model_id,
    )


@pytest.mark.parametrize(
    ("model", "port", "payload", "attribute", "expected"),
    [
        (S2102, 2, "010310000000000000", "illuminance", 0),
        (TS201, 85, "93673401640002", "temperature", 30.8),
        (TS201, 85, "0367baff", "temperature", -7),
        (UC51x, 85, "030100", "valve_1_open", False),
        (LHT65, 2, "cbeaff9c026d01ff387fff", "external_temperature", -2),
    ],
)
def test_partial_invalid_and_old_uplinks(
    model: type[Device], port: int, payload: str, attribute: str, expected: float | bool
) -> None:
    """Decode source fixtures without losing readings to bad or unrelated data."""
    device = model(descriptor(model))
    event = UplinkEvent(
        descriptor=device.descriptor,
        received_at=datetime.now(UTC),
        f_port=port,
        data=bytes.fromhex(payload),
    )
    device._receive_event(event)
    assert getattr(device, attribute) == expected
    device._receive_event(replace(event, data=b"\x01"))
    device._receive_event(replace(event, f_port=99, data=b"\x00" * 11))
    device._receive_event(
        replace(
            event,
            received_at=event.received_at - timedelta(seconds=1),
            data=b"\x00" * len(event.data),
        )
    )
    assert getattr(device, attribute) == expected


def test_sensor_fault_clears_temperature() -> None:
    """A TS201 fault makes the old measurement unknown."""
    device = TS201(descriptor(TS201))
    event = UplinkEvent(
        descriptor=device.descriptor,
        received_at=datetime.now(UTC),
        f_port=85,
        data=bytes.fromhex("03673401"),
    )
    device._receive_event(event)
    device._receive_event(replace(event, data=bytes.fromhex("b36700")))
    assert device.temperature is None


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (TS201, "20cec79afa6402bdff"),
        (UC51x, "20ce3fa109641700000000"),
        (LHT65, "cbea0105026d4101aa7fff"),
    ],
)
def test_history_does_not_become_current_state(
    model: type[TS201 | UC51x | LHT65], payload: str
) -> None:
    """Device history replies do not report current telemetry."""
    assert model.decode(bytes.fromhex(payload)) == {}


@pytest.mark.parametrize(
    ("model", "payload", "expected"),
    [
        (UC51x, "030101", {"valve_1_open": True}),
        (
            LHT65,
            "cbf60b0d0376010add7fff",
            {
                "temperature": 28.29,
                "humidity": 88.6,
                "external_temperature": 27.81,
                "battery_voltage": 3.062,
                "external_sensor_disconnected": False,
                "reported_battery_status": 3,
            },
        ),
    ],
)
def test_ttn_codec_example(
    model: type[UC51x | LHT65], payload: str, expected: dict[str, float | int | bool]
) -> None:
    """Published TTN examples cover models without physical-device captures."""
    assert model.decode(bytes.fromhex(payload)) == expected


LHT65_BASE = {
    "temperature": 28.29,
    "humidity": 88.6,
    "battery_voltage": 3.062,
    "external_sensor_disconnected": False,
    "reported_battery_status": 0,
}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            "0bf60b0d03760401000000",
            {**LHT65_BASE, "external_input": True, "external_interrupt": False},
        ),
        ("0bf60b0d03760500640000", {**LHT65_BASE, "illuminance": 100}),
        ("0bf60b0d0376060bb80000", {**LHT65_BASE, "external_voltage": 3.0}),
        ("0bf60b0d03760700640000", {**LHT65_BASE, "external_count": 100}),
        ("0bf60b0d03760800000064", {**LHT65_BASE, "external_count": 100}),
        (
            "09f60b0d03760900000000",
            {
                "temperature": 28.29,
                "humidity": 88.6,
                "external_sensor_disconnected": False,
                "external_temperature": 25.5,
                "reported_battery_status": 0,
            },
        ),
        ("0bf60b0d0376017fff0000", {**LHT65_BASE, "external_temperature": None}),
        (
            "0bf60b0d03768100640000",
            {
                "temperature": 28.29,
                "humidity": 88.6,
                "battery_voltage": 3.062,
                "external_sensor_disconnected": True,
                "reported_battery_status": 0,
                "external_temperature": None,
            },
        ),
        ("0000000000000f00000000", {}),
    ],
)
def test_lht65_extension_frames(
    payload: str, expected: dict[str, float | int | bool | None]
) -> None:
    """Each extension decodes its record and reports the shared battery status."""
    assert LHT65.decode(bytes.fromhex(payload)) == expected


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("0000000000000100", "Invalid LHT65 frame length"),
        ("00000000ffff0100000000", "Humidity outside sensor range"),
    ],
)
def test_lht65_rejects_invalid_frames(payload: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        LHT65.decode(bytes.fromhex(payload))


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("017561", {"reported_battery_percent": 97}),
        ("0301ff", {"valve_1_control_failed": True}),
        ("0501ff", {"valve_2_control_failed": True}),
        ("050101", {"valve_2_open": True}),
        ("04c864000000", {"valve_1_pulse_count": 100}),
        ("06c864000000", {"valve_2_pulse_count": 100}),
        ("070101", {"gpio_1": True}),
        ("080100", {"gpio_2": False}),
        ("097b6400", {"pressure_kpa": 100}),
        ("b97b00", {"pressure_kpa": None}),
    ],
)
def test_uc51x_records(
    payload: str, expected: dict[str, float | int | bool | None]
) -> None:
    """Each UC51x record decodes without changing unrelated values."""
    assert UC51x.decode(bytes.fromhex(payload)) == expected


@pytest.mark.parametrize(
    ("model", "payload", "match"),
    [
        (TS201, "017565", "Invalid battery percentage"),
        (TS201, "0175", "Truncated channel data"),
        (UC51x, "017565", "Invalid battery percentage"),
    ],
)
def test_milesight_rejects_invalid_frames(
    model: type[TS201 | UC51x], payload: str, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        model.decode(bytes.fromhex(payload))


@pytest.mark.parametrize(
    ("payload", "illuminance", "notified"),
    [
        ("020310" + "0" * 12, None, False),
        ("010310009435770000", None, True),
        ("01031000c2eb0b0000", None, False),
    ],
)
def test_s2102_non_current_records(
    payload: str, illuminance: float | None, notified: bool
) -> None:
    """Other channels, fault sentinels, and out-of-range values stay unread."""
    device = S2102(descriptor(S2102))
    listener = Mock()
    device.add_update_listener(listener)
    device._receive_event(
        UplinkEvent(
            descriptor=device.descriptor,
            received_at=datetime.now(UTC),
            f_port=2,
            data=bytes.fromhex(payload),
        )
    )
    assert device.illuminance is illuminance
    if notified:
        listener.assert_called_once_with()
    else:
        listener.assert_not_called()

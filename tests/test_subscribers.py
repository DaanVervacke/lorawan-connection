"""Brand-filtered delivery, removal fallback, and listener cleanup."""

from datetime import UTC, datetime

import pytest

from lorawan_connection import (
    AddedEvent,
    DeviceDescriptor,
    DeviceEvent,
    EventType,
    RemovedEvent,
    Unsubscribe,
    UpdatedEvent,
    UplinkEvent,
)
from lorawan_connection._subscribers import Subscribers, inventory_event

BRANDS = frozenset({("chirpstack", 1)})


def descriptor(brand_id: int | str | None, dev_eui: str) -> DeviceDescriptor:
    return DeviceDescriptor(
        network_id="network",
        stack="chirpstack",
        dev_eui=dev_eui,
        name="Device",
        application_id="application",
        profile_id="profile",
        brand_id=brand_id,
    )


FIRST = descriptor(1, "0201010101010101")
SECOND = descriptor(1, "0201010101010102")
OTHER_BRAND = descriptor(2, "0201010101010101")


def uplink(target: DeviceDescriptor) -> UplinkEvent:
    return UplinkEvent(
        descriptor=target,
        received_at=datetime.now(UTC),
        data=b"payload",
    )


def removed_factory(target: DeviceDescriptor) -> DeviceEvent:
    return inventory_event(EventType.REMOVED, target)


def test_replay_delivers_matching_inventory() -> None:
    registry = Subscribers()
    events = []
    unsubscribe = registry.add(BRANDS, events.append, replay=[FIRST, OTHER_BRAND])
    assert [event.type for event in events] == [EventType.ADDED]
    assert events[0].descriptor is FIRST
    unsubscribe()


def test_replay_without_brands_delivers_everything() -> None:
    registry = Subscribers()
    events = []
    registry.add(None, events.append, replay=[FIRST, OTHER_BRAND, SECOND])
    assert [event.descriptor for event in events] == [FIRST, OTHER_BRAND, SECOND]


def test_clearing_during_replay_stops_delivery() -> None:
    registry = Subscribers()
    events = []

    def listener(event: DeviceEvent) -> None:
        events.append(event)
        registry.clear()

    registry.add(None, listener, replay=[FIRST, SECOND])
    assert [event.descriptor for event in events] == [FIRST]


def test_emit_skips_listener_removed_during_delivery() -> None:
    registry = Subscribers()
    delivered = []
    stop_removed: Unsubscribe | None = None

    def remover(event: DeviceEvent) -> None:
        delivered.append("remover")
        assert stop_removed is not None
        stop_removed()

    stop_remover = registry.add(None, remover)
    stop_removed = registry.add(None, lambda event: delivered.append("removed"))
    registry.emit(uplink(FIRST), FIRST, removed_factory)
    assert delivered == ["remover"]
    registry.emit(uplink(FIRST), FIRST, removed_factory)
    assert delivered == ["remover", "remover"]
    stop_remover()
    assert stop_removed is not None
    stop_removed()


def test_unsubscribe_is_idempotent_and_independent() -> None:
    registry = Subscribers()
    events = []
    stop_first = registry.add(BRANDS, events.append)
    stop_second = registry.add(BRANDS, events.append)
    stop_first()
    stop_first()
    registry.emit(uplink(FIRST), FIRST, removed_factory)
    assert len(events) == 1
    stop_second()


def test_brand_change_reports_removal_of_previous() -> None:
    registry = Subscribers()
    events = []
    registry.add(BRANDS, events.append)
    registry.emit(uplink(OTHER_BRAND), OTHER_BRAND, removed_factory, FIRST)
    assert [event.type for event in events] == [EventType.REMOVED]
    assert events[0].descriptor is FIRST


def test_brand_change_keeps_matching_listener() -> None:
    registry = Subscribers()
    events = []
    registry.add(frozenset({("chirpstack", 2)}), events.append)
    event = uplink(OTHER_BRAND)
    registry.emit(event, OTHER_BRAND, removed_factory, FIRST)
    assert events == [event]


def test_emit_without_previous_ignores_unmatched_listener() -> None:
    registry = Subscribers()
    events = []
    registry.add(frozenset({("chirpstack", 2)}), events.append)
    registry.emit(uplink(FIRST), FIRST, removed_factory)
    assert events == []


def test_clear_drops_every_listener() -> None:
    registry = Subscribers()
    events = []
    registry.add(None, events.append)
    registry.clear()
    registry.emit(uplink(FIRST), FIRST, removed_factory)
    assert events == []


@pytest.mark.parametrize(
    ("kind", "event_class"),
    [
        (EventType.ADDED, AddedEvent),
        (EventType.UPDATED, UpdatedEvent),
        (EventType.REMOVED, RemovedEvent),
    ],
)
def test_inventory_event_kind(
    kind: EventType, event_class: type[AddedEvent | UpdatedEvent | RemovedEvent]
) -> None:
    event = inventory_event(kind, FIRST)
    assert isinstance(event, event_class)
    assert event.type is kind
    assert event.descriptor is FIRST

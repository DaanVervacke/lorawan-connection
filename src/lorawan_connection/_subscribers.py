"""Subscriber registries and inventory events shared by the connections."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from .callbacks import Unsubscribe, notify
from .events import (
    AddedEvent,
    DeviceDescriptor,
    DeviceEvent,
    EventType,
    RemovedEvent,
    UpdatedEvent,
)

_INVENTORY_EVENTS: dict[EventType, type[AddedEvent | UpdatedEvent | RemovedEvent]] = {
    EventType.ADDED: AddedEvent,
    EventType.UPDATED: UpdatedEvent,
    EventType.REMOVED: RemovedEvent,
}


def inventory_event(kind: EventType, descriptor: DeviceDescriptor) -> DeviceEvent:
    """Build an inventory event stamped with the current time."""
    return _INVENTORY_EVENTS[kind](received_at=datetime.now(UTC), descriptor=descriptor)


def _removed_now(descriptor: DeviceDescriptor) -> DeviceEvent:
    return inventory_event(EventType.REMOVED, descriptor)


@dataclass(eq=False)
class _Subscriber:
    brands: frozenset[tuple[str, int | str]] | None
    listener: Callable[[DeviceEvent], None]


class Subscribers:
    """Deliver events to brand-filtered listeners with idempotent removal."""

    def __init__(self) -> None:
        self._items: list[_Subscriber] = []

    def add(
        self,
        brands: frozenset[tuple[str, int | str]] | None,
        listener: Callable[[DeviceEvent], None],
        *,
        replay: Iterable[DeviceDescriptor] = (),
    ) -> Unsubscribe:
        """Register one listener, replay matching inventory, and return cleanup."""
        subscriber = _Subscriber(brands, listener)
        self._items.append(subscriber)
        for descriptor in replay:
            if subscriber not in self._items:
                break
            if brands is None or (descriptor.stack, descriptor.brand_id) in brands:
                notify([listener], inventory_event(EventType.ADDED, descriptor))

        def unsubscribe() -> None:
            if subscriber in self._items:
                self._items.remove(subscriber)

        return unsubscribe

    def emit(
        self,
        event: DeviceEvent,
        descriptor: DeviceDescriptor,
        previous: DeviceDescriptor | None = None,
        *,
        build_removed: Callable[[DeviceDescriptor], DeviceEvent] = _removed_now,
    ) -> None:
        """Deliver an event to matching listeners, with a removal fallback."""
        for subscriber in tuple(self._items):
            if subscriber not in self._items:
                continue
            if subscriber.brands is None or (
                (descriptor.stack, descriptor.brand_id) in subscriber.brands
            ):
                notify([subscriber.listener], event)
            elif previous is not None and (
                (previous.stack, previous.brand_id) in subscriber.brands
            ):
                notify([subscriber.listener], build_removed(previous))

    def clear(self) -> None:
        """Drop every listener."""
        self._items.clear()


def deliver(
    subscribers: Subscribers,
    devices: Mapping[str, DeviceDescriptor],
    event: DeviceEvent,
    previous: DeviceDescriptor | None = None,
) -> None:
    """Resolve the event's descriptor and deliver it to matching listeners."""
    descriptor = event.descriptor or devices.get(event.dev_eui)
    if descriptor is None:
        return
    subscribers.emit(event, descriptor, previous)

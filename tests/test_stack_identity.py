"""Match native identities without translating one stack's catalog to another."""

from dataclasses import replace

import pytest

from lorawan_connection import DeviceCollection
from lorawan_connection.mock import MockConnection
from sensecap_lorawan import S2101, SenseCapDeviceCollection

from .conftest import DeviceModel
from .test_sensecap_example import DESCRIPTOR


@pytest.mark.parametrize("stack", ["chirpstack", "tts"])
async def test_same_model_on_either_stack(stack: str) -> None:
    brand, model = S2101.identifiers[stack]
    descriptor = replace(DESCRIPTOR, stack=stack, brand_id=brand, model_id=model)
    connection = MockConnection([descriptor], stack_type=stack)
    collection = SenseCapDeviceCollection(connection)
    await collection.async_setup()
    assert type(collection.devices[descriptor.dev_eui]) is S2101
    collection.close()


async def test_namespace_is_part_of_subscription_and_model_matching() -> None:
    class OtherStack(DeviceModel):
        identifiers = {"other": (744, S2101.identifiers["chirpstack"][1])}

    first = DESCRIPTOR
    second = replace(DESCRIPTOR, stack="other", dev_eui="0000000000000002")
    connection = MockConnection([first], stack_type="chirpstack")
    other_connection = MockConnection([second], stack_type="other")
    sensecap = DeviceCollection(connection, [S2101, OtherStack])
    other = DeviceCollection(other_connection, [S2101, OtherStack])
    await sensecap.async_setup()
    await other.async_setup()
    assert list(sensecap.devices) == [first.dev_eui]
    assert list(other.devices) == [second.dev_eui]
    assert type(sensecap.devices[first.dev_eui]) is S2101
    assert type(other.devices[second.dev_eui]) is OtherStack
    sensecap.close()
    other.close()


def test_duplicate_rejected_within_one_stack() -> None:
    class Alias(DeviceModel):
        identifiers = {"tts": S2101.identifiers["tts"]}

    with pytest.raises(ValueError, match="Duplicate model identity"):
        DeviceCollection(MockConnection(), [S2101, Alias])

"""Versioned in-session sensor registry, independent of legacy radar_core.

Import/export JSON is intentionally postponed to the single Export Centre.
The registry does not modify active solver inputs until an explicit future action.
"""
from dataclasses import asdict
from engineering_contracts import SensorDefinition, SensorType

MAX_SENSORS = 64


def add_sensor(registry, sensor):
    """Return an immutable new registry mapping with a validated revision."""
    if not isinstance(sensor, SensorDefinition):
        raise TypeError("Expected SensorDefinition")
    if not isinstance(registry, dict):
        raise TypeError("Registry must be a dictionary")
    if sensor.sensor_id in registry:
        raise ValueError("Sensor ID already exists; edit by creating a new revision")
    if len(registry) >= MAX_SENSORS:
        raise ValueError("Maximum 64 sensors in one in-memory project")
    return {**registry, sensor.sensor_id: sensor}


def revise_sensor(registry, sensor_id, **changes):
    """Revision is always incremented; previous version remains auditable."""
    if sensor_id not in registry:
        raise KeyError("Unknown sensor")
    before = registry[sensor_id]
    fields = asdict(before)
    if "revision" in changes or "sensor_id" in changes:
        raise ValueError("Identity/revision cannot be directly overwritten")
    if set(changes) - set(fields):
        raise ValueError("Unknown sensor field")
    fields.update(changes)
    fields["revision"] = before.revision + 1
    return {**registry, sensor_id: SensorDefinition(**fields)}


def list_sensors(registry):
    return sorted(registry.values(), key=lambda x: x.sensor_id.casefold())


def from_rows(rows):
    """Validated JSON-like rows, with duplicate-ID rejection and upper bound."""
    if not isinstance(rows, list) or len(rows) > MAX_SENSORS:
        raise ValueError("Invalid sensor list or too many sensors")
    result={}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Sensor row must be object")
        fields=set(SensorDefinition.__dataclass_fields__)
        if set(row)-fields:
            raise ValueError("Unexpected sensor fields")
        sensor=SensorDefinition(**{**row,"kind":SensorType(row["kind"])})
        result=add_sensor(result,sensor)
    return result


def to_rows(registry):
    return [{**asdict(s),"kind":s.kind.value} for s in list_sensors(registry)]

"""Sensor entities for PrimaGas tanks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PrimaGasCoordinator


@dataclass(frozen=True, kw_only=True)
class PrimaGasSensorDescription(SensorEntityDescription):
    """Describes a sensor and how to pull its value out of the asset dict."""

    value_fn: Callable[[dict[str, Any]], Any]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


SENSORS: tuple[PrimaGasSensorDescription, ...] = (
    PrimaGasSensorDescription(
        key="level_percentage",
        translation_key="level_percentage",
        name="Fuellstand",
        icon="mdi:gauge",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda a: a.get("assetCurrentLevelPercentage"),
    ),
    PrimaGasSensorDescription(
        key="filling_volume",
        translation_key="filling_volume",
        name="Aktuelle Fuellmenge",
        icon="mdi:gas-cylinder",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda a: a.get("assetCurrentFillingVolume"),
    ),
    PrimaGasSensorDescription(
        key="capacity",
        translation_key="capacity",
        name="Tank-Kapazitaet",
        icon="mdi:propane-tank",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=lambda a: a.get("assetCapacity"),
    ),
    PrimaGasSensorDescription(
        key="stock_left_days",
        translation_key="stock_left_days",
        name="Reichweite",
        icon="mdi:calendar-clock",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda a: (a.get("tankForecast") or {}).get("stockLeftInDays"),
    ),
    PrimaGasSensorDescription(
        key="predicted_delivery_date",
        translation_key="predicted_delivery_date",
        name="Voraussichtliches Lieferdatum",
        icon="mdi:truck-delivery",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda a: _parse_iso(
            (a.get("tankForecast") or {}).get("predictedReplenishmentDeliveryDate")
        ),
    ),
    PrimaGasSensorDescription(
        key="replenishment_volume",
        translation_key="replenishment_volume",
        name="Empfohlene Liefermenge",
        icon="mdi:gas-station",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=0,
        value_fn=lambda a: (a.get("tankForecast") or {}).get(
            "replenishmentVolumeToDeliverLiter"
        ),
    ),
    PrimaGasSensorDescription(
        key="predicted_runout_date",
        translation_key="predicted_runout_date",
        name="Voraussichtliches Leerdatum",
        icon="mdi:tank-off",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        value_fn=lambda a: _parse_iso(
            (a.get("tankForecast") or {}).get("predictedRunoutDate")
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensor entities for every tank reported by the API."""
    coordinator: PrimaGasCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[PrimaGasTankSensor] = []
    for asset in coordinator.data.get("assets", []):
        if asset.get("assetType") != "Tank":
            continue
        asset_id = asset.get("assetId")
        for desc in SENSORS:
            entities.append(PrimaGasTankSensor(coordinator, asset_id, desc))
    async_add_entities(entities)


class PrimaGasTankSensor(
    CoordinatorEntity[PrimaGasCoordinator], SensorEntity
):
    """One sensor reading from one tank."""

    _attr_has_entity_name = True
    entity_description: PrimaGasSensorDescription

    def __init__(
        self,
        coordinator: PrimaGasCoordinator,
        asset_id: str,
        description: PrimaGasSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._asset_id = asset_id
        self._attr_unique_id = f"{asset_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, asset_id)},
            manufacturer="PrimaGas / SHV Energy",
            model="Fluessiggas-Tank",
            name=f"PrimaGas Tank {asset_id}",
            configuration_url="https://kunden.primagas.de/",
        )

    @callback
    def _current_asset(self) -> dict[str, Any] | None:
        for asset in self.coordinator.data.get("assets", []):
            if asset.get("assetId") == self._asset_id:
                return asset
        return None

    @property
    def native_value(self) -> Any:
        asset = self._current_asset()
        if asset is None:
            return None
        return self.entity_description.value_fn(asset)

    @property
    def available(self) -> bool:
        return super().available and self._current_asset() is not None

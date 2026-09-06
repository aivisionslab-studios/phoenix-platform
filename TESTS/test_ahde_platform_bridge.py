import asyncio
from pathlib import Path

from phoenix_kernel.ahde.contracts import DiscoveryEvent, EventPriority, EventType
from phoenix_kernel.ahde.event_bus import EventBus


def test_ahde_event_history_is_bounded_and_newest_first():
    bus = EventBus()

    async def publish_events():
        for index in range(105):
            await bus.publish(
                EventType.TELEMETRY_UPDATED,
                DiscoveryEvent(
                    event_type=EventType.TELEMETRY_UPDATED,
                    payload={"index": index},
                    timestamp=f"2026-09-02T00:00:{index:02d}Z",
                    priority=EventPriority.NORMAL,
                ),
            )

    asyncio.run(publish_events())
    history = bus.recent_events(100)
    assert len(history) == 100
    assert history[0]["payload"]["index"] == 104
    assert history[-1]["payload"]["index"] == 5


def test_sensor_normalization_uses_observed_values():
    from api_server import _normalize_ahde_devices

    devices = _normalize_ahde_devices([
        {"name": "GPU real", "type": "GpuAmd", "sensors": [
            {"name": "GPU Load", "type": "Load", "value": 37.0, "unit": "%"}
        ]}
    ])
    sensor = devices[0]["sensors"][0]
    assert devices[0]["category"] == "gpu"
    assert sensor["value"] == 37.0
    assert sensor["device"] == "GPU real"


def test_ahde_and_report_routes_are_registered():
    from api_server import app

    paths = {route.path for route in app.routes}
    assert {
        "/api/ahde/sensors",
        "/api/ahde/events",
        "/api/ahde/snapshot",
        "/api/ahde/scan",
        "/api/system/report",
    } <= paths


def test_system_report_ui_contains_no_fabricated_health_or_hardware():
    source = Path("platform_source/src/components/SystemReportModal.tsx").read_text(encoding="utf-8")
    for fabricated in ("46 DOCS", "E5-2690", "RX 580", "HEALTHY", "AHDC-"):
        assert fabricated not in source
    assert "/api/system/report" in source
    assert "não calculada" in source

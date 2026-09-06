import psutil
from .base import ITelemetryProvider
from phoenix_kernel.shared.models import TelemetrySnapshot

class LinuxTelemetryProvider(ITelemetryProvider):
    def get_metrics(self) -> TelemetrySnapshot:
        cpu_usage = psutil.cpu_percent(interval=None)
        ram_usage = psutil.virtual_memory()
        gpu_temp = gpu_load = gpu_vram_used = None

        try:
            from ..core import get_gpu_sensors
            gpu_sensors = get_gpu_sensors()
            gpu_temp = gpu_sensors.get("temperature_celsius")
            gpu_load = gpu_sensors.get("load_percent")
            gpu_vram_used = gpu_sensors.get("vram_used_mb")
        except Exception:
            pass

        return TelemetrySnapshot(
            cpu_usage_percent=cpu_usage,
            ram_used_mb=int(ram_usage.used / (1024 * 1024)),
            gpu_temp_celsius=gpu_temp,
            gpu_load_percent=gpu_load,
            gpu_vram_used_mb=gpu_vram_used
        )
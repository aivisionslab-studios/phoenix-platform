
import platform
def get_telemetry_provider():
    system = platform.system().lower()
    if system == 'windows':
        from .windows import WindowsTelemetryProvider
        return WindowsTelemetryProvider()
    elif system == 'linux':
        from .linux import LinuxTelemetryProvider
        return LinuxTelemetryProvider()
    raise NotImplementedError(f'Telemetry não suportada para {system}')

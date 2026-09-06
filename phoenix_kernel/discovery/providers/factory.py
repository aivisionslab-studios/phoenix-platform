import platform
def get_discovery_provider():
    system = platform.system().lower()
    if system == "windows":
        from .windows import WindowsDiscoveryProvider
        return WindowsDiscoveryProvider()
    elif system == "linux":
        from .linux import LinuxDiscoveryProvider
        return LinuxDiscoveryProvider()
    raise NotImplementedError(f"Discovery não suportado para {system}")

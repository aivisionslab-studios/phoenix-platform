import platform
import subprocess
import logging

logger = logging.getLogger(__name__)

def get_all_hardware_sensors() -> list:
    """Retorna todos os dispositivos e sensores no formato que o HTML espera."""
    system = platform.system().lower()
    if system == "windows":
        return _get_windows_hardware()
    elif system == "linux":
        return _get_linux_hardware()
    return []

def get_gpu_sensors() -> dict:
    """Retorna sensores rápidos da GPU para o /api/state (Temp, Load, VRAM)."""
    system = platform.system().lower()
    if system == "windows":
        return _get_windows_gpu()
    elif system == "linux":
        return _get_linux_gpu()
    return {"temperature_celsius": None, "load_percent": None, "vram_used_mb": None}

# ==========================================
# WINDOWS (LibreHardwareMonitor via pythonnet)
# ==========================================
_win_computer = None
def _get_win_computer():
    global _win_computer
    if _win_computer is not None: return _win_computer
    try:
        import clr
        from HardwareMonitor.Hardware import Computer
        computer = Computer()
        computer.IsCpuEnabled = True
        computer.IsGpuEnabled = True
        computer.IsStorageEnabled = True
        computer.IsMotherboardEnabled = True
        computer.IsMemoryEnabled = True
        computer.IsNetworkEnabled = True
        computer.IsControllerEnabled = True
        computer.Open()
        _win_computer = computer
        return _win_computer
    except Exception as e:
        logger.error(f"Windows HardwareMonitor falhou: {e}")
        return None

def _get_windows_hardware() -> list:
    computer = _get_win_computer()
    if not computer: return []
    devices = []
    units = {"Temperature": "°C", "Load": "%", "Clock": "MHz", "Voltage": "V", "Fan": "RPM", "Power": "W", "Data": "GB", "SmallData": "MB"}
    
    try:
        for hw in computer.Hardware:
            hw.Update()
            sensors = []
            for s in hw.Sensors:
                if s.Value is not None:
                    s_type = str(s.SensorType)
                    sensors.append({"name": s.Name or "Unknown", "type": s_type, "value": float(s.Value), "unit": units.get(s_type, "")})
            if sensors:
                devices.append({"name": hw.Name, "type": str(hw.HardwareType), "sensors": sensors})
            
            sub_hw = getattr(hw, "SubHardware", None) or []
            for sub in sub_hw:
                sub.Update()
                sub_sensors = []
                for s in sub.Sensors:
                    if s.Value is not None:
                        s_type = str(s.SensorType)
                        sub_sensors.append({"name": s.Name or "Unknown", "type": s_type, "value": float(s.Value), "unit": units.get(s_type, "")})
                if sub_sensors:
                    devices.append({"name": f"{hw.Name} / {sub.Name}", "type": str(sub.HardwareType), "sensors": sub_sensors})
    except Exception as e:
        logger.error(f"Erro lendo hardware Windows: {e}")
    return devices

def _get_windows_gpu() -> dict:
    computer = _get_win_computer()
    if not computer: return {"temperature_celsius": None, "load_percent": None, "vram_used_mb": None}
    temp = load = vram = None
    try:
        for hw in computer.Hardware:
            hw.Update()
            if "Gpu" not in str(hw.HardwareType): continue
            for s in hw.Sensors:
                if s.Value is None: continue
                s_type = str(s.SensorType)
                if s_type == "Temperature" and (temp is None or "Core" in s.Name): temp = float(s.Value)
                elif s_type == "Load" and (load is None or "Core" in s.Name): load = float(s.Value)
                elif s_type == "SmallData" and "Memory" in s.Name and "Used" in s.Name: vram = float(s.Value)
    except: pass
    return {"temperature_celsius": temp, "load_percent": load, "vram_used_mb": vram}

# ==========================================
# LINUX (Comandos nativos: lscpu, lspci, lsblk, sensors)
# ==========================================
def _run_cmd(cmd: list) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except: return ""

def _get_linux_hardware() -> list:
    devices = []
    
    # CPU
    cpu_model = _run_cmd(["lscpu"]).split("\n")
    model_name = [line for line in cpu_model if "Model name" in line]
    cpu_name = model_name[0].split(":")[1].strip() if model_name else "Linux CPU"
    cpu_sensors = []
    temps = _run_cmd(["sensors"]).split("\n")
    for line in temps:
        if "Tdie" in line or "Tctl" in line or "Core 0" in line:
            try:
                val = float(line.split("+")[1].split("°")[0])
                cpu_sensors.append({"name": "CPU Temp", "type": "Temperature", "value": val, "unit": "°C"})
                break
            except: pass
    if cpu_sensors:
        devices.append({"name": cpu_name, "type": "Cpu", "sensors": cpu_sensors})
        
    # GPU
    gpu_lines = _run_cmd(["lspci"]).split("\n")
    for line in gpu_lines:
        if "VGA compatible controller" in line or "3D controller" in line:
            gpu_name = line.split(":")[-1].strip()
            gpu_sensors = []
            for t_line in temps:
                if ("edge" in t_line or "junction" in t_line) and "°C" in t_line:
                    try:
                        val = float(t_line.split("+")[1].split("°")[0])
                        gpu_sensors.append({"name": "GPU Temp", "type": "Temperature", "value": val, "unit": "°C"})
                        break
                    except: pass
            devices.append({"name": gpu_name, "type": "Gpu", "sensors": gpu_sensors if gpu_sensors else [{"name": "Status", "type": "Load", "value": 0, "unit": "%"}]})
            
    # Storage
    lsblk_out = _run_cmd(["lsblk", "-d", "-o", "NAME,MODEL,SIZE,ROTA", "--exclude", "1,2,11"])
    for line in lsblk_out.split("\n")[1:]:
        parts = line.split()
        if len(parts) >= 3:
            name = parts[1] if len(parts) > 2 else parts[0]
            size = parts[2] if len(parts) > 2 else "Unknown"
            is_ssd = parts[-1] == "0"
            devices.append({
                "name": f"{name} ({size})",
                "type": "Storage",
                "sensors": [{"name": "Type", "type": "Factor", "value": 1.0 if is_ssd else 0.0, "unit": "SSD/HDD"}]
            })
            
    return devices

def _get_linux_gpu() -> dict:
    temps = _run_cmd(["sensors"]).split("\n")
    temp = None
    for line in temps:
        if ("edge" in line or "junction" in line) and "°C" in line:
            try:
                temp = float(line.split("+")[1].split("°")[0])
                break
            except: pass
            
    vram = None
    vram_file = "/sys/class/drm/card0/device/mem_info_vram_used"
    try:
        with open(vram_file, "r") as f:
            vram = int(f.read().strip()) // (1024 * 1024)
    except: pass
    
    return {"temperature_celsius": temp, "load_percent": None, "vram_used_mb": vram}

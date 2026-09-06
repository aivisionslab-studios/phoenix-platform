import logging
import threading
import platform
import os
import glob
import json
import re
import subprocess

logger = logging.getLogger(__name__)

IS_LINUX = platform.system() == "Linux"

# Windows globals
_computer = None
_diagnostic_logged = False
_hw_lock = threading.Lock()

_SENSOR_UNITS = {"Temperature": "°C", "Load": "%", "Clock": "MHz", "Voltage": "V", "Fan": "RPM", "Power": "W", "Data": "GB", "SmallData": "MB", "Throughput": "B/s", "Factor": "x"}

# ============================================================
# LINUX NATIVE FUNCTIONS
# ============================================================

def _amd_gpu_cards():
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]*/device")):
        vendor_path = os.path.join(card, "vendor")
        if not os.path.exists(vendor_path): continue
        try:
            with open(vendor_path) as f:
                if f.read().strip() == "0x1002": yield card
        except OSError: continue

def _read_sysfs_int(path):
    try:
        with open(path) as f: return int(f.read().strip())
    except (OSError, ValueError): return None

def _gpu_name_linux() -> str:
    try:
        out = subprocess.run(["lspci", "-d", "1002:"], capture_output=True, text=True, timeout=5)
        for line in out.stdout.splitlines():
            if "VGA" in line or "Display" in line or "3D controller" in line:
                return line.split(": ", 1)[-1].strip()
    except: pass
    return "GPU AMD"

_LMSENSORS_TYPE_MAP = {"temp": "Temperature", "fan": "Fan", "in": "Voltage"}

def _lmsensors_devices() -> list:
    try:
        out = subprocess.run(["sensors", "-j"], capture_output=True, text=True, timeout=5)
        data = json.loads(out.stdout)
    except: return []

    devices = []
    for chip_name, chip_data in data.items():
        if not isinstance(chip_data, dict): continue
        sensors = []
        for feature_name, readings in chip_data.items():
            if not isinstance(readings, dict): continue
            for key, value in readings.items():
                if not key.endswith("_input") or not isinstance(value, (int, float)): continue
                prefix = re.match(r"([a-z]+)", key)
                stype = _LMSENSORS_TYPE_MAP.get(prefix.group(1), None) if prefix else None
                if not stype: continue
                sensors.append({
                    "name": feature_name, "type": stype, "value": float(value),
                    "unit": _SENSOR_UNITS.get(stype, "")
                })
        if sensors:
            devices.append({"name": chip_name, "type": "Motherboard", "sensors": sensors})
    return devices

def _parse_lsblk_size_gb(size_str):
    if not size_str: return None
    m = re.match(r"([\d.]+)\s*([KMGT])", size_str.strip(), re.IGNORECASE)
    if not m: return None
    value = float(m.group(1))
    factor = {"K": 1 / 1024 / 1024, "M": 1 / 1024, "G": 1, "T": 1024}.get(m.group(2).upper(), 1)
    return round(value * factor, 1)

def _disk_temps_by_device() -> dict:
    result = {}
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(os.path.join(hwmon, "name")) as f: chip = f.read().strip()
        except: continue
        if chip not in ("drivetemp", "nvme"): continue
        temp = _read_sysfs_int(os.path.join(hwmon, "temp1_input"))
        if temp is None: continue
        block_name = None
        device_path = os.path.join(hwmon, "device")
        block_glob = glob.glob(os.path.join(device_path, "block", "*"))
        if block_glob:
            block_name = os.path.basename(block_glob[0])
        else:
            try: target = os.path.basename(os.path.realpath(device_path))
            except: target = ""
            if target.startswith("nvme"):
                ns_glob = glob.glob(f"/sys/class/nvme/{target}/nvme*n1")
                if ns_glob: block_name = os.path.basename(ns_glob[0])
        if block_name: result[block_name] = temp / 1000.0
    return result

def _storage_devices_linux() -> list:
    try:
        out = subprocess.run(["lsblk", "-d", "-J", "-o", "NAME,MODEL,SIZE,ROTA,TYPE"], capture_output=True, text=True, timeout=5)
        data = json.loads(out.stdout)
    except: return []

    temps_by_dev = _disk_temps_by_device()
    devices = []
    for blk in data.get("blockdevices", []):
        if blk.get("type") != "disk": continue
        name = blk.get("name", "")
        if not name: continue
        kind = "NVMe" if name.startswith("nvme") else "HDD" if blk.get("rota") in (True, "1", 1) else "SSD"
        sensors = []
        size_gb = _parse_lsblk_size_gb(blk.get("size"))
        if size_gb is not None: sensors.append({"name": "Capacity", "type": "Data", "value": size_gb, "unit": "GB"})
        temp = temps_by_dev.get(name)
        if temp is not None: sensors.append({"name": "Temperature", "type": "Temperature", "value": temp, "unit": "°C"})
        if sensors:
            label = (blk.get("model") or "").strip() or name
            devices.append({"name": f"{label} ({kind}, /dev/{name})", "type": kind, "sensors": sensors})
    return devices

def _get_all_hardware_sensors_linux() -> list:
    devices = []
    for card in _amd_gpu_cards():
        sensors = []
        busy = _read_sysfs_int(os.path.join(card, "gpu_busy_percent"))
        if busy is not None: sensors.append({"name": "GPU Load", "type": "Load", "value": float(busy), "unit": _SENSOR_UNITS["Load"]})
        vram_used = _read_sysfs_int(os.path.join(card, "mem_info_vram_used"))
        if vram_used is not None: sensors.append({"name": "GPU Memory Used", "type": "SmallData", "value": vram_used / (1024 * 1024), "unit": _SENSOR_UNITS["SmallData"]})
        vram_total = _read_sysfs_int(os.path.join(card, "mem_info_vram_total"))
        if vram_total is not None: sensors.append({"name": "GPU Memory Total", "type": "SmallData", "value": vram_total / (1024 * 1024), "unit": _SENSOR_UNITS["SmallData"]})
        for hwmon_path in glob.glob(os.path.join(card, "hwmon", "hwmon*", "temp1_input")):
            milli_c = _read_sysfs_int(hwmon_path)
            if milli_c is not None: sensors.append({"name": "GPU Core", "type": "Temperature", "value": milli_c / 1000.0, "unit": _SENSOR_UNITS["Temperature"]})
        if sensors: devices.append({"name": _gpu_name_linux(), "type": "GpuAmd", "sensors": sensors})

    devices.extend(_lmsensors_devices())
    devices.extend(_storage_devices_linux())
    return devices

def _get_gpu_static_specs_linux() -> list:
    specs = []
    for card in _amd_gpu_cards():
        vram_total = _read_sysfs_int(os.path.join(card, "mem_info_vram_total"))
        specs.append({"model": _gpu_name_linux(), "vram_mb": int(vram_total / (1024 * 1024)) if vram_total else 0})
    return specs

def _get_gpu_sensors_linux() -> dict:
    for card in _amd_gpu_cards():
        temp = load = vram_used = None
        busy = _read_sysfs_int(os.path.join(card, "gpu_busy_percent"))
        if busy is not None: load = float(busy)
        vram = _read_sysfs_int(os.path.join(card, "mem_info_vram_used"))
        if vram is not None: vram_used = vram / (1024 * 1024)
        for hwmon_path in glob.glob(os.path.join(card, "hwmon", "hwmon*", "temp1_input")):
            milli_c = _read_sysfs_int(hwmon_path)
            if milli_c is not None: temp = milli_c / 1000.0; break
        return {"temperature_celsius": temp, "load_percent": load, "vram_used_mb": vram_used}
    return {"temperature_celsius": None, "load_percent": None, "vram_used_mb": None}


# ============================================================
# WINDOWS FUNCTIONS (Preserved exactly as they were)
# ============================================================

def _get_computer():
    global _computer
    if _computer is not None: return _computer
    try:
        import clr
    except ImportError:
        logger.warning("pacote 'pythonnet' não instalado.")
        return None
    try:
        from HardwareMonitor.Hardware import Computer
    except ImportError:
        logger.warning("pacote 'HardwareMonitor' não instalado.")
        return None
    except Exception as e:
        logger.error(f"falha ao carregar HardwareMonitor.Hardware: {e}")
        return None
    try:
        computer = Computer()
        computer.IsCpuEnabled = True
        computer.IsGpuEnabled = True
        for flag in ("IsMotherboardEnabled", "IsMemoryEnabled", "IsStorageEnabled", "IsNetworkEnabled", "IsControllerEnabled", "IsPsuEnabled", "IsBatteryEnabled"):
            try: setattr(computer, flag, True)
            except: pass
        computer.Open()
        _computer = computer
        return _computer
    except Exception as e:
        logger.warning(f"falha ao abrir Computer(): {e}")
        return None

def _log_diagnostic_once(computer):
    global _diagnostic_logged
    if _diagnostic_logged: return
    _diagnostic_logged = True
    try:
        hw_list = list(computer.Hardware)
        logger.info(f"[HW DIAGNOSTIC] {len(hw_list)} dispositivo(s) detectado(s).")
    except: pass

def _collect_sensors(hw) -> list:
    out = []
    for sensor in hw.Sensors:
        if sensor.Value is None: continue
        stype = str(sensor.SensorType)
        try: value = float(sensor.Value)
        except: continue
        out.append({"name": sensor.Name or "", "type": stype, "value": value, "unit": _SENSOR_UNITS.get(stype, "")})
    return out


# ============================================================
# PUBLIC API (Multi-OS Router)
# ============================================================

def get_all_hardware_sensors() -> list:
    if IS_LINUX: return _get_all_hardware_sensors_linux()
    
    computer = _get_computer()
    if computer is None: return []
    _log_diagnostic_once(computer)
    devices = []
    
    with _hw_lock:
        try:
            for hw in computer.Hardware:
                try:
                    hw.Update()
                    sensors = _collect_sensors(hw)
                    if sensors: devices.append({"name": hw.Name, "type": str(hw.HardwareType), "sensors": sensors})
                    
                    sub_hw_list = getattr(hw, "SubHardware", None) or []
                    for sub in sub_hw_list:
                        try:
                            sub.Update()
                            sub_sensors = _collect_sensors(sub)
                            if sub_sensors: devices.append({"name": f"{hw.Name} / {sub.Name}", "type": str(sub.HardwareType), "sensors": sub_sensors})
                        except: pass
                except Exception as e:
                    logger.debug(f"Erro lendo hardware {hw.Name}: {e}")
        except Exception as e:
            logger.warning(f"erro geral lendo sensores: {e}")
            
    return devices

def get_gpu_static_specs() -> list:
    if IS_LINUX: return _get_gpu_static_specs_linux()
    
    computer = _get_computer()
    if computer is None: return []
    specs = []
    with _hw_lock:
        try:
            for hw in computer.Hardware:
                try:
                    hw.Update()
                    if "Gpu" not in str(hw.HardwareType): continue
                    vram_total_mb = 0
                    for sensor in hw.Sensors:
                        if str(sensor.SensorType) == "SmallData" and sensor.Name == "GPU Memory Total" and sensor.Value is not None:
                            vram_total_mb = int(float(sensor.Value))
                            break
                    specs.append({"model": hw.Name, "vram_mb": vram_total_mb})
                except: pass
        except: pass
    return specs

def get_gpu_sensors() -> dict:
    if IS_LINUX: return _get_gpu_sensors_linux()
    
    computer = _get_computer()
    if computer is None: return {"temperature_celsius": None, "load_percent": None, "vram_used_mb": None}
    _log_diagnostic_once(computer)
    temp = load = vram_used = None
    
    with _hw_lock:
        try:
            for hw in computer.Hardware:
                try:
                    hw.Update()
                    if "Gpu" not in str(hw.HardwareType): continue
                    for sensor in hw.Sensors:
                        name = sensor.Name or ""
                        sensor_type = str(sensor.SensorType)
                        value = sensor.Value
                        if value is None: continue
                        if sensor_type == "Temperature":
                            if temp is None or "Core" in name: temp = float(value)
                        elif sensor_type == "Load":
                            if load is None or "Core" in name: load = float(value)
                        elif sensor_type == "SmallData" and "Memory" in name and "Used" in name:
                            vram_used = float(value)
                except: pass
        except: pass
        
    return {"temperature_celsius": temp, "load_percent": load, "vram_used_mb": vram_used}
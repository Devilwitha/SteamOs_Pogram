"""Liest CPU-/GPU-Auslastung sowie eine repraesentative Temperatur direkt
aus sysfs/procfs - bewusst ohne psutil o.ae. Zusatzpaket, damit
stats_monitor.py ohne zusaetzliche pip-Installation auf SteamOS laeuft
(siehe auch gui/gui_server.py, das aus demselben Grund nur die
Standardbibliothek nutzt).

Alle drei Funktionen liefern None, wenn der jeweilige Wert auf diesem
System nicht ermittelbar ist (z. B. kein AMD-GPU-Treiber) - stats_monitor.py
zeigt das als "--" an, statt abzustuerzen.
"""
from pathlib import Path

# Bei mehreren GPUs (z. B. ein Test-PC mit iGPU+dGPU) waehlt dieser Index
# die zu verwendende Karte unter /sys/class/drm/. Auf einem echten Steam
# Deck (nur eine APU) ist 0 immer richtig.
GPU_CARD_INDEX = 0

_last_cpu_times = None


def cpu_percent():
    """Prozentuale CPU-Auslastung (ueber alle Kerne gemittelt) seit dem
    letzten Aufruf, berechnet aus den kumulativen Zeiten in /proc/stat
    (erste Zeile 'cpu ...', siehe `man proc` - Felder: user, nice, system,
    idle, iowait, irq, softirq, ...). Braucht zwei Messpunkte fuer einen
    sinnvollen Wert - beim allerersten Aufruf (z. B. gleich nach Programmstart)
    daher 0.0."""
    global _last_cpu_times
    try:
        with open("/proc/stat") as f:
            fields = [int(x) for x in f.readline().split()[1:]]
    except (OSError, ValueError, IndexError):
        return None

    idle = fields[3] + fields[4]  # idle + iowait
    total = sum(fields)

    if _last_cpu_times is None:
        _last_cpu_times = (idle, total)
        return 0.0

    last_idle, last_total = _last_cpu_times
    _last_cpu_times = (idle, total)

    delta_total = total - last_total
    delta_idle = idle - last_idle
    if delta_total <= 0:
        return 0.0
    return round(100.0 * (delta_total - delta_idle) / delta_total, 1)


def gpu_percent():
    """Aktuelle GPU-Auslastung in Prozent ueber den amdgpu-Treiber
    (Standard auf SteamOS/Steam Deck) - None, wenn nicht verfuegbar (z. B.
    kein AMD-GPU-Treiber bzw. GPU_CARD_INDEX zeigt auf keine vorhandene
    Karte)."""
    path = Path(f"/sys/class/drm/card{GPU_CARD_INDEX}/device/gpu_busy_percent")
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _read_hwmon_temp(hwmon_dir, preferred_labels):
    """Temperatur (Grad Celsius) eines hwmon-Verzeichnisses: bevorzugt den
    ersten Sensor, dessen Label (tempN_label) in preferred_labels
    vorkommt, sonst den ersten ueberhaupt vorhandenen tempN_input."""
    labeled = {}
    for temp_input in sorted(hwmon_dir.glob("temp*_input")):
        label_file = temp_input.with_name(temp_input.name.replace("_input", "_label"))
        try:
            label = label_file.read_text().strip()
        except OSError:
            label = None
        labeled.setdefault(label, temp_input)

    path = None
    for wanted in preferred_labels:
        if wanted in labeled:
            path = labeled[wanted]
            break
    if path is None and labeled:
        path = next(iter(labeled.values()))
    if path is None:
        return None

    try:
        return int(path.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def _find_hwmon_temp(preferred_names, preferred_labels=()):
    hwmon_root = Path("/sys/class/hwmon")
    if not hwmon_root.is_dir():
        return None
    for hwmon_dir in sorted(hwmon_root.iterdir()):
        try:
            name = (hwmon_dir / "name").read_text().strip()
        except OSError:
            continue
        if name not in preferred_names:
            continue
        temp = _read_hwmon_temp(hwmon_dir, preferred_labels)
        if temp is not None:
            return temp
    return None


def temperature():
    """Repraesentative Systemtemperatur in Grad Celsius. Auf SteamOS/Steam
    Deck sitzen CPU und GPU auf derselben APU - deshalb der amdgpu-
    'junction'-Sensor (SoC-Hotspot) als erste Wahl, mit 'edge' als
    Rueckfallwert. Auf Systemen ohne amdgpu (z. B. ein separater
    Test-PC mit diskreter CPU) wird stattdessen k10temp/coretemp
    verwendet. None, wenn gar kein passender Sensor gefunden wurde."""
    temp = _find_hwmon_temp({"amdgpu"}, preferred_labels=("junction", "edge"))
    if temp is not None:
        return round(temp, 1)
    temp = _find_hwmon_temp({"k10temp", "coretemp"})
    if temp is not None:
        return round(temp, 1)
    return None

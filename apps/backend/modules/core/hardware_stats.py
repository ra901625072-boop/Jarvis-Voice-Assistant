"""
modules/core/hardware_stats.py — Centralised hardware monitoring.

Provides:
  get_cpu_temperature()  — Real hardware temperature (WMI on Windows, psutil elsewhere)
  get_stats()            — Cached (cpu_percent, temp) for high-frequency callers
  start_tracking()       — Starts the background polling thread

Both the Flask HTTP route (/stats) and the WebRTC stats_publisher in agent.py
import get_cpu_temperature() from here to ensure consistent readings.
"""
import sys
import psutil
import threading
import time
import logging

logger = logging.getLogger("JARVIS.HardwareStats")

# ── Background polling cache ─────────────────────────────────────────────────
_cpu_percent: float = 0.0
_cached_temp: float | None = None
_lock = threading.Lock()
_initialized = False


def get_cpu_temperature() -> float | None:
    """
    Read the real CPU temperature.

    Returns degrees Celsius as a float, or None if unavailable.
    Uses WMI on Windows; psutil.sensors_temperatures() on Linux/macOS.
    """
    if sys.platform != "win32":
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for _name, entries in temps.items():
                    if entries:
                        return entries[0].current
        except Exception:
            pass
        return None

    # Windows: WMI thermal zone
    try:
        import wmi  # type: ignore

        w = wmi.WMI(namespace="root\\wmi")
        zones = w.MSAcpi_ThermalZoneTemperature()
        if zones:
            raw_temp = zones[0].CurrentTemperature
            celsius = (raw_temp / 10.0) - 273.15
            if 0 <= celsius <= 120:
                return round(celsius, 1)
    except Exception:
        pass
    return None


def _update_loop() -> None:
    """Background daemon that refreshes cpu_percent every second."""
    global _cpu_percent, _cached_temp
    psutil.cpu_percent(interval=None)  # prime the counter
    while True:
        time.sleep(1.0)
        try:
            cpu = psutil.cpu_percent(interval=None)
            temp = get_cpu_temperature()
            with _lock:
                _cpu_percent = cpu
                _cached_temp = temp
        except Exception:
            pass


def start_tracking() -> None:
    """Start the background hardware polling thread (idempotent)."""
    global _initialized
    if not _initialized:
        _initialized = True
        threading.Thread(
            target=_update_loop,
            daemon=True,
            name="JarvisHardwareStats",
        ).start()
        logger.debug("Hardware stats background tracker started.")


def get_stats() -> tuple[float, float | None]:
    """Return cached (cpu_percent, temperature_celsius) for high-frequency callers."""
    with _lock:
        return _cpu_percent, _cached_temp

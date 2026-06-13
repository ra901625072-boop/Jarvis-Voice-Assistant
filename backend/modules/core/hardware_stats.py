import psutil
import threading
import time

_cpu_percent = 0.0
_temp = 42.0
_lock = threading.Lock()
_initialized = False

def _update_loop():
    global _cpu_percent, _temp
    psutil.cpu_percent(interval=None)
    while True:
        time.sleep(1.0)
        try:
            cpu = psutil.cpu_percent(interval=None)
            with _lock:
                _cpu_percent = cpu
                _temp = 42.0 + (cpu * 0.43)
        except Exception:
            pass

def start_tracking():
    global _initialized
    if not _initialized:
        _initialized = True
        threading.Thread(target=_update_loop, daemon=True).start()

def get_stats():
    with _lock:
        return _cpu_percent, _temp

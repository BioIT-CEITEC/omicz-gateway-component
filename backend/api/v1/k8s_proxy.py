import json
import os
import subprocess
import threading
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger

logger = get_logger("k8s_proxy")

router = APIRouter()

# ── Config paths ──────────────────────────────────────────────────────────────
CONFIG_DIR      = "/app/k8s_proxy_config"
KUBECONFIG_PATH = os.path.join(CONFIG_DIR, "kubeconfig.yaml")
SETTINGS_PATH   = os.path.join(CONFIG_DIR, "settings.json")

os.makedirs(CONFIG_DIR, exist_ok=True)

# ── In-memory state ───────────────────────────────────────────────────────────
_process: Optional[subprocess.Popen] = None
_logs:    deque = deque(maxlen=200)   # last 200 lines
_lock:    threading.Lock = threading.Lock()


# ── Schemas ───────────────────────────────────────────────────────────────────
class ProxyConfig(BaseModel):
    namespace:    str
    service_name: str
    local_port:   int = 8080
    remote_port:  int = 8080
    kubeconfig:   str  # full kubeconfig text


class ProxyConfigResponse(BaseModel):
    namespace:      str
    service_name:   str
    local_port:     int
    remote_port:    int
    has_kubeconfig: bool


class StatusResponse(BaseModel):
    status: str            # "running" | "stopped" | "error"
    pid:    Optional[int] = None


# ── Helpers ───────────────────────────────────────────────────────────────────
def _load_settings() -> Optional[dict]:
    if not os.path.isfile(SETTINGS_PATH):
        return None
    with open(SETTINGS_PATH) as f:
        return json.load(f)


def _get_status() -> dict:
    global _process
    if _process is None:
        return {"status": "stopped", "pid": None}
    retcode = _process.poll()
    if retcode is None:
        return {"status": "running", "pid": _process.pid}
    return {"status": "error", "pid": None}


def _set_process(proc):
    global _process
    _process = proc


def _kill_port(port: int):
    """Kill any process listening on the given TCP port (Linux /proc only)."""
    hex_port = f"{port:04X}"
    try:
        with open("/proc/net/tcp") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 10 or parts[3] != "0A":   # 0A = LISTEN
                    continue
                _, lport = parts[1].split(":")
                if lport.upper() != hex_port:
                    continue
                inode = parts[9]
                # find PID that owns this socket inode
                for pid_dir in os.listdir("/proc"):
                    if not pid_dir.isdigit():
                        continue
                    fd_dir = f"/proc/{pid_dir}/fd"
                    try:
                        for fd in os.listdir(fd_dir):
                            target = os.readlink(f"{fd_dir}/{fd}")
                            if target == f"socket:[{inode}]":
                                logger.info(f"[kubectl] killing PID {pid_dir} holding port {port}")
                                os.kill(int(pid_dir), 9)
                                break
                    except (PermissionError, FileNotFoundError, ProcessLookupError):
                        continue
    except Exception as e:
        logger.warning(f"[kubectl] _kill_port({port}) failed: {e}")


def _read_output(proc: subprocess.Popen):
    """Background thread: reads kubectl output, appends to _logs, then auto-restarts."""
    for line in proc.stdout:
        line = line.rstrip()
        with _lock:
            _logs.append(line)
        logger.info(f"[kubectl] {line}")
    returncode = proc.returncode
    with _lock:
        _logs.append(f"[kubectl] process exited (returncode={returncode})")
    logger.warning(f"kubectl port-forward exited with returncode={returncode}")

    # auto-restart: only if this is still the active process (not manually stopped)
    with _lock:
        still_active = (_process is proc)
    if not still_active:
        logger.info("[kubectl] process was manually stopped — not restarting")
        return

    logger.info("[kubectl] auto-restarting in 2s…")

    # ensure old process and anything else holding the port is gone
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass
    if settings := _load_settings():
        _kill_port(settings.get("local_port", 8080))
    time.sleep(2)  # let OS release the port

    settings = _load_settings()
    if not settings or not os.path.isfile(KUBECONFIG_PATH):
        logger.warning("[kubectl] cannot auto-restart — no config/kubeconfig found")
        return

    cmd = [
        "kubectl", "port-forward",
        "--address", "0.0.0.0",
        f"service/{settings['service_name']}",
        f"{settings['local_port']}:{settings['remote_port']}",
        "-n", settings["namespace"],
        "--kubeconfig", KUBECONFIG_PATH,
    ]
    logger.info(f"[kubectl] restarting: {' '.join(cmd)}")
    new_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    with _lock:
        _logs.append(f"[kubectl] restarted (pid={new_proc.pid})")
    _set_process(new_proc)
    threading.Thread(target=_read_output, args=[new_proc], daemon=True).start()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=StatusResponse)
def get_status():
    return _get_status()


@router.get("/config", response_model=ProxyConfigResponse)
def get_config():
    settings = _load_settings()
    if not settings:
        raise HTTPException(status_code=404, detail="no config saved yet")
    return {**settings, "has_kubeconfig": os.path.isfile(KUBECONFIG_PATH)}


@router.post("/config")
def save_config(config: ProxyConfig):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump({
            "namespace":    config.namespace,
            "service_name": config.service_name,
            "local_port":   config.local_port,
            "remote_port":  config.remote_port,
        }, f)
    with open(KUBECONFIG_PATH, "w") as f:
        f.write(config.kubeconfig)
    logger.info(f"k8s proxy config saved: {config.namespace}/{config.service_name} {config.local_port}:{config.remote_port}")
    return {"detail": "config saved"}


@router.post("/start")
def start_proxy():
    global _process

    with _lock:
        if _process is not None and _process.poll() is None:
            raise HTTPException(status_code=409, detail="proxy is already running")

    settings = _load_settings()
    if not settings:
        raise HTTPException(status_code=400, detail="no config saved — save config first")
    if not os.path.isfile(KUBECONFIG_PATH):
        raise HTTPException(status_code=400, detail="no kubeconfig saved — save config first")

    cmd = [
        "kubectl", "port-forward",
        "--address", "0.0.0.0",
        f"service/{settings['service_name']}",
        f"{settings['local_port']}:{settings['remote_port']}",
        "-n", settings["namespace"],
        "--kubeconfig", KUBECONFIG_PATH,
    ]

    logger.info(f"starting: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    with _lock:
        _process = proc
        _logs.clear()

    threading.Thread(target=_read_output, args=[proc], daemon=True).start()

    return {"detail": "proxy started", "pid": proc.pid}


@router.post("/stop")
def stop_proxy():
    global _process

    with _lock:
        if _process is None or _process.poll() is not None:
            raise HTTPException(status_code=409, detail="proxy is not running")
        _process.terminate()
        _process = None

    logger.info("kubectl port-forward stopped")
    return {"detail": "proxy stopped"}


@router.get("/logs")
def get_logs():
    with _lock:
        return {"logs": list(_logs)}

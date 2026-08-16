from __future__ import annotations

import datetime as dt
import logging
import os
import platform
import shlex
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import psutil
from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.storage import load_state, save_state

try:
    import paramiko
except ImportError:  # pragma: no cover - runtime dependency check
    paramiko = None


# Basic app settings. Most of these can be changed with env vars while testing.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def load_local_env(path: Path) -> None:
    """Tiny .env loader so local setup stays simple without another dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env(PROJECT_ROOT / ".env")
STALE_AFTER_SECONDS = int(os.getenv("HEALTHIT_STALE_AFTER_SECONDS", "60"))
TELEMETRY_TOKEN = os.getenv("HEALTHIT_TELEMETRY_TOKEN")
ENABLE_SSH = os.getenv("HEALTHIT_ENABLE_SSH", "false").lower() == "true"
SSH_USER = os.getenv("HEALTHIT_SSH_USER")
SSH_TIMEOUT_SECONDS = int(os.getenv("HEALTHIT_SSH_TIMEOUT_SECONDS", "12"))
TERMINAL_TIMEOUT_SECONDS = int(os.getenv("HEALTHIT_TERMINAL_TIMEOUT_SECONDS", "30"))

logging.basicConfig(
    level=os.getenv("HEALTHIT_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("healthit")

app = FastAPI(
    title="HealthIT System Monitor",
    description="Lightweight telemetry dashboard for local computers, homelab nodes, and small clusters.",
    version="1.0.0",
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "HEALTHIT_ALLOWED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-HealthIT-Token"],
)


# API request/response shapes. Keeping these near the top makes the backend easier to scan.
class TelemetryPayload(BaseModel):
    identity: dict[str, Any] = Field(default_factory=dict)
    hardware: dict[str, Any] = Field(default_factory=dict)
    cpu: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    disk: dict[str, Any] = Field(default_factory=dict)
    network: dict[str, Any] = Field(default_factory=dict)
    packets: dict[str, Any] = Field(default_factory=dict)
    errors: dict[str, Any] = Field(default_factory=dict)
    alerts: list[str] = Field(default_factory=list)
    overall_status: str | None = None
    last_seen: str | None = None
    display_name: str | None = None
    tags: list[str] = Field(default_factory=list)


class TaskRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=120)
    mode: str = Field(default="safe", pattern="^(safe|ssh)$")


class TaskResult(BaseModel):
    task_id: str
    machine_key: str
    status: str
    output: str
    completed_at: str | None = None


class TerminalSessionCreate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    machine_key: str | None = Field(default=None, max_length=160)


class TerminalCommandRequest(BaseModel):
    command: str = Field(default="", max_length=2000)


class TerminalSessionRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class MachineRegistration(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    host: str | None = Field(default=None, max_length=160)
    tags: list[str] = Field(default_factory=list)


class SshDeployRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    host: str = Field(..., min_length=1, max_length=160)
    controller_url: str | None = Field(default=None, max_length=300)
    login_type: str = Field(default="key", pattern="^(key|password)$")
    ssh_user: str = Field(default="pi", min_length=1, max_length=80)
    ssh_password: str | None = Field(default=None, max_length=500)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    tags: list[str] = Field(default_factory=list)


class MachineUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    host: str | None = Field(default=None, max_length=160)
    tags: list[str] | None = None


# Prototype storage. SQLite saves these dictionaries so the dashboard survives restarts.
remote_machines: dict[str, dict[str, Any]] = {}
registered_machines: dict[str, dict[str, Any]] = {}
machine_overrides: dict[str, dict[str, Any]] = {}
task_queues: dict[str, list[dict[str, Any]]] = {}
task_results: dict[str, list[dict[str, Any]]] = {}
terminal_sessions: dict[str, dict[str, Any]] = {}
saved_state = load_state()
remote_machines.update(saved_state["remote_machines"])
registered_machines.update(saved_state["registered_machines"])
machine_overrides.update(saved_state["machine_overrides"])
terminal_sessions.update(saved_state["terminal_sessions"])
task_results.update(saved_state["task_results"])
ALLOWED_TASKS = {
    "help",
    "status",
    "refresh",
    "uptime",
    "whoami",
    "ip",
    "disk",
    "memory",
    "network",
    "alerts",
}


def persist_state() -> None:
    """Save the parts of state that should survive a dashboard restart."""
    save_state(
        remote_machines=remote_machines,
        registered_machines=registered_machines,
        machine_overrides=machine_overrides,
        terminal_sessions=terminal_sessions,
        task_results=task_results,
    )


def format_uptime(seconds: int) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60

    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def get_cpu_status(cpu_percent: float) -> str:
    if cpu_percent < 50:
        return "Good Standing"
    if cpu_percent < 80:
        return "Moderate Load"
    return "High Load"


def get_memory_status(memory_percent: float) -> str:
    if memory_percent < 60:
        return "Good Standing"
    if memory_percent < 80:
        return "Maintenance Suggested"
    return "Memory Overload"


def get_disk_status(disk_percent: float) -> str:
    if disk_percent < 70:
        return "Good Standing"
    if disk_percent < 90:
        return "Maintenance Suggested"
    return "Critical Condition"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_ip_addresses() -> list[dict[str, str]]:
    ip_addresses = []
    for interface_name, address_list in psutil.net_if_addrs().items():
        for addr in address_list:
            if addr.family == socket.AF_INET and addr.address != "127.0.0.1":
                ip_addresses.append({"interface": interface_name, "ip_address": addr.address})
    return ip_addresses


def get_mac_addresses() -> list[dict[str, str]]:
    mac_addresses = []
    for interface_name, address_list in psutil.net_if_addrs().items():
        for addr in address_list:
            addr_family = str(addr.family)
            if ("AF_LINK" in addr_family or "AF_PACKET" in addr_family) and addr.address:
                mac_addresses.append({"interface": interface_name, "mac_address": addr.address})
    return mac_addresses


def get_system_identity() -> dict[str, Any]:
    """Collect the identity fields that make this machine recognizable."""
    boot_time = psutil.boot_time()
    uptime_seconds = int(dt.datetime.now().timestamp() - boot_time)

    return {
        "hostname": socket.gethostname(),
        "device_name": platform.node(),
        "os_type": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "current_user": os.getenv("USERNAME") or os.getenv("USER") or "Unknown",
        "ip_addresses": get_ip_addresses(),
        "mac_addresses": get_mac_addresses(),
        "boot_time": dt.datetime.fromtimestamp(boot_time).isoformat(),
        "uptime_seconds": uptime_seconds,
        "uptime_readable": format_uptime(uptime_seconds),
        "machine_id": str(uuid.getnode()),
    }


def get_cpu_model() -> str:
    cpu_model = platform.processor()
    if cpu_model and cpu_model.strip():
        return cpu_model

    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as file:
                for line in file:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        except OSError as exc:
            logger.debug("Could not read /proc/cpuinfo: %s", exc)

    return "Unavailable"


def get_disk_models() -> list[dict[str, str]]:
    if platform.system() != "Linux":
        return []

    result = subprocess.run(
        ["lsblk", "-d", "-o", "NAME,MODEL,SIZE,TYPE"],
        capture_output=True,
        text=True,
        check=False,
    )

    disk_models = []
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) >= 4:
            disk_models.append(
                {"name": parts[0], "model": parts[1], "size": parts[2], "type": parts[3]}
            )
    return disk_models


def get_temperature_info() -> dict[str, Any]:
    temperatures = []
    max_temp = None

    if not hasattr(psutil, "sensors_temperatures"):
        return {"max_temp_c": None, "sensors": temperatures}

    try:
        temp_data = psutil.sensors_temperatures()
    except (AttributeError, OSError) as exc:
        logger.debug("Temperature sensors unavailable: %s", exc)
        return {"max_temp_c": None, "sensors": temperatures}

    for sensor_name, entries in temp_data.items():
        for entry in entries:
            current_temp = entry.current
            temperatures.append(
                {
                    "sensor": sensor_name,
                    "label": entry.label or sensor_name,
                    "current_c": current_temp,
                    "high_c": entry.high,
                    "critical_c": entry.critical,
                }
            )
            if current_temp is not None and (max_temp is None or current_temp > max_temp):
                max_temp = current_temp

    return {"max_temp_c": max_temp, "sensors": temperatures}


def get_failed_services() -> list[str]:
    if platform.system() != "Linux":
        return []

    result = subprocess.run(
        ["systemctl", "--failed", "--no-legend", "--plain"],
        capture_output=True,
        text=True,
        check=False,
    )

    return [line.split()[0] for line in result.stdout.strip().splitlines() if line.strip()]


def get_hardware_info() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    return {
        "cpu_model": get_cpu_model(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "total_memory_gb": round(memory.total / (1024**3), 2),
        "disk_devices": get_disk_models(),
        "temperature": get_temperature_info(),
    }


def collect_storage_info() -> dict[str, Any]:
    partitions = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except OSError:
            continue
        partitions.append(
            {
                "device": partition.device,
                "mountpoint": partition.mountpoint,
                "fstype": partition.fstype,
                "percent": usage.percent,
                "used_gb": round(usage.used / (1024**3), 2),
                "total_gb": round(usage.total / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
            }
        )

    try:
        io = psutil.disk_io_counters()
        disk_io = {
            "read_gb": round(io.read_bytes / (1024**3), 2),
            "write_gb": round(io.write_bytes / (1024**3), 2),
            "read_count": io.read_count,
            "write_count": io.write_count,
        }
    except Exception:
        disk_io = {}

    return {"partitions": partitions, "io": disk_io}


def collect_network_interfaces() -> list[dict[str, Any]]:
    interfaces = []
    addresses = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    for name, addr_list in addresses.items():
        interfaces.append(
            {
                "name": name,
                "is_up": stats.get(name).isup if name in stats else None,
                "speed_mbps": stats.get(name).speed if name in stats else None,
                "mtu": stats.get(name).mtu if name in stats else None,
                "addresses": [
                    {
                        "family": str(addr.family),
                        "address": addr.address,
                        "netmask": addr.netmask,
                    }
                    for addr in addr_list
                ],
            }
        )
    return interfaces


def collect_process_info(limit: int = 8) -> dict[str, Any]:
    processes = []
    for proc in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent", "status"]):
        try:
            info = proc.info
            processes.append(
                {
                    "pid": info.get("pid"),
                    "name": info.get("name") or "unknown",
                    "username": info.get("username") or "unknown",
                    "cpu_percent": round(info.get("cpu_percent") or 0, 1),
                    "memory_percent": round(info.get("memory_percent") or 0, 2),
                    "status": info.get("status") or "unknown",
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    top_cpu = sorted(processes, key=lambda item: item["cpu_percent"], reverse=True)[:limit]
    top_memory = sorted(processes, key=lambda item: item["memory_percent"], reverse=True)[:limit]
    return {
        "count": len(processes),
        "top_cpu": top_cpu,
        "top_memory": top_memory,
    }


def collect_power_info() -> dict[str, Any]:
    if not hasattr(psutil, "sensors_battery"):
        return {"battery": None}
    try:
        battery = psutil.sensors_battery()
    except Exception:
        battery = None
    if battery is None:
        return {"battery": None}
    return {
        "battery": {
            "percent": battery.percent,
            "power_plugged": battery.power_plugged,
            "seconds_left": battery.secsleft,
        }
    }


def collect_user_sessions() -> list[dict[str, Any]]:
    users = []
    try:
        for user in psutil.users():
            users.append(
                {
                    "name": user.name,
                    "terminal": user.terminal,
                    "host": user.host,
                    "started": dt.datetime.fromtimestamp(user.started).isoformat(),
                }
            )
    except Exception:
        pass
    return users


def collect_system_metrics() -> dict[str, Any]:
    """Grab the live values shown in the main metric cards."""
    cpu_percent = psutil.cpu_percent(interval=1)
    per_cpu = psutil.cpu_percent(interval=None, percpu=True)
    cpu_freq = psutil.cpu_freq()
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk_path = "/" if platform.system() != "Windows" else "C:\\"
    disk = psutil.disk_usage(disk_path)
    net = psutil.net_io_counters()

    cpu_status = get_cpu_status(cpu_percent)
    memory_status = get_memory_status(memory.percent)
    disk_status = get_disk_status(disk.percent)
    network_sent_mb = net.bytes_sent / (1024**2)
    network_received_mb = net.bytes_recv / (1024**2)

    return {
        "cpu": {
            "percent": round(cpu_percent, 1),
            "per_core_percent": [round(value, 1) for value in per_cpu],
            "frequency_mhz": round(cpu_freq.current, 1) if cpu_freq else None,
            "status": cpu_status,
            "comment": {
                "Good Standing": "System is performing efficiently.",
                "Moderate Load": "System is okay, but avoid overloading it.",
                "High Load": "Close unnecessary apps or check for issues.",
            }[cpu_status],
        },
        "memory": {
            "percent": round(memory.percent, 1),
            "used_gb": round(memory.used / (1024**3), 2),
            "available_gb": round(memory.available / (1024**3), 2),
            "total_gb": round(memory.total / (1024**3), 2),
            "swap_percent": round(swap.percent, 1),
            "swap_used_gb": round(swap.used / (1024**3), 2),
            "swap_total_gb": round(swap.total / (1024**3), 2),
            "status": memory_status,
            "comment": {
                "Good Standing": "Plenty of memory available.",
                "Maintenance Suggested": "Monitor open programs and close unused ones.",
                "Memory Overload": "Close memory-heavy apps and monitor open programs.",
            }[memory_status],
        },
        "disk": {
            "percent": round(disk.percent, 1),
            "used_gb": round(disk.used / (1024**3), 2),
            "total_gb": round(disk.total / (1024**3), 2),
            "status": disk_status,
            "comment": {
                "Good Standing": "No issues detected.",
                "Maintenance Suggested": "Monitor and clean temporary or unused files.",
                "Critical Condition": "Free disk space now to avoid issues.",
            }[disk_status],
        },
        "network": {
            "sent_mb": round(network_sent_mb, 2),
            "received_mb": round(network_received_mb, 2),
            "packets_sent": net.packets_sent,
            "packets_received": net.packets_recv,
            "upload_status": classify_upload(network_sent_mb)[0],
            "upload_comment": classify_upload(network_sent_mb)[1],
            "download_status": classify_download(network_received_mb)[0],
            "download_comment": classify_download(network_received_mb)[1],
        },
        "packets": {
            "sent": net.packets_sent,
            "received": net.packets_recv,
            "sent_status": classify_packets(net.packets_sent, "sent")[0],
            "sent_comment": classify_packets(net.packets_sent, "sent")[1],
            "received_status": classify_packets(net.packets_recv, "received")[0],
            "received_comment": classify_packets(net.packets_recv, "received")[1],
        },
        "errors": {
            "receive_errors": net.errin,
            "send_errors": net.errout,
        },
    }


def classify_upload(value_mb: float) -> tuple[str, str]:
    if value_mb < 100:
        return "Idle/Light", "Minimal outgoing network activity."
    if value_mb < 500:
        return "Light Uploads", "Some background sync or small uploads."
    if value_mb < 1000:
        return "Moderate", "Medium upload usage."
    if value_mb < 5000:
        return "High Usage", "Large uploads or backups may be running."
    return "Heavy/Unusual", "High upload detected. Investigate if unexpected."


def classify_download(value_mb: float) -> tuple[str, str]:
    if value_mb < 100:
        return "Idle/Light", "Minimal incoming network activity."
    if value_mb < 500:
        return "Light Downloads", "Background updates or light use."
    if value_mb < 2000:
        return "Moderate", "Normal downloads or media use."
    if value_mb < 5000:
        return "High Usage", "Large files or streaming may be active."
    return "Heavy/Unusual", "Very high download volume. Check activity."


def classify_packets(count: int, direction: str) -> tuple[str, str]:
    if count < 10000:
        return "Very Light", "Normal system use."
    if count < 50000:
        return "Moderate", f"Some apps are moving {direction} data."
    if count < 200000:
        return "High", f"Sustained {direction} network activity."
    return "Alert", f"Unusually high {direction} packet count."


def build_alerts(identity: dict[str, Any], hardware: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    """Turn raw numbers into short dashboard warnings."""
    alerts = []

    if metrics["cpu"]["percent"] >= 80:
        alerts.append("CPU usage is high.")
    if metrics["memory"]["percent"] >= 80:
        alerts.append("Memory usage is high.")
    if metrics["disk"]["percent"] >= 90:
        alerts.append("Disk usage is in critical condition.")
    elif metrics["disk"]["percent"] >= 70:
        alerts.append("Disk usage is elevated. Maintenance suggested.")
    if metrics["errors"]["receive_errors"] > 0:
        alerts.append("Network receive errors detected.")
    if metrics["errors"]["send_errors"] > 0:
        alerts.append("Network send errors detected.")

    max_temp = hardware["temperature"]["max_temp_c"]
    if max_temp is not None and max_temp >= 90:
        alerts.append("System temperature is critical.")
    elif max_temp is not None and max_temp >= 75:
        alerts.append("System temperature is elevated.")

    for service in get_failed_services():
        alerts.append(f"Failed service detected: {service}")

    if not identity["ip_addresses"]:
        alerts.append("No active IPv4 address detected.")

    return alerts


def get_overall_status(metrics: dict[str, Any], alerts: list[str]) -> str:
    if metrics["disk"]["percent"] >= 90 or metrics["memory"]["percent"] >= 90:
        return "Critical"
    if len(alerts) >= 3:
        return "Warning"
    if alerts:
        return "Attention Needed"
    return "Healthy"


def normalize_machine_id(snapshot: dict[str, Any]) -> str:
    identity = snapshot.get("identity", {})
    return str(identity.get("machine_id") or identity.get("hostname") or "unknown-machine")


def machine_age_seconds(snapshot: dict[str, Any]) -> int | None:
    last_seen = parse_iso(snapshot.get("last_seen"))
    if last_seen is None:
        return None
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=dt.timezone.utc)
    return max(0, int((dt.datetime.now(dt.timezone.utc) - last_seen).total_seconds()))


def enrich_machine(snapshot: dict[str, Any], source: str) -> dict[str, Any]:
    enriched = dict(snapshot)
    enriched["source"] = source
    enriched["machine_key"] = normalize_machine_id(enriched)
    enriched["age_seconds"] = machine_age_seconds(enriched)
    enriched["connection_status"] = (
        "stale"
        if enriched["age_seconds"] is not None and enriched["age_seconds"] > STALE_AFTER_SECONDS
        else "online"
    )
    return enriched


def collect_full_snapshot() -> dict[str, Any]:
    """Build one complete local telemetry snapshot for the dashboard."""
    identity = get_system_identity()
    hardware = get_hardware_info()
    metrics = collect_system_metrics()
    alerts = build_alerts(identity, hardware, metrics)

    return {
        **metrics,
        "identity": identity,
        "hardware": hardware,
        "storage": collect_storage_info(),
        "network_interfaces": collect_network_interfaces(),
        "processes": collect_process_info(),
        "power": collect_power_info(),
        "user_sessions": collect_user_sessions(),
        "alerts": alerts,
        "last_seen": now_iso(),
        "overall_status": get_overall_status(metrics, alerts),
        "display_name": identity["hostname"],
        "tags": ["local"],
    }


def build_registered_machine(registration: MachineRegistration) -> dict[str, Any]:
    """Create a pending machine row before the agent starts reporting."""
    machine_key = f"manual-{uuid.uuid4()}"
    return {
        "machine_key": machine_key,
        "display_name": registration.display_name,
        "source": "registered",
        "connection_status": "pending",
        "overall_status": "Waiting",
        "last_seen": None,
        "age_seconds": None,
        "tags": registration.tags,
        "identity": {
            "hostname": registration.host or registration.display_name,
            "ip_addresses": [{"interface": "manual", "ip_address": registration.host}] if registration.host else [],
            "mac_addresses": [],
        },
        "hardware": {},
        "alerts": ["Waiting for this machine to send telemetry."],
        "connect_command": (
            "python agent.py --server http://DASHBOARD-IP:8000 "
            f"--name \"{registration.display_name}\""
        ),
    }


def local_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def dashboard_agent_url(request: Request) -> str:
    """Pick the callback URL that remote agents should send telemetry to."""
    public_url = os.getenv("HEALTHIT_PUBLIC_URL")
    if public_url:
        return public_url.rstrip("/")
    port = request.url.port or 8000
    return f"http://{local_lan_ip()}:{port}"


def deploy_controller_url(deploy: SshDeployRequest, request: Request) -> str:
    return (deploy.controller_url or dashboard_agent_url(request)).rstrip("/")


def deploy_step(
    label: str,
    status: str,
    command: str,
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = None,
) -> dict[str, Any]:
    """Status object used by the frontend deploy progress list."""
    return {
        "label": label,
        "status": status,
        "command": command,
        "stdout": (stdout or "")[-1600:],
        "stderr": (stderr or "")[-1600:],
        "exit_code": exit_code,
    }


def deploy_failure(label: str, command: str, stdout: str, stderr: str, exit_code: int | None, hint: str) -> HTTPException:
    step = deploy_step(label, "failed", command, stdout, stderr, exit_code)
    return HTTPException(
        status_code=400,
        detail={
            "message": f"{label} failed.",
            "step": step,
            "hint": hint,
        },
    )


def run_deploy_step(label: str, command: list[str], timeout: int = 45) -> dict[str, Any]:
    """Run one SSH-key deploy command and capture useful output if it fails."""
    logger.info("SSH deploy step: %s", label)
    command_text = " ".join(shlex.quote(part) for part in command)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="SSH tools were not found. Install or enable OpenSSH Client on this dashboard computer.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise deploy_failure(label, command_text, exc.stdout or "", exc.stderr or "Timed out.", None, f"{label} timed out.") from exc

    step = deploy_step(label, "completed", command_text, result.stdout, result.stderr, result.returncode)
    if result.returncode != 0:
        raise deploy_failure(
            label,
            command_text,
            result.stdout,
            result.stderr,
            result.returncode,
            "Confirm SSH is enabled, the host is reachable, and your SSH key can log in without a password prompt.",
        )
    return step


def ssh_target(request: SshDeployRequest) -> str:
    return f"{request.ssh_user}@{request.host}"


def ssh_base_command(request: SshDeployRequest) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT_SECONDS}",
        "-p",
        str(request.ssh_port),
        ssh_target(request),
    ]


def scp_base_command(request: SshDeployRequest) -> list[str]:
    return [
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT_SECONDS}",
        "-P",
        str(request.ssh_port),
    ]


def ensure_paramiko_available() -> None:
    if paramiko is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "Password SSH deploy requires paramiko. Run pip install -r requirements.txt "
                "on the dashboard machine."
            ),
        )


def run_paramiko_command(client: Any, label: str, command: str, timeout: int = 45) -> dict[str, Any]:
    logger.info("SSH password deploy step: %s", label)
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        stdout_text = stdout.read().decode(errors="replace").strip()
        stderr_text = stderr.read().decode(errors="replace").strip()
    except Exception as exc:
        raise deploy_failure(
            label,
            command,
            "",
            str(exc),
            1,
            "Confirm SSH is enabled and the username/password are correct.",
        ) from exc

    step = deploy_step(label, "completed", command, stdout_text, stderr_text, exit_code)
    if exit_code != 0:
        raise deploy_failure(
            label,
            command,
            stdout_text,
            stderr_text,
            exit_code,
            "Confirm the remote account can create folders, run python3, and install packages.",
        )
    return step


def connect_paramiko(deploy: SshDeployRequest) -> Any:
    """Open password-based SSH without saving or logging the password."""
    ensure_paramiko_available()
    if not deploy.ssh_password:
        raise HTTPException(status_code=400, detail="Password SSH deploy requires a password.")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=deploy.host,
            port=deploy.ssh_port,
            username=deploy.ssh_user,
            password=deploy.ssh_password,
            timeout=SSH_TIMEOUT_SECONDS,
            banner_timeout=SSH_TIMEOUT_SECONDS,
            auth_timeout=SSH_TIMEOUT_SECONDS,
            look_for_keys=False,
            allow_agent=False,
        )
    except Exception as exc:
        client.close()
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Checking SSH access failed.",
                "step": deploy_step("Connecting over SSH", "failed", "paramiko.connect", "", str(exc), 1),
                "hint": "Confirm the host/IP, SSH port, username, and password.",
            },
        ) from exc
    return client


def deploy_matches_snapshot(deploy: SshDeployRequest, snapshot: dict[str, Any]) -> bool:
    display_name = normalize_match_value(snapshot.get("display_name"))
    identity = snapshot.get("identity", {})
    hostname = normalize_match_value(identity.get("hostname"))
    host = normalize_match_value(deploy.host)
    name = normalize_match_value(deploy.display_name)
    ips = {
        normalize_match_value(item.get("ip_address"))
        for item in identity.get("ip_addresses", [])
        if item.get("ip_address")
    }
    return bool((name and name in {display_name, hostname}) or (host and host in {hostname, *ips}))


def wait_for_agent_heartbeat(deploy: SshDeployRequest, timeout: int = 25) -> dict[str, Any]:
    """After starting the remote agent, wait until telemetry reaches this server."""
    command = "wait for POST /telemetry"
    deadline = time.time() + timeout
    while time.time() < deadline:
        for machine in remote_machines.values():
            if deploy_matches_snapshot(deploy, machine):
                label = machine.get("display_name") or machine.get("identity", {}).get("hostname")
                return deploy_step("Verifying heartbeat", "completed", command, f"Telemetry received from {label}.", "", 0)
        time.sleep(2)
    raise deploy_failure(
        "Verifying heartbeat",
        command,
        "",
        (
            "The remote process started, but no telemetry reached the dashboard before timeout. "
            "Check Controller URL, firewall, and network reachability from the target."
        ),
        1,
        "Use a Controller URL reachable from the target, such as http://<dashboard-LAN-IP>:8000.",
    )


def append_failed_step(exc: HTTPException, steps: list[dict[str, Any]]) -> HTTPException:
    if isinstance(exc.detail, dict):
        failed_step = exc.detail.get("step")
        detail_steps = [*steps]
        if failed_step and failed_step not in detail_steps:
            detail_steps.append(failed_step)
        exc.detail["steps"] = detail_steps
    return exc


def remote_start_script(remote_dir: str, server_url: str, display_name: str) -> str:
    """Build the remote command that keeps the agent running in the background."""
    return (
        f"cd {remote_dir} && "
        "if [ -f agent.pid ]; then oldpid=$(cat agent.pid 2>/dev/null || true); "
        "if [ -n \"$oldpid\" ]; then kill \"$oldpid\" >/dev/null 2>&1 || true; fi; fi; "
        "nohup .venv/bin/python agent.py "
        f"--server {shlex.quote(server_url)} "
        f"--name {shlex.quote(display_name)} "
        "--interval 5 > healthit-agent.log 2>&1 & "
        "echo $! > agent.pid; "
        "sleep 2; "
        "pid=$(cat agent.pid); "
        "if ps -p \"$pid\" >/dev/null 2>&1; then echo \"started pid=$pid\"; "
        "else echo \"agent failed to stay running\"; tail -80 healthit-agent.log; exit 1; fi"
    )


def deploy_agent_with_password(deploy: SshDeployRequest, request: Request) -> dict[str, Any]:
    """Deploy the agent through Paramiko when the dashboard user enters a password."""
    server_url = deploy_controller_url(deploy, request)
    remote_dir = "healthit-agent"
    agent_path = PROJECT_ROOT / "agent.py"
    target = ssh_target(deploy)
    steps = []
    client = connect_paramiko(deploy)

    try:
        steps.append(deploy_step("Connecting over SSH", "completed", "paramiko.connect", "password login ok", "", 0))
        steps.append(run_paramiko_command(client, "Creating remote agent folder", f"mkdir -p ~/{remote_dir}"))
        steps.append(run_paramiko_command(client, "Checking python3", "python3 --version"))
        steps.append(run_paramiko_command(client, "Creating virtual environment", f"python3 -m venv ~/{remote_dir}/.venv", timeout=90))
        steps.append(
            run_paramiko_command(
                client,
                "Installing dependencies",
                f"~/{remote_dir}/.venv/bin/python -m pip install psutil requests",
                timeout=180,
            )
        )

        try:
            sftp = client.open_sftp()
            sftp.put(str(agent_path), f"{remote_dir}/agent.py")
            sftp.close()
            steps.append(deploy_step("Uploading agent", "completed", f"sftp put agent.py ~/{remote_dir}/agent.py", "uploaded", "", 0))
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Uploading agent failed.",
                    "step": deploy_step("Uploading agent", "failed", f"sftp put agent.py ~/{remote_dir}/agent.py", "", str(exc), 1),
                    "hint": "Confirm the SSH account can write to its home directory.",
                },
            ) from exc

        steps.append(run_paramiko_command(client, "Starting agent", remote_start_script(f"~/{remote_dir}", server_url, deploy.display_name)))
        steps.append(wait_for_agent_heartbeat(deploy))
    except HTTPException as exc:
        raise append_failed_step(exc, steps)
    finally:
        client.close()

    return {
        "message": "Agent deployment started.",
        "server_url": server_url,
        "target": target,
        "login_type": "password",
        "steps": steps,
        "command": f"python3 ~/healthit-agent/agent.py --server {server_url} --name {deploy.display_name}",
    }


def deploy_agent_with_key(deploy: SshDeployRequest, request: Request) -> dict[str, Any]:
    """Deploy the agent with normal ssh/scp when SSH keys are already set up."""
    server_url = deploy_controller_url(deploy, request)
    remote_dir = "~/healthit-agent"
    agent_path = PROJECT_ROOT / "agent.py"
    steps = []

    try:
        steps.append(
            run_deploy_step(
                "Connecting over SSH",
                [*ssh_base_command(deploy), "echo healthit-ssh-ok"],
                timeout=SSH_TIMEOUT_SECONDS + 5,
            )
        )
        steps.append(
            run_deploy_step(
                "Creating remote agent folder",
                [*ssh_base_command(deploy), f"mkdir -p {remote_dir}"],
            )
        )
        steps.append(run_deploy_step("Checking python3", [*ssh_base_command(deploy), "python3 --version"]))
        steps.append(
            run_deploy_step(
                "Creating virtual environment",
                [*ssh_base_command(deploy), f"python3 -m venv {remote_dir}/.venv"],
                timeout=90,
            )
        )
        steps.append(
            run_deploy_step(
                "Installing dependencies",
                [*ssh_base_command(deploy), f"{remote_dir}/.venv/bin/python -m pip install psutil requests"],
                timeout=180,
            )
        )
        steps.append(
            run_deploy_step(
                "Uploading agent",
                [*scp_base_command(deploy), str(agent_path), f"{ssh_target(deploy)}:{remote_dir}/agent.py"],
            )
        )
        steps.append(
            run_deploy_step(
                "Starting agent",
                [*ssh_base_command(deploy), remote_start_script(remote_dir, server_url, deploy.display_name)],
            )
        )
        steps.append(wait_for_agent_heartbeat(deploy))
    except HTTPException as exc:
        raise append_failed_step(exc, steps)

    return {
        "message": "Agent deployment started.",
        "server_url": server_url,
        "target": ssh_target(deploy),
        "login_type": "key",
        "steps": steps,
        "command": f"python3 ~/healthit-agent/agent.py --server {server_url} --name {deploy.display_name}",
    }


def deploy_agent_over_ssh(deploy: SshDeployRequest, request: Request) -> dict[str, Any]:
    if deploy.login_type == "password":
        return deploy_agent_with_password(deploy, request)
    return deploy_agent_with_key(deploy, request)


def normalize_match_value(value: str | None) -> str:
    return (value or "").strip().casefold()


def registration_matches(machine: dict[str, Any], registration: MachineRegistration) -> bool:
    wanted_name = normalize_match_value(registration.display_name)
    wanted_host = normalize_match_value(registration.host)
    existing_name = normalize_match_value(machine.get("display_name"))
    identity = machine.get("identity", {})
    existing_host = normalize_match_value(identity.get("hostname"))
    existing_ips = {
        normalize_match_value(item.get("ip_address"))
        for item in identity.get("ip_addresses", [])
        if item.get("ip_address")
    }

    if wanted_name and wanted_name in {existing_name, existing_host}:
        return True
    if wanted_host and wanted_host in {existing_host, *existing_ips}:
        return True
    return False


def find_pending_registration(snapshot: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Return the pending inventory row that matches a newly reporting agent."""
    display_name = normalize_match_value(snapshot.get("display_name"))
    identity = snapshot.get("identity", {})
    hostname = normalize_match_value(identity.get("hostname"))
    ips = {
        normalize_match_value(item.get("ip_address"))
        for item in identity.get("ip_addresses", [])
        if item.get("ip_address")
    }

    for key, machine in registered_machines.items():
        pending_name = normalize_match_value(machine.get("display_name"))
        pending_identity = machine.get("identity", {})
        pending_host = normalize_match_value(pending_identity.get("hostname"))
        pending_ips = {
            normalize_match_value(item.get("ip_address"))
            for item in pending_identity.get("ip_addresses", [])
            if item.get("ip_address")
        }
        if pending_name and pending_name in {display_name, hostname}:
            return key, machine
        if pending_host and pending_host in {hostname, *ips}:
            return key, machine
        if pending_ips.intersection({hostname, *ips}):
            return key, machine
    return None


def apply_machine_override(machine: dict[str, Any]) -> dict[str, Any]:
    """Apply friendly names/tags without changing the raw telemetry payload."""
    key = machine.get("machine_key") or normalize_machine_id(machine)
    override = machine_overrides.get(key, {})
    if not override:
        return machine

    updated = dict(machine)
    identity = dict(updated.get("identity", {}))
    if override.get("display_name"):
        updated["display_name"] = override["display_name"]
    if override.get("host"):
        identity["hostname"] = override["host"]
    if override.get("tags") is not None:
        updated["tags"] = override["tags"]
    updated["identity"] = identity
    return updated


def require_telemetry_token(header_token: str | None) -> None:
    if TELEMETRY_TOKEN and header_token != TELEMETRY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid telemetry token.")


def normalize_task_command(command: str) -> str:
    normalized = command.strip().lower()
    if normalized not in ALLOWED_TASKS:
        allowed = ", ".join(sorted(ALLOWED_TASKS))
        raise HTTPException(
            status_code=400,
            detail=f"Command not allowed. Try one of: {allowed}.",
        )
    return normalized


def format_task_output(command: str, snapshot: dict[str, Any]) -> str:
    identity = snapshot.get("identity", {})
    hardware = snapshot.get("hardware", {})
    alerts = snapshot.get("alerts", [])

    if command == "help":
        return "Allowed commands: " + ", ".join(sorted(ALLOWED_TASKS))
    if command in {"status", "refresh"}:
        return (
            f"{snapshot.get('display_name') or identity.get('hostname', 'Machine')} is "
            f"{snapshot.get('overall_status', 'Unknown')} | "
            f"CPU {snapshot.get('cpu', {}).get('percent', '--')}% | "
            f"Memory {snapshot.get('memory', {}).get('percent', '--')}% | "
            f"Disk {snapshot.get('disk', {}).get('percent', '--')}%"
        )
    if command == "uptime":
        return f"Uptime: {identity.get('uptime_readable', 'Unavailable')}"
    if command == "whoami":
        return f"User: {identity.get('current_user', 'Unknown')} on {identity.get('hostname', 'Unknown host')}"
    if command == "ip":
        addresses = identity.get("ip_addresses", [])
        if not addresses:
            return "No active IPv4 addresses reported."
        return "\n".join(f"{item.get('interface', 'interface')}: {item.get('ip_address')}" for item in addresses)
    if command == "disk":
        disk = snapshot.get("disk", {})
        return (
            f"Disk: {disk.get('percent', '--')}% used | "
            f"{disk.get('used_gb', '--')} GB / {disk.get('total_gb', '--')} GB | "
            f"{disk.get('status', 'Unknown')}"
        )
    if command == "memory":
        memory = snapshot.get("memory", {})
        return (
            f"Memory: {memory.get('percent', '--')}% used | "
            f"{memory.get('used_gb', '--')} GB / {memory.get('total_gb', '--')} GB | "
            f"{memory.get('status', 'Unknown')}"
        )
    if command == "network":
        network = snapshot.get("network", {})
        errors = snapshot.get("errors", {})
        return (
            f"Sent {network.get('sent_mb', '--')} MB | "
            f"Received {network.get('received_mb', '--')} MB | "
            f"Errors in/out {errors.get('receive_errors', '--')}/{errors.get('send_errors', '--')}"
        )
    if command == "alerts":
        return "\n".join(alerts) if alerts else "No active alerts."

    return f"{command} completed."


def run_local_task(command: str) -> dict[str, Any]:
    snapshot = collect_full_snapshot()
    task_id = str(uuid.uuid4())
    return {
        "task_id": task_id,
        "machine_key": normalize_machine_id(snapshot),
        "command": command,
        "status": "completed",
        "output": format_task_output(command, snapshot),
        "created_at": now_iso(),
        "completed_at": now_iso(),
    }


def queue_remote_task(machine_key: str, command: str) -> dict[str, Any]:
    task = {
        "task_id": str(uuid.uuid4()),
        "machine_key": machine_key,
        "command": command,
        "status": "queued",
        "output": "",
        "created_at": now_iso(),
        "completed_at": None,
    }
    task_queues.setdefault(machine_key, []).append(task)
    task_results.setdefault(machine_key, []).append(task)
    persist_state()
    return task


def ssh_target_for_machine(snapshot: dict[str, Any]) -> str:
    identity = snapshot.get("identity", {})
    hostname = identity.get("hostname")
    ip_addresses = identity.get("ip_addresses", [])
    host = ip_addresses[0].get("ip_address") if ip_addresses else hostname

    if not host:
        raise HTTPException(status_code=400, detail="Machine does not report an SSH host or IP.")

    return f"{SSH_USER}@{host}" if SSH_USER else host


def run_ssh_task(machine_key: str, command: str) -> dict[str, Any]:
    if not ENABLE_SSH:
        raise HTTPException(
            status_code=403,
            detail="SSH terminal is disabled. Set HEALTHIT_ENABLE_SSH=true on the dashboard server to enable it.",
        )

    local_snapshot = enrich_machine(collect_full_snapshot(), "local")
    if machine_key in {local_snapshot["machine_key"], local_snapshot["identity"].get("hostname")}:
        snapshot = local_snapshot
    elif machine_key in remote_machines:
        snapshot = remote_machines[machine_key]
    else:
        raise HTTPException(status_code=404, detail="Machine not found.")

    task_id = str(uuid.uuid4())
    target = ssh_target_for_machine(snapshot)
    ssh_command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT_SECONDS}",
        target,
        command,
    ]
    started_at = now_iso()

    try:
        result = subprocess.run(
            ssh_command,
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT_SECONDS + 5,
            check=False,
        )
        output = result.stdout.strip()
        error_output = result.stderr.strip()
        if error_output:
            output = f"{output}\n{error_output}".strip()
        status_text = "completed" if result.returncode == 0 else f"exit {result.returncode}"
    except FileNotFoundError:
        output = "ssh client was not found on the dashboard server."
        status_text = "error"
    except subprocess.TimeoutExpired:
        output = "ssh command timed out."
        status_text = "timeout"

    task = {
        "task_id": task_id,
        "machine_key": machine_key,
        "command": command,
        "status": status_text,
        "output": output or "(no output)",
        "created_at": started_at,
        "completed_at": now_iso(),
        "mode": "ssh",
    }
    task_results.setdefault(machine_key, []).append(task)
    persist_state()
    return task


def shell_command(command: str, cwd: str) -> tuple[str, int]:
    if platform.system() == "Windows":
        runner = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    else:
        runner = ["/bin/sh", "-lc", command]

    result = subprocess.run(
        runner,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=TERMINAL_TIMEOUT_SECONDS,
        check=False,
    )
    output = result.stdout
    if result.stderr:
        output = f"{output}{result.stderr}"
    return output.strip() or "(no output)", result.returncode


def create_terminal_session(name: str | None = None, machine_key: str | None = None) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    cwd = str(PROJECT_ROOT)
    session = {
        "session_id": session_id,
        "name": name or f"terminal-{len(terminal_sessions) + 1}",
        "machine_key": machine_key,
        "cwd": cwd,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "history": [
            {
                "command": "",
                "output": f"HealthIT terminal started in {cwd}\nType commands normally. Use ssh user@host to connect to another machine.",
                "cwd": cwd,
                "exit_code": 0,
                "timestamp": now_iso(),
            }
        ],
    }
    terminal_sessions[session_id] = session
    persist_state()
    return session


def terminal_summary(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": session["session_id"],
        "name": session["name"],
        "machine_key": session.get("machine_key"),
        "cwd": session["cwd"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "history": session["history"],
    }


def run_terminal_command(session_id: str, command: str) -> dict[str, Any]:
    """Run one command in the local browser terminal.

    This is intentionally a trusted-homelab feature for now. Add auth before
    exposing the dashboard outside your own network.
    """
    if session_id not in terminal_sessions:
        raise HTTPException(status_code=404, detail="Terminal session not found.")

    session = terminal_sessions[session_id]
    clean_command = command.strip()
    timestamp = now_iso()

    if not clean_command:
        session["history"].append(
            {
                "command": "",
                "output": "",
                "cwd": session["cwd"],
                "exit_code": 0,
                "timestamp": timestamp,
            }
        )
        session["history"] = session["history"][-200:]
        session["updated_at"] = now_iso()
        persist_state()
        return terminal_summary(session)

    if clean_command.lower() in {"cls", "clear"}:
        session["history"] = []
        session["updated_at"] = timestamp
        persist_state()
        return terminal_summary(session)

    if clean_command.lower() in {"pwd", "cd"}:
        output = session["cwd"]
        exit_code = 0
    elif clean_command.lower().startswith("cd "):
        next_path = clean_command[3:].strip().strip('"')
        target = Path(session["cwd"]).joinpath(next_path).resolve()
        if target.exists() and target.is_dir():
            session["cwd"] = str(target)
            output = session["cwd"]
            exit_code = 0
        else:
            output = f"The system cannot find the path specified: {next_path}"
            exit_code = 1
    else:
        try:
            output, exit_code = shell_command(clean_command, session["cwd"])
        except subprocess.TimeoutExpired:
            output = f"Command timed out after {TERMINAL_TIMEOUT_SECONDS}s."
            exit_code = 124
        except OSError as exc:
            output = str(exc)
            exit_code = 1

    entry = {
        "command": clean_command,
        "output": output,
        "cwd": session["cwd"],
        "exit_code": exit_code,
        "timestamp": timestamp,
    }
    session["history"].append(entry)
    session["history"] = session["history"][-200:]
    session["updated_at"] = now_iso()
    persist_state()
    return terminal_summary(session)


@app.get("/")
def home() -> dict[str, str]:
    return {
        "message": "HealthIT API is running.",
        "dashboard": "/app",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "timestamp": now_iso()}


@app.get("/metrics")
def read_metrics() -> dict[str, Any]:
    return enrich_machine(collect_full_snapshot(), "local")


@app.get("/deploy-info")
def deploy_info(request: Request) -> dict[str, str]:
    return {"controller_url": dashboard_agent_url(request)}


@app.post("/telemetry")
def receive_telemetry(
    payload: TelemetryPayload = Body(...),
    x_healthit_token: str | None = Header(default=None),
) -> dict[str, str]:
    """Main endpoint remote agents use to send live machine stats."""
    require_telemetry_token(x_healthit_token)

    snapshot = payload.model_dump()
    snapshot["last_seen"] = now_iso()
    machine_key = normalize_machine_id(snapshot)
    pending_match = find_pending_registration(snapshot)
    if pending_match:
        pending_key, pending_machine = pending_match
        snapshot["display_name"] = snapshot.get("display_name") or pending_machine.get("display_name")
        if pending_machine.get("tags"):
            snapshot["tags"] = pending_machine["tags"]
        machine_overrides[machine_key] = machine_overrides.pop(pending_key, {})
        registered_machines.pop(pending_key, None)

    remote_machines[machine_key] = enrich_machine(snapshot, "remote")
    persist_state()

    logger.info("Telemetry received from %s", machine_key)
    return {"message": "Telemetry received successfully.", "machine_key": machine_key}


@app.get("/machines")
def get_all_machines() -> dict[str, Any]:
    """Return local, remote, and pending machines in one dashboard list."""
    local_snapshot = apply_machine_override(enrich_machine(collect_full_snapshot(), "local"))
    remote_snapshots = [
        apply_machine_override(enrich_machine(machine, "remote"))
        for machine in remote_machines.values()
    ]
    live_keys = {local_snapshot["machine_key"], *[machine["machine_key"] for machine in remote_snapshots]}
    pending_snapshots = [
        apply_machine_override(machine)
        for key, machine in registered_machines.items()
        if key not in live_keys
    ]
    machines = [local_snapshot, *remote_snapshots, *pending_snapshots]

    return {
        "count": len(machines),
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "machines": machines,
    }


@app.post("/machines/register")
def register_machine(registration: MachineRegistration) -> dict[str, Any]:
    local_snapshot = apply_machine_override(enrich_machine(collect_full_snapshot(), "local"))
    existing_machines = [
        local_snapshot,
        *[apply_machine_override(enrich_machine(machine, "remote")) for machine in remote_machines.values()],
        *[apply_machine_override(machine) for machine in registered_machines.values()],
    ]
    for machine in existing_machines:
        if registration_matches(machine, registration):
            return {
                **machine,
                "already_exists": True,
                "message": "This machine is already in the inventory.",
            }

    machine = build_registered_machine(registration)
    registered_machines[machine["machine_key"]] = machine
    persist_state()
    return {**machine, "already_exists": False, "message": "Machine registered."}


@app.post("/machines/deploy-ssh")
def deploy_machine_agent(deploy: SshDeployRequest, request: Request) -> dict[str, Any]:
    """Register a machine, deploy its agent over SSH, then wait for heartbeat."""
    registration = MachineRegistration(
        display_name=deploy.display_name,
        host=deploy.host,
        tags=deploy.tags,
    )
    machine = register_machine(registration)
    if machine.get("already_exists") and machine.get("connection_status") == "online":
        return {
            "message": "Machine is already online.",
            "already_exists": True,
            "machine": machine,
            "steps": [],
        }

    try:
        deploy_result = deploy_agent_over_ssh(deploy, request)
    except HTTPException as exc:
        machine_key = machine.get("machine_key")
        if machine_key in registered_machines:
            registered_machines[machine_key]["connection_status"] = "failed"
            registered_machines[machine_key]["overall_status"] = "Deploy Failed"
            registered_machines[machine_key]["alerts"] = [
                exc.detail.get("message", "Deploy failed.") if isinstance(exc.detail, dict) else "Deploy failed."
            ]
        if isinstance(exc.detail, dict):
            exc.detail["machine"] = registered_machines.get(machine_key, machine)
        persist_state()
        raise exc
    return {
        **deploy_result,
        "already_exists": machine.get("already_exists", False),
        "machine": machine,
    }


@app.get("/machines/{machine_key}")
def get_machine(machine_key: str) -> dict[str, Any]:
    local_snapshot = apply_machine_override(enrich_machine(collect_full_snapshot(), "local"))
    if machine_key in {local_snapshot["machine_key"], local_snapshot["identity"].get("hostname")}:
        return local_snapshot

    if machine_key in remote_machines:
        return apply_machine_override(enrich_machine(remote_machines[machine_key], "remote"))

    if machine_key in registered_machines:
        return apply_machine_override(registered_machines[machine_key])

    raise HTTPException(status_code=404, detail="Machine not found.")


@app.put("/machines/{machine_key}")
def update_machine(machine_key: str, update: MachineUpdate) -> dict[str, Any]:
    if machine_key in registered_machines:
        machine = dict(registered_machines[machine_key])
        identity = dict(machine.get("identity", {}))
        if update.display_name is not None:
            machine["display_name"] = update.display_name
        if update.host is not None:
            identity["hostname"] = update.host
            identity["ip_addresses"] = [{"interface": "manual", "ip_address": update.host}] if update.host else []
        if update.tags is not None:
            machine["tags"] = update.tags
        machine["identity"] = identity
        registered_machines[machine_key] = machine
        persist_state()
        return apply_machine_override(machine)

    known_keys = {normalize_machine_id(collect_full_snapshot()), *remote_machines.keys()}
    if machine_key not in known_keys:
        raise HTTPException(status_code=404, detail="Machine not found.")

    override = machine_overrides.setdefault(machine_key, {})
    if update.display_name is not None:
        override["display_name"] = update.display_name
    if update.host is not None:
        override["host"] = update.host
    if update.tags is not None:
        override["tags"] = update.tags
    persist_state()
    return get_machine(machine_key)


@app.delete("/machines/{machine_key}")
def delete_machine(machine_key: str) -> dict[str, str]:
    if machine_key in registered_machines:
        del registered_machines[machine_key]
        machine_overrides.pop(machine_key, None)
        persist_state()
        return {"message": "Machine removed.", "machine_key": machine_key}
    if machine_key in remote_machines:
        del remote_machines[machine_key]
        machine_overrides.pop(machine_key, None)
        persist_state()
        return {"message": "Remote machine removed.", "machine_key": machine_key}

    local_key = normalize_machine_id(collect_full_snapshot())
    if machine_key == local_key:
        raise HTTPException(status_code=400, detail="The local dashboard machine cannot be removed.")
    raise HTTPException(status_code=404, detail="Machine not found.")


@app.post("/machines/{machine_key}/tasks")
def create_machine_task(machine_key: str, request: TaskRequest) -> dict[str, Any]:
    if request.mode == "ssh":
        return run_ssh_task(machine_key, request.command)

    command = normalize_task_command(request.command)
    local_snapshot = enrich_machine(collect_full_snapshot(), "local")

    if machine_key in {local_snapshot["machine_key"], local_snapshot["identity"].get("hostname")}:
        task = run_local_task(command)
        task_results.setdefault(task["machine_key"], []).append(task)
        persist_state()
        return task

    if machine_key not in remote_machines:
        raise HTTPException(status_code=404, detail="Machine not found.")

    return queue_remote_task(machine_key, command)


@app.get("/machines/{machine_key}/tasks")
def get_machine_tasks(machine_key: str) -> dict[str, Any]:
    return {"machine_key": machine_key, "tasks": task_results.get(machine_key, [])[-20:]}


@app.get("/terminal/sessions")
def list_terminal_sessions() -> dict[str, Any]:
    if not terminal_sessions:
        create_terminal_session()
    return {"sessions": [terminal_summary(session) for session in terminal_sessions.values()]}


@app.post("/terminal/sessions")
def create_terminal_session_endpoint(request: TerminalSessionCreate) -> dict[str, Any]:
    return terminal_summary(create_terminal_session(request.name, request.machine_key))


@app.get("/terminal/sessions/{session_id}")
def get_terminal_session(session_id: str) -> dict[str, Any]:
    if session_id not in terminal_sessions:
        raise HTTPException(status_code=404, detail="Terminal session not found.")
    return terminal_summary(terminal_sessions[session_id])


@app.post("/terminal/sessions/{session_id}/rename")
def rename_terminal_session(session_id: str, request: TerminalSessionRename) -> dict[str, Any]:
    if session_id not in terminal_sessions:
        raise HTTPException(status_code=404, detail="Terminal session not found.")
    terminal_sessions[session_id]["name"] = request.name.strip()
    terminal_sessions[session_id]["updated_at"] = now_iso()
    persist_state()
    return terminal_summary(terminal_sessions[session_id])


@app.delete("/terminal/sessions/{session_id}")
def delete_terminal_session(session_id: str) -> dict[str, str]:
    if session_id not in terminal_sessions:
        raise HTTPException(status_code=404, detail="Terminal session not found.")
    del terminal_sessions[session_id]
    persist_state()
    return {"message": "Terminal session deleted.", "session_id": session_id}


@app.post("/terminal/sessions/{session_id}/commands")
def execute_terminal_command(session_id: str, request: TerminalCommandRequest) -> dict[str, Any]:
    return run_terminal_command(session_id, request.command)


@app.get("/agent/tasks")
def get_agent_tasks(
    machine_key: str,
    x_healthit_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_telemetry_token(x_healthit_token)
    queued = task_queues.get(machine_key, [])
    task_queues[machine_key] = []
    return {"machine_key": machine_key, "tasks": queued}


@app.post("/agent/tasks/{task_id}/result")
def receive_agent_task_result(
    task_id: str,
    result: TaskResult,
    x_healthit_token: str | None = Header(default=None),
) -> dict[str, str]:
    require_telemetry_token(x_healthit_token)

    completed = {
        "task_id": task_id,
        "machine_key": result.machine_key,
        "command": next(
            (
                task.get("command", "unknown")
                for task in task_results.get(result.machine_key, [])
                if task.get("task_id") == task_id
            ),
            "unknown",
        ),
        "status": result.status,
        "output": result.output,
        "created_at": None,
        "completed_at": result.completed_at or now_iso(),
    }

    history = task_results.setdefault(result.machine_key, [])
    for index, task in enumerate(history):
        if task.get("task_id") == task_id:
            completed["created_at"] = task.get("created_at")
            history[index] = completed
            break
    else:
        history.append(completed)

    persist_state()
    return {"message": "Task result received.", "task_id": task_id}


if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    logger.warning("Frontend directory not found: %s", FRONTEND_DIR)

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import socket
import time
import uuid
from typing import Any
from urllib import parse, request

import psutil


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


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def status(value: float, warning: float, critical: float, labels: tuple[str, str, str]) -> str:
    if value >= critical:
        return labels[2]
    if value >= warning:
        return labels[1]
    return labels[0]


def ip_addresses() -> list[dict[str, str]]:
    addresses = []
    for interface, items in psutil.net_if_addrs().items():
        for addr in items:
            if addr.family == socket.AF_INET and addr.address != "127.0.0.1":
                addresses.append({"interface": interface, "ip_address": addr.address})
    return addresses


def mac_addresses() -> list[dict[str, str]]:
    addresses = []
    for interface, items in psutil.net_if_addrs().items():
        for addr in items:
            family = str(addr.family)
            if ("AF_LINK" in family or "AF_PACKET" in family) and addr.address:
                addresses.append({"interface": interface, "mac_address": addr.address})
    return addresses


def snapshot(display_name: str | None, tags: list[str]) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk_path = "/" if platform.system() != "Windows" else "C:\\"
    disk = psutil.disk_usage(disk_path)
    net = psutil.net_io_counters()
    cpu_percent = round(psutil.cpu_percent(interval=1), 1)
    memory_percent = round(memory.percent, 1)
    disk_percent = round(disk.percent, 1)

    alerts = []
    if cpu_percent >= 80:
        alerts.append("CPU usage is high.")
    if memory_percent >= 80:
        alerts.append("Memory usage is high.")
    if disk_percent >= 90:
        alerts.append("Disk usage is critical.")
    elif disk_percent >= 70:
        alerts.append("Disk usage is elevated.")
    if net.errin or net.errout:
        alerts.append("Network errors detected.")

    overall = "Critical" if memory_percent >= 90 or disk_percent >= 90 else "Healthy"
    if overall == "Healthy" and alerts:
        overall = "Attention Needed"

    boot_time = psutil.boot_time()
    uptime_seconds = int(dt.datetime.now().timestamp() - boot_time)

    return {
        "display_name": display_name or socket.gethostname(),
        "tags": tags,
        "identity": {
            "hostname": socket.gethostname(),
            "device_name": platform.node(),
            "os_type": platform.system(),
            "os_release": platform.release(),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "current_user": os.getenv("USERNAME") or os.getenv("USER") or "Unknown",
            "ip_addresses": ip_addresses(),
            "mac_addresses": mac_addresses(),
            "boot_time": dt.datetime.fromtimestamp(boot_time).isoformat(),
            "uptime_seconds": uptime_seconds,
            "uptime_readable": format_uptime(uptime_seconds),
            "machine_id": str(uuid.getnode()),
        },
        "hardware": {
            "cpu_model": platform.processor() or "Unavailable",
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "total_memory_gb": round(memory.total / (1024**3), 2),
            "disk_devices": [],
            "temperature": {"max_temp_c": None, "sensors": []},
        },
        "cpu": {
            "percent": cpu_percent,
            "status": status(cpu_percent, 50, 80, ("Good Standing", "Moderate Load", "High Load")),
            "comment": "Live CPU load from the remote agent.",
        },
        "memory": {
            "percent": memory_percent,
            "used_gb": round(memory.used / (1024**3), 2),
            "total_gb": round(memory.total / (1024**3), 2),
            "status": status(
                memory_percent,
                60,
                80,
                ("Good Standing", "Maintenance Suggested", "Memory Overload"),
            ),
            "comment": "Live memory usage from the remote agent.",
        },
        "disk": {
            "percent": disk_percent,
            "used_gb": round(disk.used / (1024**3), 2),
            "total_gb": round(disk.total / (1024**3), 2),
            "status": status(
                disk_percent,
                70,
                90,
                ("Good Standing", "Maintenance Suggested", "Critical Condition"),
            ),
            "comment": "Live disk usage from the remote agent.",
        },
        "network": {
            "sent_mb": round(net.bytes_sent / (1024**2), 2),
            "received_mb": round(net.bytes_recv / (1024**2), 2),
            "upload_status": "Live",
            "upload_comment": "Network upload total since boot.",
            "download_status": "Live",
            "download_comment": "Network download total since boot.",
        },
        "packets": {
            "sent": net.packets_sent,
            "received": net.packets_recv,
            "sent_status": "Live",
            "sent_comment": "Packets sent since boot.",
            "received_status": "Live",
            "received_comment": "Packets received since boot.",
        },
        "errors": {
            "receive_errors": net.errin,
            "send_errors": net.errout,
        },
        "alerts": alerts,
        "overall_status": overall,
        "last_seen": now_iso(),
    }


def format_uptime(seconds: int) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def send_snapshot(url: str, payload: dict[str, Any], token: str | None) -> None:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-HealthIT-Token"] = token

    req = request.Request(url, data=data, headers=headers, method="POST")
    with request.urlopen(req, timeout=10) as response:
        response.read()


def task_output(command: str, current: dict[str, Any]) -> tuple[str, str]:
    if command not in ALLOWED_TASKS:
        return "rejected", f"Command not allowed: {command}"

    identity = current.get("identity", {})
    alerts = current.get("alerts", [])

    if command == "help":
        return "completed", "Allowed commands: " + ", ".join(sorted(ALLOWED_TASKS))
    if command in {"status", "refresh"}:
        return (
            "completed",
            f"{current.get('display_name')} is {current.get('overall_status')} | "
            f"CPU {current.get('cpu', {}).get('percent')}% | "
            f"Memory {current.get('memory', {}).get('percent')}% | "
            f"Disk {current.get('disk', {}).get('percent')}%",
        )
    if command == "uptime":
        return "completed", f"Uptime: {identity.get('uptime_readable', 'Unavailable')}"
    if command == "whoami":
        return "completed", f"User: {identity.get('current_user', 'Unknown')} on {identity.get('hostname', 'Unknown host')}"
    if command == "ip":
        addresses = identity.get("ip_addresses", [])
        if not addresses:
            return "completed", "No active IPv4 addresses reported."
        return "completed", "\n".join(
            f"{item.get('interface', 'interface')}: {item.get('ip_address')}" for item in addresses
        )
    if command == "disk":
        disk = current.get("disk", {})
        return (
            "completed",
            f"Disk: {disk.get('percent', '--')}% used | "
            f"{disk.get('used_gb', '--')} GB / {disk.get('total_gb', '--')} GB | "
            f"{disk.get('status', 'Unknown')}",
        )
    if command == "memory":
        memory = current.get("memory", {})
        return (
            "completed",
            f"Memory: {memory.get('percent', '--')}% used | "
            f"{memory.get('used_gb', '--')} GB / {memory.get('total_gb', '--')} GB | "
            f"{memory.get('status', 'Unknown')}",
        )
    if command == "network":
        network = current.get("network", {})
        errors = current.get("errors", {})
        return (
            "completed",
            f"Sent {network.get('sent_mb', '--')} MB | "
            f"Received {network.get('received_mb', '--')} MB | "
            f"Errors in/out {errors.get('receive_errors', '--')}/{errors.get('send_errors', '--')}",
        )
    if command == "alerts":
        return "completed", "\n".join(alerts) if alerts else "No active alerts."

    return "completed", f"{command} completed."


def get_tasks(server: str, machine_key: str, token: str | None) -> list[dict[str, Any]]:
    query = parse.urlencode({"machine_key": machine_key})
    headers = {}
    if token:
        headers["X-HealthIT-Token"] = token

    req = request.Request(f"{server.rstrip('/')}/agent/tasks?{query}", headers=headers, method="GET")
    with request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("tasks", [])


def send_task_result(server: str, task: dict[str, Any], machine_key: str, status_text: str, output: str, token: str | None) -> None:
    payload = {
        "task_id": task["task_id"],
        "machine_key": machine_key,
        "status": status_text,
        "output": output,
        "completed_at": now_iso(),
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-HealthIT-Token"] = token

    url = f"{server.rstrip('/')}/agent/tasks/{task['task_id']}/result"
    req = request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with request.urlopen(req, timeout=10) as response:
        response.read()


def main() -> None:
    parser = argparse.ArgumentParser(description="Send this computer's telemetry to HealthIT.")
    parser.add_argument("--server", default=os.getenv("HEALTHIT_SERVER", "http://127.0.0.1:8000"))
    parser.add_argument("--interval", type=int, default=int(os.getenv("HEALTHIT_AGENT_INTERVAL", "10")))
    parser.add_argument("--name", default=os.getenv("HEALTHIT_AGENT_NAME"))
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--token", default=os.getenv("HEALTHIT_TELEMETRY_TOKEN"))
    args = parser.parse_args()

    server = args.server.rstrip("/")
    telemetry_url = server + "/telemetry"
    print(f"Sending telemetry to {telemetry_url} every {args.interval}s. Press Ctrl+C to stop.")

    while True:
        current_snapshot = snapshot(args.name, args.tag)
        machine_key = current_snapshot["identity"]["machine_id"]
        try:
            send_snapshot(telemetry_url, current_snapshot, args.token)
            print(f"{now_iso()} telemetry sent")
        except Exception as exc:
            print(f"{now_iso()} telemetry failed: {exc}")

        try:
            for task in get_tasks(server, machine_key, args.token):
                status_text, output = task_output(task.get("command", ""), current_snapshot)
                send_task_result(server, task, machine_key, status_text, output, args.token)
                print(f"{now_iso()} task {task.get('command')} {status_text}")
        except Exception as exc:
            print(f"{now_iso()} task polling failed: {exc}")

        time.sleep(args.interval)


if __name__ == "__main__":
    main()

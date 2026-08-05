from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
#import smtplib
#from email.message import EmailMessage
#from colorama import init # the color library
from fastapi import FastAPI # the library for the API
from fastapi import Body
import psutil  #the library for the actual data from my computer
#import time #library for time
import csv #library for log and excel files
import os # the operating s ystem library which brings compatibility with linux
import sys
import platform
import socket
import uuid
import datetime
import subprocess

print(sys.executable)
#init(autoreset=True)
app = FastAPI()
app.mount("/app", StaticFiles(directory="../frontend", html=True), name="frontend")
#cors issues solution
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# This is where the Log file is created and instated into the system
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(BASE_DIR, "HealthIT_systemlog.csv")

if not os.path.exists(log_file):
    with open(log_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            "The Timestamp",
            "CPU %", "CPU Status",
            "RAM %", "RAM Status",
            "Disk %", "Disk Status",
            "Network sent (MB)", "Sent Status",
            "Network recieved (MB)", "Sent Status",
            "Packets Sent", "Packet Sent Status",
            "Packets Recieved", "Packet Recieved Status",
            "Recieving Errors", "Sending Errors"
        ])

# In-memory storage for remote machine telemetry
remote_machines = {}

##### Getting cpu ram and disk status and usage data #####
# Status-checking functions for testing
def get_cpu_status(cpu_percent):
    if cpu_percent < 50:
        return "Good Standing"
    elif cpu_percent < 80:
        return "Moderate Load"
    else:
        return "High Load"

def get_memory_status(memory_percent):
    if memory_percent < 60:
        return "Good Standing"
    elif memory_percent < 80:
        return "Maintenance Suggested"
    else:
        return "Memory Overload"

def get_disk_status(disk_percent):
    if disk_percent < 70:
        return "Good Standing"
    elif disk_percent < 90:
        return "Maintenance Suggested"
    else:
        return "Critical Condition"


def format_uptime(seconds):
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def get_ip_addresses():
    ip_addresses = []
    try:
        interfaces = psutil.net_if_addrs()
        for interface_name, address_list in interfaces.items():
            for addr in address_list:
                if addr.family == socket.AF_INET:
                    if addr.address != "127.0.0.1":
                        ip_addresses.append({
                            "interface": interface_name,
                            "ip_address": addr.address
                        })
    except Exception:
        pass
    return ip_addresses


def get_mac_addresses():
    mac_addresses = []
    try:
        interfaces = psutil.net_if_addrs()
        for interface_name, address_list in interfaces.items():
            for addr in address_list:
                addr_family = str(addr.family)
                if ("AF_LINK" in addr_family or "AF_PACKET" in addr_family) and addr.address:
                    mac_addresses.append({
                        "interface": interface_name,
                        "mac_address": addr.address
                    })
    except Exception:
        pass
    return mac_addresses


def get_system_identity():
    hostname = socket.gethostname()

    try:
        boot_time = psutil.boot_time()
        uptime_seconds = int(datetime.datetime.now().timestamp() - boot_time)
        uptime_formatted = format_uptime(uptime_seconds)
        boot_time_readable = datetime.datetime.fromtimestamp(boot_time).isoformat()
    except Exception:
        uptime_seconds = None
        uptime_formatted = "Unavailable"
        boot_time_readable = "Unavailable"

    identity = {
        "hostname": hostname,
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
        "boot_time": boot_time_readable,
        "uptime_seconds": uptime_seconds,
        "uptime_readable": uptime_formatted,
        "machine_id": str(uuid.getnode()),
    }
    return identity


def get_cpu_model():
    try:
        cpu_model = platform.processor()
        if cpu_model and cpu_model.strip():
            return cpu_model
    except Exception:
        pass

    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as file:
                for line in file:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass

    return "Unavailable"


def get_disk_models():
    disk_models = []

    if platform.system() == "Linux":
        try:
            result = subprocess.run(
                ["lsblk", "-d", "-o", "NAME,MODEL,SIZE,TYPE"],
                capture_output=True,
                text=True,
                check=False
            )
            lines = result.stdout.strip().splitlines()
            for line in lines[1:]:
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    disk_models.append({
                        "name": parts[0],
                        "model": parts[1],
                        "size": parts[2],
                        "type": parts[3]
                    })
        except Exception:
            pass

    return disk_models


def get_temperature_info():
    temperatures = []
    max_temp = None

    try:
        temp_data = psutil.sensors_temperatures()
        if temp_data:
            for sensor_name, entries in temp_data.items():
                for entry in entries:
                    current_temp = entry.current
                    label_name = entry.label if entry.label else sensor_name

                    temperatures.append({
                        "sensor": sensor_name,
                        "label": label_name,
                        "current_c": current_temp,
                        "high_c": entry.high,
                        "critical_c": entry.critical
                    })

                    if current_temp is not None:
                        if max_temp is None or current_temp > max_temp:
                            max_temp = current_temp
    except Exception:
        pass

    return {
        "max_temp_c": max_temp,
        "sensors": temperatures
    }


def get_failed_services():
    failed_services = []

    if platform.system() == "Linux":
        try:
            result = subprocess.run(
                ["systemctl", "--failed", "--no-legend", "--plain"],
                capture_output=True,
                text=True,
                check=False
            )

            lines = result.stdout.strip().splitlines()
            for line in lines:
                if line.strip():
                    service_name = line.split()[0]
                    failed_services.append(service_name)
        except Exception:
            pass

    return failed_services


def get_hardware_info():
    memory = psutil.virtual_memory()

    hardware = {
        "cpu_model": get_cpu_model(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "total_memory_gb": round(memory.total / (1024 ** 3), 2),
        "disk_devices": get_disk_models(),
        "temperature": get_temperature_info()
    }

    return hardware


def collect_system_metrics():
    #### Pulls and formats the data ####

    # this is where it pulls data from CPU in 1 second interval
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_status = get_cpu_status(cpu_percent)
    # pulls from earlier functions to state and format the status of ram
    if cpu_status == "Good Standing":
        cpu_comment = "System is performing efficently"
    elif cpu_status == "Moderate Load":
        cpu_comment = "System is Okay, but avoid overloading it."
    else:
        cpu_comment = "Close unnecessary apps or check for issues."

    #RAM
    memory = psutil.virtual_memory()
    memory_percent = memory.percent
    memory_used = memory.used / (1024 ** 3)
    memory_total = memory.total / (1024 ** 3)
    # pulls from earlier functions to state and format the status of ram
    memory_status = get_memory_status(memory_percent)
    # status for RAM
    if memory_status == "Good Standing":
        ram_comment = "Plenty of memory availabe."
    elif memory_status == "Maintenance Suggested":
        ram_comment = "Monitor open programs and clean unused ones."
    else:
        ram_comment = "Close memory-heavy apps and monitor open programs."

    # Disk usage
    disk_path = "/" if platform.system() != "Windows" else "C:\\"
    disk = psutil.disk_usage(disk_path) # this pull from root directoryt about total,used, free and usage percentage
    disk_used = disk.used / (1024 ** 3) #converts bytes to Giga bytes
    disk_total = disk.total / (1024 ** 3)
    disk_percent = disk.percent
    disk_status = get_disk_status(disk_percent)
    # pulls from earlier functions to state and format the status of disk
    if disk_status == "Good Standing":
        disk_comment = "No Issues"
    elif disk_status == "Maintenance Suggested":
        disk_comment = "Monitor and clean temporary or unused files."
    else:
        disk_comment = "Free Disk space now to avoid issues."

    #network stats
    net = psutil.net_io_counters()
    network_sent_mb = net.bytes_sent / (1024 ** 2)
    network_received_mb = net.bytes_recv / (1024 ** 2)

    #status for network (network_sent_mb)
    if network_sent_mb < 100:
        upload_status = "Idle/Light"
        upload_comment = "Minimal outgoing network activity."
    elif network_sent_mb < 500:
        upload_status = "Light Uploads"
        upload_comment = "Some background sync or small uploads."
    elif network_sent_mb < 1000:
        upload_status = "Moderate"
        upload_comment = "Medium upload usage."
    elif network_sent_mb < 5000:
        upload_status = "High Usage"
        upload_comment = "Large uploads or backups happening."
    else:
        upload_status = "Heavy/Unusual"
        upload_comment = "High upload detected — investigate."

    #status for network (bytes recieved)
    if network_received_mb < 100:
        download_status = "Idle/Light"
        download_comment = "Minimal incoming network activity."
    elif network_received_mb < 500:
        download_status = "Light Downloads"
        download_comment = "Background updates or light use."
    elif network_received_mb < 2000:
        download_status = "Moderate"
        download_comment = "Normal downloads or media use."
    elif network_received_mb < 5000:
        download_status = "High Usage"
        download_comment = "Large files or streaming."
    else:
        download_status = "Heavy/Unusual"
        download_comment = "Very high download — check activity."

    #Packets
    packets_sent = net.packets_sent
    packets_received = net.packets_recv

    #status for packets sent
    if packets_sent < 10000:
        packets_sent_status = "Very Light"
        packets_sent_comment = "Normal system use."
    elif packets_sent < 50000:
        packets_sent_status = "Moderate"
        packets_sent_comment = "Some apps are sending data."
    elif packets_sent < 200000:
        packets_sent_status = "High"
        packets_sent_comment = "Sustained upload activity."
    else:
        packets_sent_status = "Alert"
        packets_sent_comment = "Unusually high packet count."

    #status for packets recieved
    if packets_received < 10000:
        packets_received_status = "Very Light"
        packets_received_comment = "Minimal network activity."
    elif packets_received < 50000:
        packets_received_status = "Moderate"
        packets_received_comment = "Regular downloads or syncs."
    elif packets_received < 200000:
        packets_received_status = "High"
        packets_received_comment = "Sustained downloads or streaming."
    else:
        packets_received_status = "Alert"
        packets_received_comment = "High inbound activity — monitor closely."

    # Error Handling
    receive_errors = net.errin
    send_errors = net.errout

    #### variable dictionary ####
    metrics = {
        "cpu": {
            "percent": cpu_percent,
            "status": cpu_status,
            "comment": cpu_comment
        },
        "memory": {
            "percent": memory_percent,
            "used_gb": memory_used,
            "total_gb": memory_total,
            "status": memory_status,
            "comment": ram_comment
        },
        "disk": {
            "percent": disk_percent,
            "used_gb": disk_used,
            "total_gb": disk_total,
            "status": disk_status,
            "comment": disk_comment
        },
        "network": {
            "sent_mb": network_sent_mb,
            "received_mb": network_received_mb,
            "upload_status": upload_status,
            "upload_comment": upload_comment,
            "download_status": download_status,
            "download_comment": download_comment
        },
        "packets": {
            "sent": packets_sent,
            "received": packets_received,
            "sent_status": packets_sent_status,
            "sent_comment": packets_sent_comment,
            "received_status": packets_received_status,
            "received_comment": packets_received_comment
        },
        "errors": {
            "receive_errors": receive_errors,
            "send_errors": send_errors
        }
    }
    return metrics


def build_alerts(identity, hardware, metrics):
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
    if max_temp is not None:
        if max_temp >= 90:
            alerts.append("System temperature is critical.")
        elif max_temp >= 75:
            alerts.append("System temperature is elevated.")

    failed_services = get_failed_services()
    for service in failed_services:
        alerts.append(f"Failed service detected: {service}")

    if len(identity["ip_addresses"]) == 0:
        alerts.append("No active IPv4 address detected.")

    return alerts


def get_overall_status(metrics, alerts):
    if metrics["disk"]["percent"] >= 90:
        return "Critical"
    if metrics["memory"]["percent"] >= 90:
        return "Critical"
    if len(alerts) >= 3:
        return "Warning"
    if len(alerts) > 0:
        return "Attention Needed"
    return "Healthy"


def collect_full_snapshot():
    identity = get_system_identity()
    hardware = get_hardware_info()
    metrics = collect_system_metrics()
    alerts = build_alerts(identity, hardware, metrics)
    timestamp = datetime.datetime.now().isoformat()

    snapshot = {
        **metrics,
        "identity": identity,
        "hardware": hardware,
        "alerts": alerts,
        "last_seen": timestamp,
        "overall_status": get_overall_status(metrics, alerts)
    }

    return snapshot


# test route for API
@app.get("/")
def home():
    return {"message": "HealthIT API is running!"}


@app.get("/metrics")
def read_metrics():
    return collect_full_snapshot()


@app.post("/telemetry")
def receive_telemetry(payload: dict = Body(...)):
    identity = payload.get("identity", {})
    hostname = identity.get("hostname", "unknown_machine")

    payload["last_seen"] = datetime.datetime.now().isoformat()
    remote_machines[hostname] = payload

    return {
        "message": "Telemetry received successfully.",
        "hostname": hostname
    }


@app.get("/machines")
def get_all_remote_machines():
    return remote_machines


@app.get("/machines/{hostname}")
def get_remote_machine(hostname: str):
    if hostname in remote_machines:
        return remote_machines[hostname]
    return {"error": "Machine not found."}


#    ############# System logging ##################
#    #Appends the system info to the csv file
#    with open(log_file, mode='a', newline='') as file:
#        writer = csv.writer(file)
#        writer.writerow([
#            time.ctime(),
#            cpu_percent, cpu_status,
#            memory_percent, memory_status,
#            disk_percent, disk_status,
#            network_sent_mb, upload_status,
#            network_received_mb, download_status,
#            packets_sent, packets_sent_status,
#            packets_received, packets_received_status,
#            receive_errors, send_errors
#        ])

    ############# Email functionality ##################
#    #email sending function
#   def send_HealthIT_email(summary):
#        sender_email = "santiago.carbajal.0616@gmail.com"
#        receiver_email = "santiago.carbajal.0616@gmail.com"
#        app_password = "gykeoavmfwgiphqh"

#        msg = EmailMessage()
# #       msg["Subject"] = "Daily HealthIT System Report"
#        msg["From"] = sender_email
#        msg["To"] = receiver_email
#        msg.set_content(summary)

#        try:
#            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
#                smtp.login(sender_email, app_password)
#                smtp.send_message(msg)
#            print("Email Successfully Sent!")
#        except Exception as e:
#            print(f"Failed to send email: {e}")

#    summary = f"""
#    === Daily Health Report ===
#    Timestamp: {time.ctime()}

#    CPU Usage: {cpu_percent}% - {cpu_status}
#    RAM Usage: {memory_percent}% - {memory_status}
#    Disk Usage: {disk_percent}% - {disk_status}
#    Network Sent: {network_sent_mb: .2f} MB - {upload_status}
#    Network Received: {network_received_mb: .2f} MB - {download_status}
#    Packets Sent: {packets_sent} - {packets_sent_status}
#    Packets Received: {packets_received} - {packets_received_status}

#    Errors In: {receive_errors}
#    Errors Out: {send_errors}
#    """
#    send_HealthIT_email(summary)
# HealthIT System Monitor

HealthIT System Monitor is a lightweight telemetry dashboard for checking the health of computers you care about: your own machine, a homelab server, a repair-bench computer, or a small cluster of devices.

The goal is simple: connect a computer, see how it is doing, and understand when something needs attention without needing to sit in front of that machine.

## What It Does

- Shows live local CPU, memory, disk, network, packet, identity, and hardware information.
- Highlights machine health as Healthy, Attention Needed, Warning, or Critical.
- Accepts telemetry from remote computers through a simple HTTP endpoint.
- Displays local and remote machines in one dashboard.
- Provides a multi-session browser terminal that runs commands from the dashboard server.
- Includes an animated, game-inspired frontend with live metric cards, alerts, and small history charts.
- Includes a demo mode so the dashboard can be viewed even before remote machines are connected.

## Project Structure

```text
healthit-system-monitor/
├── agent.py                  # Lightweight remote telemetry sender
├── backend/
│   ├── Health_Logger.py      # FastAPI app and telemetry collection
│   └── __init__.py
├── frontend/
│   ├── index.html            # Dashboard shell
│   ├── script.js             # Polling, rendering, demo mode, charts
│   └── style.css             # Modern dashboard styling
├── requirements.txt
└── README.md
```

## Local Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run the dashboard API from the project root:

```powershell
python -m uvicorn backend.Health_Logger:app --reload
```

Open the dashboard:

```text
http://127.0.0.1:8000/app
```

API docs are available at:

```text
http://127.0.0.1:8000/docs
```

## Remote Telemetry

Start the main dashboard on the computer that will receive telemetry:

```powershell
python -m uvicorn backend.Health_Logger:app --host 0.0.0.0 --port 8000
```

On another computer, install the same requirements and run:

```powershell
python agent.py --server http://YOUR-DASHBOARD-IP:8000 --name Lab-Node-01 --tag homelab
```

You can also deploy the agent from the dashboard with **Add Machine**. Enter the target name, IPv4 address/host, Controller URL, SSH username, port, and either SSH Password or SSH Key mode. Password SSH is intended for trusted local homelab testing and the password is not stored; SSH keys are recommended for ongoing use.

The remote computer will post telemetry to:

```text
POST /telemetry
```

The agent also polls for safe queued tasks from the dashboard. The main dashboard terminal is separate: it creates browser terminal sessions and runs commands on the dashboard server.

```text
alerts, disk, help, ip, memory, network, refresh, status, uptime, whoami
```

The terminal can launch SSH from the command line the same way a normal terminal would:

```text
ssh user@192.168.1.25
ssh user@server "docker ps"
```

For best results, configure SSH keys on the dashboard server first. Browser-based HTTP command execution is not a full TTY, so commands that require an interactive password prompt should be run with key-based auth or with a remote command:

```text
ssh user@server "uptime"
```

This terminal is intended for local dev and trusted homelab use, not public deployment.

Optional token protection:

```powershell
$env:HEALTHIT_TELEMETRY_TOKEN="change-me"
python -m uvicorn backend.Health_Logger:app --host 0.0.0.0 --port 8000
```

Then run the agent with the same token:

```powershell
python agent.py --server http://YOUR-DASHBOARD-IP:8000 --token change-me
```

## API Endpoints

- `GET /` - API status and links.
- `GET /health` - lightweight health check.
- `GET /metrics` - live local machine snapshot.
- `GET /machines` - local and remote machines in one response.
- `GET /machines/{machine_key}` - one machine by key.
- `POST /machines/{machine_key}/tasks` - run or queue a safe terminal task.
- `GET /machines/{machine_key}/tasks` - recent task results.
- `GET /terminal/sessions` - list browser terminal sessions.
- `POST /terminal/sessions` - create a browser terminal session.
- `POST /terminal/sessions/{session_id}/commands` - run a command in a terminal session.
- `POST /telemetry` - submit remote machine telemetry.
- `GET /agent/tasks` - remote agent task polling endpoint.
- `POST /agent/tasks/{task_id}/result` - remote agent task result endpoint.

## Why This Project Exists

This project started from a practical idea: sometimes you want to know what is happening on a computer without physically being there. Maybe it is a homelab server, a family computer, a VM, or a machine you are troubleshooting.

HealthIT turns that into a friendly control room: connect machines, watch their vitals, and catch problems before they become mysterious.

## Roadmap

Phase 1 focused on making the app reliable and presentable: reproducible dependencies, safer backend defaults, better docs, and a modern dashboard.

Phase 2 added the remote telemetry path: a lightweight agent, validated telemetry payloads, optional token protection, and multi-machine API responses.

Phase 3 starts turning the idea into a homelab/cluster monitor: fleet view, stale-machine detection, alerts, demo mode, live charts, and a more interactive interface.

Next improvements could include persistent history, authentication, machine groups, charts over time, Docker support, deployment instructions, and a carefully secured remote shell mode with authentication, audit logs, and explicit per-machine opt-in.

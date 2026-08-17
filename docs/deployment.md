# Deployment Notes

HealthIT is meant to run on a computer inside your own network.

The usual setup is:

```text
Your browser -> HealthIT dashboard computer -> SQLite
                                      ^
                                      |
                              Raspberry Pi / lab machines
```

GitHub hosts the code, but it does not run the live app. The dashboard needs a Python/FastAPI server so agents can send telemetry back to it.

## Good Local Setup

Run this on the dashboard computer:

```powershell
python -m uvicorn backend.Health_Logger:app --host 0.0.0.0 --port 8000
```

Then open:

```text
http://127.0.0.1:8000/app
```

For other machines to connect, use the dashboard computer's LAN address as the Controller URL:

```text
http://YOUR-DASHBOARD-IP:8000
```

## Why Not GitHub Pages?

GitHub Pages only serves static files. HealthIT needs the backend running for:

- live local metrics
- remote telemetry posts
- SSH agent deployment
- terminal sessions
- SQLite persistence

So GitHub Pages can show a static demo later, but not the full working app.

## Later

The clean next deployment step is Docker or a small homelab server service.

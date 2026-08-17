import os

os.environ.setdefault("HEALTHIT_DB_PATH", "data/test-healthit.db")

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.Health_Logger import (
    app,
    deploy_failure,
    deploy_step,
    machine_overrides,
    registered_machines,
    remote_machines,
    task_results,
    terminal_sessions,
)


client = TestClient(app)


def reset_state() -> None:
    """Keep tests independent from whatever the local dashboard has been doing."""
    remote_machines.clear()
    registered_machines.clear()
    machine_overrides.clear()
    terminal_sessions.clear()
    task_results.clear()


def test_health_endpoint_is_alive():
    reset_state()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_register_machine_and_detect_duplicate():
    reset_state()
    payload = {
        "display_name": "Lab Node",
        "host": "192.168.1.50",
        "tags": ["homelab"],
    }

    created = client.post("/machines/register", json=payload)
    duplicate = client.post("/machines/register", json=payload)

    assert created.status_code == 200
    assert created.json()["already_exists"] is False
    assert duplicate.status_code == 200
    assert duplicate.json()["already_exists"] is True


def test_pending_machine_becomes_remote_when_telemetry_arrives():
    reset_state()
    client.post(
        "/machines/register",
        json={"display_name": "Pi Node", "host": "192.168.1.60", "tags": ["pi"]},
    )

    response = client.post(
        "/telemetry",
        json={
            "display_name": "Pi Node",
            "identity": {
                "hostname": "pi-node",
                "machine_id": "pi-node-001",
                "ip_addresses": [{"interface": "eth0", "ip_address": "192.168.1.60"}],
            },
            "cpu": {"percent": 12},
            "memory": {"percent": 30},
            "disk": {"percent": 20},
        },
    )

    machines = client.get("/machines").json()["machines"]

    assert response.status_code == 200
    assert response.json()["machine_key"] == "pi-node-001"
    assert any(machine["machine_key"] == "pi-node-001" for machine in machines)
    assert not registered_machines


def test_deploy_step_keeps_frontend_error_details_consistent():
    step = deploy_step("Checking python3", "failed", "python3 --version", "", "not found", 1)

    assert step["label"] == "Checking python3"
    assert step["status"] == "failed"
    assert step["stderr"] == "not found"


def test_deploy_failure_has_a_human_message_and_failed_step():
    error = deploy_failure(
        "Installing dependencies",
        "pip install psutil requests",
        "",
        "network unavailable",
        1,
        "Check internet access on the target machine.",
    )

    assert isinstance(error, HTTPException)
    assert error.detail["message"] == "Installing dependencies failed."
    assert error.detail["step"]["status"] == "failed"
    assert "internet access" in error.detail["hint"]

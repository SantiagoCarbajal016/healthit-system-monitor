const API_URL = "http://127.0.0.1:8000/metrics";

async function fetchMetrics() {
    console.log("fetching metrics...");

    try {
        const response = await fetch(API_URL);
        console.log("response:", response);

        const data = await response.json();
        console.log("data:", data);

        // ========================
        // CPU
        // ========================
        document.getElementById("cpu-percent").textContent =
            `Usage: ${data.cpu.percent}%`;
        document.getElementById("cpu-status").textContent =
            `Status: ${data.cpu.status}`;

        // ========================
        // MEMORY
        // ========================
        document.getElementById("memory-percent").textContent =
            `Usage: ${data.memory.percent}%`;
        document.getElementById("memory-status").textContent =
            `Status: ${data.memory.status}`;

        // ========================
        // DISK
        // ========================
        document.getElementById("disk-percent").textContent =
            `Usage: ${data.disk.percent}%`;
        document.getElementById("disk-status").textContent =
            `Status: ${data.disk.status}`;

        // ========================
        // NETWORK
        // ========================
        document.getElementById("network-sent").textContent =
            `Sent: ${data.network.sent_mb.toFixed(2)} MB`;
        document.getElementById("network-recv").textContent =
            `Received: ${data.network.received_mb.toFixed(2)} MB`;
        document.getElementById("network-status").textContent =
            `Upload: ${data.network.upload_status} | Download: ${data.network.download_status}`;

        // ========================
        // SYSTEM IDENTITY (NEW)
        // ========================
        if (data.identity) {
            document.getElementById("hostname").textContent =
                `Host: ${data.identity.hostname}`;

            document.getElementById("os-info").textContent =
                `OS: ${data.identity.os_type} ${data.identity.os_release}`;

            document.getElementById("uptime").textContent =
                `Uptime: ${data.identity.uptime_readable}`;

            if (data.identity.ip_addresses?.length > 0) {
                document.getElementById("ip-address").textContent =
                    `IP: ${data.identity.ip_addresses[0].ip_address}`;
            }

            if (data.identity.mac_addresses?.length > 0) {
                document.getElementById("mac-address").textContent =
                    `MAC: ${data.identity.mac_addresses[0].mac_address}`;
            }
        }

        // ========================
        // HARDWARE (NEW)
        // ========================
        if (data.hardware) {
            document.getElementById("cpu-model").textContent =
                `CPU: ${data.hardware.cpu_model}`;

            document.getElementById("ram-total").textContent =
                `RAM: ${data.hardware.total_memory_gb} GB`;

            if (data.hardware.temperature?.max_temp_c !== null) {
                document.getElementById("temperature").textContent =
                    `Temp: ${data.hardware.temperature.max_temp_c} °C`;
            } else {
                document.getElementById("temperature").textContent =
                    `Temp: Unavailable`;
            }
        }

        // ========================
        // ALERTS (NEW)
        // ========================
        const alertsContainer = document.getElementById("alerts");
        alertsContainer.innerHTML = "";

        if (data.alerts && data.alerts.length > 0) {
            data.alerts.forEach(alert => {
                const li = document.createElement("li");
                li.textContent = alert;
                alertsContainer.appendChild(li);
            });
        } else {
            alertsContainer.innerHTML = "<li>No active alerts</li>";
        }

        // ========================
        // OVERALL STATUS (NEW)
        // ========================
        if (data.overall_status) {
            document.getElementById("overall-status").textContent =
                `Status: ${data.overall_status}`;
        }

    } catch (error) {
        console.error("FETCH FAILED:", error);
        document.getElementById("cpu-percent").textContent = "Fetch failed";
    }
}

fetchMetrics();
setInterval(fetchMetrics, 5000);
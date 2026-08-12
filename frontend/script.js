const API_BASE = window.location.protocol.startsWith("http") ? window.location.origin : "http://127.0.0.1:8000";

const state = {
    machines: [],
    selectedKey: null,
    filter: "all",
    search: "",
    panelLayout: JSON.parse(localStorage.getItem("healthit.panelLayout") || "{}"),
    customPanels: JSON.parse(localStorage.getItem("healthit.customPanels") || "[]"),
    panelOverrides: JSON.parse(localStorage.getItem("healthit.panelOverrides") || "{}"),
    editingCustomPanelId: null,
    editingBuiltInPanelId: null,
    history: new Map(),
    terminalSessions: [],
    activeTerminalId: null,
    visibleTerminalIds: [],
    activePanelDrag: null,
};

const els = {
    fleetSummary: document.getElementById("fleet-summary"),
    machineCount: document.getElementById("machine-count"),
    machineList: document.getElementById("machine-list"),
    toast: document.getElementById("toast"),
    machineSearch: document.getElementById("machine-search"),
    refreshButton: document.getElementById("refresh-button"),
    resetLayoutButton: document.getElementById("reset-layout-button"),
    addCustomPanelButton: document.getElementById("add-custom-panel-button"),
    addMachineForm: document.getElementById("add-machine-form"),
    newMachineName: document.getElementById("new-machine-name"),
    newMachineHost: document.getElementById("new-machine-host"),
    newMachineControllerUrl: document.getElementById("new-machine-controller-url"),
    newMachineLoginType: document.getElementById("new-machine-login-type"),
    newMachineSshUser: document.getElementById("new-machine-ssh-user"),
    newMachineSshPort: document.getElementById("new-machine-ssh-port"),
    newMachineSshPassword: document.getElementById("new-machine-ssh-password"),
    newMachineTags: document.getElementById("new-machine-tags"),
    deployProgress: document.getElementById("deploy-progress"),
    deployProgressLabel: document.getElementById("deploy-progress-label"),
    deployProgressValue: document.getElementById("deploy-progress-value"),
    deployProgressBar: document.getElementById("deploy-progress-bar"),
    deployStepList: document.getElementById("deploy-step-list"),
    deployDetails: document.getElementById("deploy-details"),
    deployDetailsOutput: document.getElementById("deploy-details-output"),
    retryDeployButton: document.getElementById("retry-deploy-button"),
    connectCommand: document.getElementById("connect-command"),
    customPanelDialog: document.getElementById("custom-panel-dialog"),
    customPanelForm: document.getElementById("custom-panel-form"),
    customPanelTitle: document.getElementById("custom-panel-title"),
    customPanelCode: document.getElementById("custom-panel-code"),
    cancelCustomPanelButton: document.getElementById("cancel-custom-panel-button"),
    selectedSource: document.getElementById("selected-source"),
    selectedName: document.getElementById("selected-name"),
    selectedMeta: document.getElementById("selected-meta"),
    statusBadge: document.getElementById("status-badge"),
    lastUpdated: document.getElementById("last-updated"),
    connectionStatus: document.getElementById("connection-status"),
    lastSeen: document.getElementById("last-seen"),
    networkVolume: document.getElementById("network-volume"),
    networkRate: document.getElementById("network-rate"),
    networkMini: document.getElementById("network-mini"),
    alertCount: document.getElementById("alert-count"),
    alerts: document.getElementById("alerts"),
    systemDetails: document.getElementById("system-details"),
    hardwareDetails: document.getElementById("hardware-details"),
    memoryDetails: document.getElementById("memory-details"),
    coreGrid: document.getElementById("core-grid"),
    cpuFrequency: document.getElementById("cpu-frequency"),
    swapSummary: document.getElementById("swap-summary"),
    storageList: document.getElementById("storage-list"),
    storageIo: document.getElementById("storage-io"),
    interfaceList: document.getElementById("interface-list"),
    interfaceCount: document.getElementById("interface-count"),
    processCpuList: document.getElementById("process-cpu-list"),
    processMemoryList: document.getElementById("process-memory-list"),
    processCount: document.getElementById("process-count"),
    powerSummary: document.getElementById("power-summary"),
    powerDetails: document.getElementById("power-details"),
    userCount: document.getElementById("user-count"),
    userList: document.getElementById("user-list"),
    terminalState: document.getElementById("terminal-state"),
    terminalWorkspace: document.getElementById("terminal-workspace"),
    terminalTabs: document.getElementById("terminal-tabs"),
    newTerminalButton: document.getElementById("new-terminal-button"),
    renameTerminalButton: document.getElementById("rename-terminal-button"),
    deleteTerminalButton: document.getElementById("delete-terminal-button"),
    splitTerminalButton: document.getElementById("split-terminal-button"),
    focusTerminalButton: document.getElementById("focus-terminal-button"),
};

function showToast(message, type = "info") {
    els.toast.textContent = message;
    els.toast.dataset.type = type;
    els.toast.classList.add("show");
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => els.toast.classList.remove("show"), 3600);
}

function saveCustomPanels() {
    localStorage.setItem("healthit.customPanels", JSON.stringify(state.customPanels));
}

function savePanelOverrides() {
    localStorage.setItem("healthit.panelOverrides", JSON.stringify(state.panelOverrides));
}

function dashboardUrlForAgents() {
    return window.location.origin;
}

function buildAgentCommand(machine) {
    const server = dashboardUrlForAgents();
    const command = `python agent.py --server ${server} --name "${machineName(machine)}"`;
    if (server.includes("127.0.0.1") || server.includes("localhost")) {
        return `${command}\n\nFor another computer, replace ${server} with this dashboard computer's LAN address, for example http://192.168.1.25:8000.`;
    }
    return command;
}

function setDeployProgress(percent, label) {
    els.deployProgress.hidden = false;
    els.deployProgressBar.value = percent;
    els.deployProgressValue.textContent = `${percent}%`;
    els.deployProgressLabel.textContent = label;
}

function hideDeployProgress() {
    if (!els.retryDeployButton.hidden) return;
    els.deployProgress.hidden = true;
}

const DEPLOY_STEPS = [
    "Connecting over SSH",
    "Creating remote agent folder",
    "Checking python3",
    "Creating virtual environment",
    "Installing dependencies",
    "Uploading agent",
    "Starting agent",
    "Verifying heartbeat",
];

function renderDeploySteps(steps = [], failed = false) {
    const byLabel = new Map(steps.map((step) => [step.label, step]));
    els.deployStepList.innerHTML = DEPLOY_STEPS.map((label) => {
        const step = byLabel.get(label);
        const status = step?.status || "pending";
        const className = status === "failed" ? "failed" : status === "completed" ? "completed" : "";
        const marker = status === "failed" ? "x" : status === "completed" ? "check" : "dot";
        return `<li class="${className}"><span>${marker}</span>${escapeHtml(label)}</li>`;
    }).join("");

    const done = steps.filter((step) => step.status === "completed").length;
    const failedStep = steps.find((step) => step.status === "failed");
    const percent = failed ? Math.max(8, Math.round((done / DEPLOY_STEPS.length) * 100)) : Math.round((done / DEPLOY_STEPS.length) * 100);
    setDeployProgress(failed ? percent : Math.min(96, percent), failedStep?.label || (failed ? "Failed" : "Deploying"));
    renderDeployDetails(steps);
}

function renderDeployDetails(steps = []) {
    const detailText = steps.map((step) => [
        `[${step.status || "pending"}] ${step.label}`,
        `command: ${step.command || "--"}`,
        `exit: ${step.exit_code ?? "--"}`,
        step.stdout ? `stdout:\n${step.stdout}` : "stdout: --",
        step.stderr ? `stderr:\n${step.stderr}` : "stderr: --",
    ].join("\n")).join("\n\n");
    els.deployDetails.hidden = !detailText;
    els.deployDetailsOutput.textContent = detailText;
}

function startDeployProgressLoop() {
    let count = 0;
    renderDeploySteps([]);
    return window.setInterval(() => {
        count = Math.min(DEPLOY_STEPS.length - 1, count + 1);
        const synthetic = DEPLOY_STEPS.slice(0, count).map((label) => ({ label, status: "completed" }));
        renderDeploySteps(synthetic);
    }, 1600);
}

function deploySummary(result) {
    const lines = [
        result.message || "Deploy finished.",
        result.server_url ? `Dashboard URL: ${result.server_url}` : null,
        result.target ? `SSH target: ${result.target}` : null,
        result.login_type ? `Login type: SSH ${result.login_type}` : null,
        "",
        ...(result.steps || []).map((step) => `${step.status === "failed" ? "x" : "check"} ${step.label}`),
    ].filter((line) => line !== null);
    return lines.join("\n");
}

async function loadDeployInfo() {
    try {
        const response = await fetch(`${API_BASE}/deploy-info`);
        if (!response.ok) return;
        const data = await response.json();
        if (!els.newMachineControllerUrl.value) els.newMachineControllerUrl.value = data.controller_url || "";
    } catch (error) {
        // Optional convenience only.
    }
}

function syncLoginTypeFields() {
    const usesPassword = els.newMachineLoginType.value === "password";
    els.newMachineSshPassword.hidden = !usesPassword;
    els.newMachineSshPassword.required = usesPassword && Boolean(els.newMachineHost.value.trim());
}

function valueAt(obj, path, fallback = "--") {
    return path.split(".").reduce((current, key) => current?.[key], obj) ?? fallback;
}

function machineName(machine) {
    return machine.display_name || valueAt(machine, "identity.hostname", "Unknown");
}

function machineKey(machine) {
    return machine.machine_key || valueAt(machine, "identity.machine_id", machineName(machine));
}

function machineStatus(machine) {
    const overall = (machine.overall_status || "").toLowerCase();
    if (machine.connection_status === "failed" || overall.includes("deploy failed")) return "critical";
    if (machine.connection_status === "pending" || machine.connection_status === "stale") return "offline";
    if (overall.includes("critical")) return "critical";
    if (overall.includes("warning") || overall.includes("attention")) return "warning";
    return "healthy";
}

function formatAge(seconds) {
    if (seconds === null || seconds === undefined) return "never";
    if (seconds < 5) return "now";
    if (seconds < 60) return `${seconds}s`;
    return `${Math.floor(seconds / 60)}m`;
}

function formatValue(value, suffix = "") {
    if (value === null || value === undefined || value === "--") return "--";
    if (value === "") return "Unavailable";
    return `${value}${suffix}`;
}

function cleanValue(value, fallback = "Unavailable") {
    if (value === null || value === undefined || value === "" || value === "--") return fallback;
    if (Array.isArray(value) && !value.length) return fallback;
    return value;
}

function formatDateTime(value) {
    if (!value || value === "--") return "Unavailable";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 22);
    return parsed.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
    });
}

function formatBatterySeconds(seconds) {
    if (seconds === null || seconds === undefined || seconds === "" || seconds === "--") return "Unavailable";
    const numeric = Number(seconds);
    if (!Number.isFinite(numeric) || numeric < 0 || numeric >= 2147483647) return "Unavailable";
    const minutes = Math.round(numeric / 60);
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function setMeter(id, value) {
    const numeric = Number(value || 0);
    const valueEl = document.getElementById(`${id}-value`);
    const meterEl = document.getElementById(`${id}-meter`);
    if (valueEl) valueEl.textContent = `${Math.round(numeric)}%`;
    if (meterEl) meterEl.style.width = `${Math.min(100, Math.max(0, numeric))}%`;
    const card = document.querySelector(`[data-metric="${id}"]`);
    if (card) {
        card.classList.remove("healthy", "warning", "critical");
        card.classList.add(numeric >= 90 ? "critical" : numeric >= 70 ? "warning" : "healthy");
    }
}

function remember(machine) {
    if (!machine.cpu) return;
    const key = machineKey(machine);
    const history = state.history.get(key) || { cpu: [], memory: [], disk: [] };
    const time = Date.now();
    history.cpu.push({ time, value: Number(valueAt(machine, "cpu.percent", 0)) });
    history.memory.push({ time, value: Number(valueAt(machine, "memory.percent", 0)) });
    history.disk.push({ time, value: Number(valueAt(machine, "disk.percent", 0)) });
    state.history.set(key, history);
}

function drawSparkline(canvasId, values, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    const left = 30;
    const bottom = 16;
    const top = 4;
    const plotWidth = width - left - 4;
    const plotHeight = height - top - bottom;
    const plotBottom = top + plotHeight;

    ctx.clearRect(0, 0, width, height);
    ctx.font = "9px Consolas, monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    [0, 25, 50, 75, 100].forEach((mark) => {
        const y = plotBottom - (mark / 100) * plotHeight;
        ctx.fillStyle = "rgba(204, 204, 220, 0.48)";
        ctx.fillText(String(mark), left - 7, y);
        ctx.strokeStyle = mark === 0 ? "rgba(204, 204, 220, 0.22)" : "rgba(204, 204, 220, 0.08)";
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(width - 4, y);
        ctx.stroke();
    });

    if (!values.length) {
        ctx.fillStyle = "rgba(167, 173, 186, 0.72)";
        ctx.textAlign = "center";
        ctx.fillText("No trend yet", left + plotWidth / 2, top + plotHeight / 2);
        return;
    }
    const firstTime = values[0].time;
    const lastTime = values[values.length - 1].time;
    const duration = Math.max(1, lastTime - firstTime);
    const points = values.map((point) => ({
        x: left + ((point.time - firstTime) / duration) * plotWidth,
        y: plotBottom - (Math.min(100, Math.max(0, point.value)) / 100) * plotHeight,
    }));

    ctx.strokeStyle = `${color}33`;
    ctx.lineWidth = 5;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    points.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();

    ctx.strokeStyle = color;
    ctx.lineWidth = 2.2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    points.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();
}

function filteredMachines() {
    return state.machines.filter((machine) => {
        const status = machineStatus(machine);
        const source = machine.source || "";
        const text = `${machineName(machine)} ${valueAt(machine, "identity.hostname", "")} ${(machine.tags || []).join(" ")}`.toLowerCase();
        const matchesSearch = text.includes(state.search.toLowerCase());
        const matchesFilter =
            state.filter === "all" ||
            (state.filter === "local" && source === "local") ||
            (state.filter === "connected" && status !== "offline") ||
            (state.filter === "offline" && status === "offline");
        return matchesSearch && matchesFilter;
    });
}

function renderMachines() {
    const machines = filteredMachines();
    els.machineCount.textContent = machines.length;
    els.machineList.innerHTML = "";
    if (!machines.length) {
        els.machineList.innerHTML = `<div class="empty-card">No machines match this view.</div>`;
        return;
    }
    machines.forEach((machine) => {
        const key = machineKey(machine);
        const status = machineStatus(machine);
        const button = document.createElement("button");
        button.className = `machine-button ${state.selectedKey === key ? "active" : ""}`;
        button.type = "button";
        button.innerHTML = `
            <span class="signal-dot ${status}"></span>
            <span>
                <span class="machine-name">${machineName(machine)}</span>
                <span class="machine-meta">${machine.source || "node"} / ${machine.connection_status || status} / ${formatAge(machine.age_seconds)}</span>
            </span>
            <span class="machine-actions">
                <span class="icon-action" data-action="edit" title="Edit" aria-label="Edit machine">✎</span>
                <span class="icon-action" data-action="delete" title="Remove" aria-label="Remove machine">×</span>
            </span>
        `;
        button.addEventListener("click", (event) => {
            const action = event.target.dataset.action;
            if (action === "edit") {
                event.stopPropagation();
                editMachine(machine);
                return;
            }
            if (action === "delete") {
                event.stopPropagation();
                deleteMachine(machine);
                return;
            }
            state.selectedKey = key;
            render();
        });
        els.machineList.appendChild(button);
    });
}

async function editMachine(machine) {
    const key = machineKey(machine);
    const currentHost = valueAt(machine, "identity.hostname", "");
    const name = window.prompt("Machine name", machineName(machine));
    if (!name || !name.trim()) return;
    const host = window.prompt("Host or IP", currentHost === "--" ? "" : currentHost);
    const tagsValue = window.prompt("Tags, comma separated", (machine.tags || []).join(", "));
    const tags = (tagsValue || "").split(",").map((tag) => tag.trim()).filter(Boolean);

    const response = await fetch(`${API_BASE}/machines/${encodeURIComponent(key)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: name.trim(), host: host?.trim() || null, tags }),
    });
    if (!response.ok) {
        showToast("Could not update machine.", "error");
        return;
    }
    showToast("Machine updated.", "success");
    await fetchMachines();
}

async function deleteMachine(machine) {
    const key = machineKey(machine);
    if (machine.source === "local") {
        showToast("Local dashboard machine cannot be removed.", "error");
        return;
    }
    if (!window.confirm(`Remove "${machineName(machine)}" from inventory?`)) return;
    const response = await fetch(`${API_BASE}/machines/${encodeURIComponent(key)}`, { method: "DELETE" });
    if (!response.ok) {
        showToast("Could not remove machine.", "error");
        return;
    }
    showToast("Machine removed.", "success");
    if (state.selectedKey === key) state.selectedKey = null;
    await fetchMachines();
}

function renderDetails(target, rows) {
    target.innerHTML = rows.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(cleanValue(value))}</dd></div>`).join("");
}

function renderList(target, rows, empty = "No data") {
    target.innerHTML = rows.length ? rows.join("") : `<div class="empty-row">${escapeHtml(empty)}</div>`;
}

function renderSelected(machine) {
    if (!machine) {
        els.selectedSource.textContent = "Inventory";
        els.selectedName.textContent = "No machines connected";
        els.selectedMeta.textContent = "Add a machine or start the local dashboard agent.";
        els.statusBadge.textContent = "Waiting";
        els.statusBadge.dataset.status = "offline";
        els.lastUpdated.textContent = "Last updated: --";
        return;
    }
    const status = machineStatus(machine);
    const identity = machine.identity || {};
    const hardware = machine.hardware || {};
    const alerts = machine.alerts || [];

    els.selectedSource.textContent = `${machine.source || "node"} / ${machine.connection_status || status}`;
    els.selectedName.textContent = machineName(machine);
    els.selectedMeta.textContent = [
        `${identity.os_type || ""} ${identity.os_release || ""}`.trim(),
        machine.connection_status || status,
        machine.source || "node",
    ].filter(Boolean).join(" / ") || "No telemetry yet";
    els.statusBadge.textContent = machine.overall_status || status;
    els.statusBadge.dataset.status = status;
    els.lastUpdated.textContent = `Last updated: ${formatDateTime(machine.last_seen)}`;
    els.connectionStatus.textContent = machine.connection_status || status;
    els.lastSeen.textContent = formatAge(machine.age_seconds);

    setMeter("cpu", Number(valueAt(machine, "cpu.percent", 0)));
    setMeter("memory", Number(valueAt(machine, "memory.percent", 0)));
    setMeter("disk", Number(valueAt(machine, "disk.percent", 0)));
    const cpuNote = document.getElementById("cpu-note");
    const memoryNote = document.getElementById("memory-note");
    const diskNote = document.getElementById("disk-note");
    if (cpuNote) cpuNote.textContent = valueAt(machine, "cpu.comment", "No CPU telemetry.");
    if (memoryNote) memoryNote.textContent = valueAt(machine, "memory.comment", "No memory telemetry.");
    if (diskNote) diskNote.textContent = valueAt(machine, "disk.comment", "No disk telemetry.");

    const history = state.history.get(machineKey(machine)) || { cpu: [], memory: [], disk: [] };
    drawSparkline("cpu-chart", history.cpu, "#f97316");
    drawSparkline("memory-chart", history.memory, "#73bf69");
    drawSparkline("disk-chart", history.disk, "#5794f2");

    els.networkRate.textContent = `${formatValue(valueAt(machine, "network.sent_mb", "--"), " MB")}`;
    els.networkVolume.textContent = `${formatValue(valueAt(machine, "network.sent_mb", "--"), " MB up")} / ${formatValue(valueAt(machine, "network.received_mb", "--"), " MB down")}`;
    renderList(els.networkMini, [
        `<div><span>Packets Sent</span><strong>${valueAt(machine, "packets.sent", "--")}</strong></div>`,
        `<div><span>Packets Received</span><strong>${valueAt(machine, "packets.received", "--")}</strong></div>`,
        `<div><span>Errors</span><strong>${valueAt(machine, "errors.receive_errors", "--")} / ${valueAt(machine, "errors.send_errors", "--")}</strong></div>`,
    ]);

    renderDetails(els.systemDetails, [
        ["Host", identity.hostname],
        ["Device", identity.device_name],
        ["OS", `${identity.os_type || "--"} ${identity.os_release || ""}`],
        ["Platform", identity.platform],
        ["User", identity.current_user],
        ["Uptime", identity.uptime_readable],
        ["IP", identity.ip_addresses?.map((item) => item.ip_address).join(", ")],
        ["MAC", identity.mac_addresses?.map((item) => item.mac_address).join(", ")],
    ]);

    renderDetails(els.hardwareDetails, [
        ["CPU", hardware.cpu_model],
        ["Cores", `${hardware.physical_cores || "--"} physical / ${hardware.logical_cores || "--"} logical`],
        ["RAM", formatValue(hardware.total_memory_gb, " GB")],
        ["Arch", identity.architecture],
        ["Temp", hardware.temperature?.max_temp_c == null ? "Unavailable" : `${hardware.temperature.max_temp_c} C`],
    ]);

    els.alertCount.textContent = alerts.length;
    els.alerts.innerHTML = alerts.length
        ? alerts.map((alert) => `<li>${escapeHtml(alert)}</li>`).join("")
        : `<li class="clear">No active alerts.</li>`;

    renderCoreGrid(machine);
    renderMemory(machine);
    renderStorage(machine);
    renderInterfaces(machine);
    renderProcesses(machine);
    renderPower(machine);
    renderUsers(machine);
}

function renderCoreGrid(machine) {
    const cores = valueAt(machine, "cpu.per_core_percent", []);
    els.cpuFrequency.textContent = valueAt(machine, "cpu.frequency_mhz", null) ? `${machine.cpu.frequency_mhz} MHz` : "--";
    els.coreGrid.innerHTML = cores.length ? cores.map((value, index) => `
        <div class="core-row">
            <span>Core ${index + 1}</span>
            <div class="mini-meter"><i style="width:${Math.min(100, value)}%"></i></div>
            <strong>${value}%</strong>
        </div>
    `).join("") : `<div class="empty-row">No per-core telemetry.</div>`;
}

function renderMemory(machine) {
    const swap = valueAt(machine, "memory.swap_percent", null);
    els.swapSummary.textContent = swap === null || swap === "--" ? "swap unavailable" : `${swap}% swap`;
    renderDetails(els.memoryDetails, [
        ["Used", formatValue(valueAt(machine, "memory.used_gb", "--"), " GB")],
        ["Available", formatValue(valueAt(machine, "memory.available_gb", "--"), " GB")],
        ["Total", formatValue(valueAt(machine, "memory.total_gb", "--"), " GB")],
        ["Swap Used", formatValue(valueAt(machine, "memory.swap_used_gb", "--"), " GB")],
        ["Swap Total", formatValue(valueAt(machine, "memory.swap_total_gb", "--"), " GB")],
    ]);
}

function renderStorage(machine) {
    const io = machine.storage?.io || {};
    els.storageIo.textContent = io.read_gb !== undefined ? `${io.read_gb} GB read / ${io.write_gb} GB write` : "--";
    const rows = (machine.storage?.partitions || []).map((part) => `
        <div class="table-row">
            <span>${escapeHtml(part.device || part.mountpoint || "Disk")}</span>
            <span>${escapeHtml(cleanValue(part.mountpoint))}</span>
            <span>${formatValue(part.percent, "%")}</span>
            <span>${formatValue(part.used_gb, " GB")} / ${formatValue(part.total_gb, " GB")}</span>
        </div>
    `);
    renderList(els.storageList, rows, "No storage telemetry.");
}

function renderInterfaces(machine) {
    const interfaces = machine.network_interfaces || [];
    els.interfaceCount.textContent = interfaces.length;
    const rows = interfaces.map((iface) => `
        <div class="table-row">
            <span>${escapeHtml(iface.name || "Interface")}</span>
            <span>${iface.is_up ? "up" : "down"}</span>
            <span>${iface.speed_mbps || "--"} Mbps</span>
            <span>${escapeHtml(cleanValue((iface.addresses || []).map((addr) => addr.address).slice(0, 2).join(", ")))}</span>
        </div>
    `);
    renderList(els.interfaceList, rows, "No interface telemetry.");
}

function renderProcesses(machine) {
    const processes = machine.processes || {};
    els.processCount.textContent = processes.count ?? "--";
    const cpuValue = (proc) => {
        const value = Number(proc.cpu_percent || 0);
        return value > 100 ? `${value}% CPU total` : `${value}% CPU`;
    };
    const row = (proc, value) => `
        <div class="table-row">
            <span>${escapeHtml(proc.name || "Process")}</span>
            <span>PID ${proc.pid}</span>
            <span>${escapeHtml(proc.status || "unknown")}</span>
            <span>${value}</span>
        </div>
    `;
    renderList(els.processCpuList, (processes.top_cpu || []).map((proc) => row(proc, cpuValue(proc))), "No process telemetry.");
    renderList(els.processMemoryList, (processes.top_memory || []).map((proc) => row(proc, `${proc.memory_percent}% MEM`)), "No process telemetry.");
}

function renderPower(machine) {
    const battery = machine.power?.battery;
    els.powerSummary.textContent = battery ? `${battery.percent}%` : "Unavailable";
    renderDetails(els.powerDetails, battery ? [
        ["Battery", `${battery.percent}%`],
        ["Plugged", battery.power_plugged ? "Yes" : "No"],
        ["Time Left", formatBatterySeconds(battery.seconds_left)],
    ] : [["Battery", "Unavailable"]]);
}

function renderUsers(machine) {
    const users = machine.user_sessions || [];
    els.userCount.textContent = users.length;
    renderList(els.userList, users.map((user) => `
        <div class="table-row">
            <span>${escapeHtml(cleanValue(user.name))}</span>
            <span>${escapeHtml(cleanValue(user.terminal))}</span>
            <span>${escapeHtml(cleanValue(user.host))}</span>
            <span>${escapeHtml(formatDateTime(user.started))}</span>
        </div>
    `), "No user sessions.");
}

function render() {
    if (!state.selectedKey && state.machines.length) state.selectedKey = machineKey(state.machines[0]);
    const selected = state.machines.find((machine) => machineKey(machine) === state.selectedKey) || state.machines[0];
    const connected = state.machines.filter((machine) => machineStatus(machine) !== "offline").length;
    els.fleetSummary.textContent = `${connected}/${state.machines.length} connected`;
    renderMachines();
    renderSelected(selected);
    applyPanelOverrides();
}

async function fetchMachines() {
    const response = await fetch(`${API_BASE}/machines`);
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const data = await response.json();
    state.machines = data.machines || [];
    state.machines.forEach(remember);
    render();
}

async function registerMachine(event) {
    event.preventDefault();
    const submitButton = els.addMachineForm.querySelector("button[type='submit']");
    submitButton.disabled = true;
    submitButton.textContent = "Deploying...";
    const tags = els.newMachineTags.value.split(",").map((tag) => tag.trim()).filter(Boolean);
    const displayName = els.newMachineName.value.trim();
    const host = els.newMachineHost.value.trim();
    const progressTimer = host ? startDeployProgressLoop() : null;
    let deploySucceeded = false;
    try {
        const endpoint = host ? "/machines/deploy-ssh" : "/machines/register";
        const body = host
            ? {
                display_name: displayName,
                host,
                controller_url: els.newMachineControllerUrl.value.trim() || null,
                login_type: els.newMachineLoginType.value,
                ssh_user: els.newMachineSshUser.value.trim() || "pi",
                ssh_password: els.newMachineLoginType.value === "password" ? els.newMachineSshPassword.value : null,
                ssh_port: Number(els.newMachineSshPort.value || 22),
                tags,
            }
            : {
                display_name: displayName,
                host: null,
                tags,
            };
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const result = await response.json();
        if (!response.ok) {
            const detail = result.detail;
            const message = typeof detail === "object"
                ? [
                    detail.message || "SSH deployment failed.",
                    detail.step?.stderr ? `stderr: ${detail.step.stderr}` : null,
                    detail.step?.stdout ? `stdout: ${detail.step.stdout}` : null,
                    detail.hint || null,
                ].filter(Boolean).join("\n\n")
                : detail || "Could not add machine.";
            const deployError = new Error(message);
            deployError.deployDetail = detail;
            throw deployError;
        }
        const machine = result.machine || result;
        if (machine.already_exists) {
            showToast(`"${machineName(machine)}" is already in the inventory or already running.`, "warning");
        } else if (host) {
            showToast(`"${displayName}" deployed over SSH. Waiting for telemetry.`, "success");
            els.addMachineForm.reset();
            els.newMachineLoginType.value = "password";
            els.newMachineSshUser.value = "pi";
            els.newMachineSshPort.value = "22";
            syncLoginTypeFields();
        } else {
            showToast(`"${machineName(machine)}" added. Run the agent command on that computer.`, "success");
            els.addMachineForm.reset();
        }
        if (host) {
            renderDeploySteps(result.steps || []);
            setDeployProgress(100, "Online");
            els.retryDeployButton.hidden = true;
        }
        els.connectCommand.textContent = host ? deploySummary(result) : machine.connect_command ? buildAgentCommand(machine) : machine.message || "Registered.";
        deploySucceeded = true;
        await fetchMachines();
        state.selectedKey = machine.machine_key || state.selectedKey;
        render();
    } catch (error) {
        if (error.deployDetail?.steps || error.deployDetail?.step) {
            renderDeploySteps(error.deployDetail.steps || [error.deployDetail.step], true);
        }
        els.retryDeployButton.hidden = !host;
        els.connectCommand.textContent = error.message;
        showToast(error.message, "error");
    } finally {
        if (progressTimer) window.clearInterval(progressTimer);
        if (host && !els.deployProgress.hidden && deploySucceeded) setDeployProgress(100, "Online");
        if (deploySucceeded) window.setTimeout(hideDeployProgress, 1600);
        submitButton.disabled = false;
        submitButton.textContent = "Deploy";
    }
}

function savePanelLayout() {
    localStorage.setItem("healthit.panelLayout", JSON.stringify(state.panelLayout));
}

function setupPanelControls() {
    document.querySelectorAll(".dashboard-box").forEach((box, index) => {
        const id = box.dataset.panelId;
        const saved = state.panelLayout[id] || {};
        box.style.order = saved.order !== undefined ? saved.order : index;
        if (saved.width) box.style.width = saved.width;
        if (saved.height) box.style.height = saved.height;
        if (saved.free) {
            box.style.position = "absolute";
            box.style.left = saved.left || "0px";
            box.style.top = saved.top || "0px";
            box.style.zIndex = saved.zIndex || 2;
        }
        box.hidden = saved.hidden === true;
        box.draggable = false;
        if (!box.dataset.panelControlsReady) {
            box.addEventListener("pointerdown", (event) => handlePanelPointerDown(event, box));
            box.addEventListener("mouseup", () => savePanelSize(box));
            box.dataset.panelControlsReady = "true";
        }
        if (box.querySelector(".panel-tools")) return;
        const tools = document.createElement("div");
        tools.className = "panel-tools";
        tools.innerHTML = `
            <button type="button" data-panel-tool="drag" title="Drag panel" aria-label="Drag panel">&varr;</button>
            <button type="button" data-panel-tool="edit" title="Edit custom box" aria-label="Edit custom box">&#9998;</button>
            <button type="button" data-panel-tool="hide" title="Hide panel" aria-label="Hide panel">&times;</button>
        `;
        tools.querySelector("[data-panel-tool='drag']").addEventListener("pointerdown", (event) => {
            startPanelFreeDrag(event, box);
        });
        tools.addEventListener("click", (event) => {
            const tool = event.target.dataset.panelTool;
            if (!tool) return;
            event.stopPropagation();
            if (tool === "drag") {
                return;
            }
            if (tool === "edit" && box.dataset.customPanelId) {
                openCustomPanelDialog(box.dataset.customPanelId);
                return;
            }
            if (tool === "edit") {
                openBuiltInPanelDialog(box);
                return;
            }
            moveOrHidePanel(box, tool);
        });
        box.prepend(tools);
    });
}

function handlePanelPointerDown(event, box) {
    if (event.button !== 0) return;
    if (event.target.closest(".panel-tools, button, input, textarea, a, canvas, .terminal-output, .terminal-inline-form")) {
        return;
    }
    if (isResizeCorner(event, box)) return;
    startPanelFreeDrag(event, box);
}

function isResizeCorner(event, box) {
    const rect = box.getBoundingClientRect();
    return rect.right - event.clientX < 22 && rect.bottom - event.clientY < 22;
}

function moveOrHidePanel(box, tool) {
    const id = box.dataset.panelId;
    state.panelLayout[id] = state.panelLayout[id] || {};
    if (tool === "hide") {
        state.panelLayout[id].hidden = true;
        box.hidden = true;
        showToast("Panel hidden. Use Reset Layout to bring it back.", "info");
    }
    savePanelLayout();
}

function startPanelFreeDrag(event, box) {
    event.preventDefault();
    event.stopPropagation();

    const dashboard = document.querySelector(".dashboard");
    const dashboardRect = dashboard.getBoundingClientRect();
    const boxRect = box.getBoundingClientRect();
    const id = box.dataset.panelId;

    box.style.position = "absolute";
    box.style.left = `${boxRect.left - dashboardRect.left + dashboard.scrollLeft}px`;
    box.style.top = `${boxRect.top - dashboardRect.top + dashboard.scrollTop}px`;
    box.style.width = `${Math.round(boxRect.width)}px`;
    box.style.height = `${Math.round(boxRect.height)}px`;
    box.style.zIndex = nextPanelZIndex();
    box.classList.add("dragging");
    dashboard.classList.add("drag-active");

    state.activePanelDrag = {
        box,
        id,
        dashboard,
        offsetX: event.clientX - boxRect.left,
        offsetY: event.clientY - boxRect.top,
    };

    document.addEventListener("pointermove", movePanelFreely);
    document.addEventListener("pointerup", finishPanelFreeDrag, { once: true });
}

function nextPanelZIndex() {
    const values = Array.from(document.querySelectorAll(".dashboard-box"))
        .map((box) => Number(box.style.zIndex || 1))
        .filter(Number.isFinite);
    return Math.max(2, ...values) + 1;
}

function movePanelFreely(event) {
    if (!state.activePanelDrag) return;
    const { box, dashboard, offsetX, offsetY } = state.activePanelDrag;
    const dashboardRect = dashboard.getBoundingClientRect();
    const rect = box.getBoundingClientRect();
    const maxLeft = Math.max(0, dashboard.scrollWidth - rect.width);
    const maxTop = Math.max(0, dashboard.scrollHeight - rect.height);
    const left = Math.min(maxLeft, Math.max(0, event.clientX - dashboardRect.left + dashboard.scrollLeft - offsetX));
    const top = Math.min(maxTop, Math.max(0, event.clientY - dashboardRect.top + dashboard.scrollTop - offsetY));

    box.style.left = `${Math.round(left)}px`;
    box.style.top = `${Math.round(top)}px`;
    updatePanelCollisionEffect(box);
}

function finishPanelFreeDrag() {
    if (!state.activePanelDrag) return;
    const { box, id, dashboard } = state.activePanelDrag;
    const rect = box.getBoundingClientRect();
    state.panelLayout[id] = state.panelLayout[id] || {};
    state.panelLayout[id].free = true;
    state.panelLayout[id].left = box.style.left;
    state.panelLayout[id].top = box.style.top;
    state.panelLayout[id].width = `${Math.round(rect.width)}px`;
    state.panelLayout[id].height = `${Math.round(rect.height)}px`;
    state.panelLayout[id].zIndex = box.style.zIndex || 2;
    box.classList.remove("dragging");
    dashboard.classList.remove("drag-active");
    document.querySelectorAll(".drag-near").forEach((item) => item.classList.remove("drag-near"));
    document.removeEventListener("pointermove", movePanelFreely);
    state.activePanelDrag = null;
    savePanelLayout();
}

function updatePanelCollisionEffect(activeBox) {
    const activeRect = activeBox.getBoundingClientRect();
    document.querySelectorAll(".dashboard-box").forEach((box) => {
        if (box === activeBox || box.hidden) {
            box.classList.remove("drag-near");
            return;
        }
        const rect = box.getBoundingClientRect();
        const horizontalGap = Math.max(rect.left - activeRect.right, activeRect.left - rect.right, 0);
        const verticalGap = Math.max(rect.top - activeRect.bottom, activeRect.top - rect.bottom, 0);
        const near = Math.hypot(horizontalGap, verticalGap) < 34;
        box.classList.toggle("drag-near", near);
    });
}

function savePanelSize(box) {
    const id = box.dataset.panelId;
    const rect = box.getBoundingClientRect();
    state.panelLayout[id] = state.panelLayout[id] || {};
    if (rect.width > 0) state.panelLayout[id].width = `${Math.round(rect.width)}px`;
    if (rect.height > 0) state.panelLayout[id].height = `${Math.round(rect.height)}px`;
    savePanelLayout();
}

function resetPanelLayout() {
    state.panelLayout = {};
    state.panelOverrides = {};
    localStorage.removeItem("healthit.panelLayout");
    localStorage.removeItem("healthit.panelOverrides");
    document.querySelectorAll(".dashboard-box").forEach((box, index) => {
        box.hidden = false;
        box.style.order = index;
        box.style.width = "";
        box.style.height = "";
        box.style.position = "";
        box.style.left = "";
        box.style.top = "";
        box.style.zIndex = "";
        box.classList.remove("drag-near", "dragging");
    });
    showToast("Dashboard layout reset.", "success");
}

function renderCustomPanels() {
    const target = document.querySelector(".deep-grid");
    document.querySelectorAll("[data-custom-panel-id]").forEach((panel) => panel.remove());
    state.customPanels.forEach((panel) => {
        const article = document.createElement("article");
        article.className = "panel wide dashboard-box custom-dashboard-box";
        article.dataset.panelId = `custom-${panel.id}`;
        article.dataset.customPanelId = panel.id;
        article.innerHTML = `
            <div class="section-heading"><h2>${escapeHtml(panel.title)}</h2><span>custom</span></div>
            <div class="custom-panel-content">${panel.code || ""}</div>
        `;
        target.appendChild(article);
    });
    setupPanelControls();
}

function editablePanelHtml(box) {
    const clone = box.cloneNode(true);
    clone.querySelector(".panel-tools")?.remove();
    return clone.innerHTML.trim();
}

function applyPanelOverrides() {
    Object.entries(state.panelOverrides).forEach(([panelId, override]) => {
        const box = document.querySelector(`[data-panel-id="${CSS.escape(panelId)}"]`);
        if (!box) return;
        box.innerHTML = override.code || "";
    });
    setupPanelControls();
}

function openCustomPanelDialog(panelId = null) {
    state.editingCustomPanelId = panelId;
    state.editingBuiltInPanelId = null;
    const panel = state.customPanels.find((item) => item.id === panelId);
    els.customPanelTitle.value = panel?.title || "";
    els.customPanelCode.value = panel?.code || "";
    els.customPanelDialog.showModal();
}

function openBuiltInPanelDialog(box) {
    const panelId = box.dataset.panelId;
    state.editingCustomPanelId = null;
    state.editingBuiltInPanelId = panelId;
    const override = state.panelOverrides[panelId];
    const heading = box.querySelector(".section-heading h2") || box.querySelector(".metric-top span");
    els.customPanelTitle.value = override?.title || heading?.textContent || panelId;
    els.customPanelCode.value = override?.code || editablePanelHtml(box);
    els.customPanelDialog.showModal();
}

function saveCustomPanel(event) {
    event.preventDefault();
    const title = els.customPanelTitle.value.trim();
    if (!title) return;
    if (state.editingBuiltInPanelId) {
        state.panelOverrides[state.editingBuiltInPanelId] = {
            title,
            code: els.customPanelCode.value,
        };
        savePanelOverrides();
        state.editingBuiltInPanelId = null;
        els.customPanelDialog.close();
        applyPanelOverrides();
        showToast("Panel code saved.", "success");
        return;
    }
    if (state.editingCustomPanelId) {
        const panel = state.customPanels.find((item) => item.id === state.editingCustomPanelId);
        if (panel) {
            panel.title = title;
            panel.code = els.customPanelCode.value;
        }
    } else {
        state.customPanels.push({
            id: crypto.randomUUID(),
            title,
            code: els.customPanelCode.value,
        });
    }
    saveCustomPanels();
    els.customPanelDialog.close();
    renderCustomPanels();
    showToast("Custom box saved.", "success");
}

function activeTerminal() {
    return state.terminalSessions.find((session) => session.session_id === state.activeTerminalId);
}

function renderTerminalTabs() {
    els.terminalTabs.innerHTML = "";
    state.terminalSessions.forEach((session) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `terminal-tab ${session.session_id === state.activeTerminalId ? "active" : ""}`;
        button.textContent = session.name;
        button.title = "Click to focus. Double-click to rename.";
        button.addEventListener("click", () => {
            state.activeTerminalId = session.session_id;
            ensureVisible(session.session_id);
            renderTerminal();
        });
        button.addEventListener("dblclick", () => renameTerminalSession(session.session_id));
        els.terminalTabs.appendChild(button);
    });
}

function renderTerminal() {
    renderTerminalTabs();
    els.terminalWorkspace.innerHTML = "";
    const visibleSessions = state.visibleTerminalIds
        .map((id) => state.terminalSessions.find((session) => session.session_id === id))
        .filter(Boolean);
    if (!visibleSessions.length) {
        els.terminalWorkspace.textContent = "No terminal session.";
        return;
    }
    els.terminalWorkspace.style.gridTemplateColumns = `repeat(${visibleSessions.length}, minmax(0, 1fr))`;
    visibleSessions.forEach((session) => {
        const pane = document.createElement("section");
        pane.className = `terminal-pane ${session.session_id === state.activeTerminalId ? "active" : ""}`;
        pane.addEventListener("click", () => {
            state.activeTerminalId = session.session_id;
            renderTerminal();
        });
        const title = document.createElement("div");
        title.className = "terminal-pane-title";
        title.textContent = `${session.name} / ${session.cwd}`;
        pane.appendChild(title);
        const outputArea = document.createElement("div");
        outputArea.className = "terminal-output";
        session.history.forEach((entry) => {
            const block = document.createElement("div");
            block.className = "terminal-entry";
            if (entry.command) {
                const command = document.createElement("div");
                command.className = "terminal-line command";
                command.textContent = `${entry.cwd}> ${entry.command}`;
                block.appendChild(command);
            } else if (!entry.output) {
                const command = document.createElement("div");
                command.className = "terminal-line command blank";
                command.textContent = `${entry.cwd}>`;
                block.appendChild(command);
            }
            if (entry.output) {
                const output = document.createElement("pre");
                output.className = entry.exit_code === 0 ? "terminal-line output" : "terminal-line error";
                output.textContent = entry.output;
                block.appendChild(output);
            }
            outputArea.appendChild(block);
        });
        if (session.session_id === state.activeTerminalId) outputArea.appendChild(buildPromptForm(session));
        pane.appendChild(outputArea);
        els.terminalWorkspace.appendChild(pane);
        outputArea.scrollTop = outputArea.scrollHeight;
    });
    const activeInput = document.querySelector(".terminal-input");
    if (activeInput) {
        activeInput.focus();
        activeInput.scrollIntoView({ block: "nearest" });
    }
}

function buildPromptForm(session) {
    const form = document.createElement("form");
    form.className = "terminal-inline-form";
    form.innerHTML = `<span class="terminal-prompt">${session.cwd}&gt;</span><input class="terminal-input" type="text" autocomplete="off" spellcheck="false" placeholder="ssh user@host">`;
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        const input = form.querySelector("input");
        const command = input.value;
        input.value = "";
        runTerminalCommand(command);
    });
    return form;
}

function ensureVisible(sessionId) {
    if (!state.visibleTerminalIds.includes(sessionId)) state.visibleTerminalIds = [sessionId];
}

async function loadTerminalSessions() {
    const response = await fetch(`${API_BASE}/terminal/sessions`);
    if (!response.ok) throw new Error("Could not load terminal sessions.");
    const data = await response.json();
    state.terminalSessions = data.sessions || [];
    if (!state.activeTerminalId && state.terminalSessions.length) state.activeTerminalId = state.terminalSessions[0].session_id;
    if (!state.visibleTerminalIds.length && state.activeTerminalId) state.visibleTerminalIds = [state.activeTerminalId];
    renderTerminal();
}

async function createTerminalSession() {
    const response = await fetch(`${API_BASE}/terminal/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: `session-${state.terminalSessions.length + 1}`, machine_key: state.selectedKey }),
    });
    if (!response.ok) throw new Error("Could not create terminal session.");
    const session = await response.json();
    state.terminalSessions.push(session);
    state.activeTerminalId = session.session_id;
    state.visibleTerminalIds = [session.session_id];
    renderTerminal();
}

async function renameTerminalSession(sessionId = state.activeTerminalId) {
    const session = state.terminalSessions.find((item) => item.session_id === sessionId);
    if (!session) return;
    const nextName = window.prompt("Terminal name", session.name);
    if (!nextName || !nextName.trim()) return;
    const response = await fetch(`${API_BASE}/terminal/sessions/${encodeURIComponent(sessionId)}/rename`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nextName.trim() }),
    });
    if (!response.ok) return;
    const updated = await response.json();
    const index = state.terminalSessions.findIndex((item) => item.session_id === updated.session_id);
    if (index >= 0) state.terminalSessions[index] = updated;
    renderTerminal();
}

async function deleteTerminalSession(sessionId = state.activeTerminalId) {
    const session = state.terminalSessions.find((item) => item.session_id === sessionId);
    if (!session || !window.confirm(`Delete terminal "${session.name}"?`)) return;
    const response = await fetch(`${API_BASE}/terminal/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    if (!response.ok) return;
    state.terminalSessions = state.terminalSessions.filter((item) => item.session_id !== sessionId);
    state.visibleTerminalIds = state.visibleTerminalIds.filter((id) => id !== sessionId);
    if (state.activeTerminalId === sessionId) state.activeTerminalId = state.visibleTerminalIds[0] || state.terminalSessions[0]?.session_id || null;
    if (!state.visibleTerminalIds.length && state.activeTerminalId) state.visibleTerminalIds = [state.activeTerminalId];
    if (!state.terminalSessions.length) await createTerminalSession();
    else renderTerminal();
}

function splitTerminal() {
    const hidden = state.terminalSessions.find((session) => !state.visibleTerminalIds.includes(session.session_id));
    const nextId = hidden?.session_id || state.activeTerminalId;
    if (!nextId) return;
    if (!state.visibleTerminalIds.includes(nextId)) state.visibleTerminalIds.push(nextId);
    state.visibleTerminalIds = state.visibleTerminalIds.slice(-3);
    state.activeTerminalId = nextId;
    renderTerminal();
}

function focusTerminal() {
    if (state.activeTerminalId) {
        state.visibleTerminalIds = [state.activeTerminalId];
        renderTerminal();
    }
}

async function runTerminalCommand(command) {
    if (!state.activeTerminalId) return;
    els.terminalState.textContent = "running";
    try {
        const response = await fetch(`${API_BASE}/terminal/sessions/${encodeURIComponent(state.activeTerminalId)}/commands`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command: command.trim() }),
        });
        const session = await response.json();
        if (!response.ok) throw new Error(session.detail || `Command failed with ${response.status}`);
        const index = state.terminalSessions.findIndex((item) => item.session_id === session.session_id);
        if (index >= 0) state.terminalSessions[index] = session;
        else state.terminalSessions.push(session);
        state.activeTerminalId = session.session_id;
        els.terminalState.textContent = "ready";
        renderTerminal();
    } catch (error) {
        els.terminalState.textContent = "local";
        showToast("Terminal command could not run locally.", "warning");
    }
}

async function boot() {
    renderCustomPanels();
    setupPanelControls();
    applyPanelOverrides();
    syncLoginTypeFields();
    await loadDeployInfo();
    els.refreshButton.addEventListener("click", fetchMachines);
    els.resetLayoutButton.addEventListener("click", resetPanelLayout);
    els.addCustomPanelButton.addEventListener("click", () => openCustomPanelDialog());
    els.customPanelForm.addEventListener("submit", saveCustomPanel);
    els.cancelCustomPanelButton.addEventListener("click", () => els.customPanelDialog.close());
    els.machineSearch.addEventListener("input", (event) => {
        state.search = event.target.value;
        renderMachines();
    });
    els.newMachineLoginType.addEventListener("change", syncLoginTypeFields);
    els.newMachineHost.addEventListener("input", syncLoginTypeFields);
    els.retryDeployButton.addEventListener("click", () => els.addMachineForm.requestSubmit());
    document.querySelectorAll(".filter-button").forEach((button) => {
        button.addEventListener("click", () => {
            document.querySelectorAll(".filter-button").forEach((item) => item.classList.remove("active"));
            button.classList.add("active");
            state.filter = button.dataset.filter;
            renderMachines();
        });
    });
    els.addMachineForm.addEventListener("submit", registerMachine);
    els.newTerminalButton.addEventListener("click", createTerminalSession);
    els.renameTerminalButton.addEventListener("click", () => renameTerminalSession());
    els.deleteTerminalButton.addEventListener("click", () => deleteTerminalSession());
    els.splitTerminalButton.addEventListener("click", splitTerminal);
    els.focusTerminalButton.addEventListener("click", focusTerminal);

    await fetchMachines();
    await loadTerminalSessions();
    setInterval(fetchMachines, 5000);
}

boot().catch((error) => {
    els.fleetSummary.textContent = error.message;
});

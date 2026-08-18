const HealthITApi = (() => {
    const apiBase = window.location.protocol.startsWith("http")
        ? window.location.origin
        : "http://127.0.0.1:8000";

    function apiFetch(path, options = {}) {
        return fetch(`${apiBase}${path}`, options);
    }

    return { apiBase, apiFetch };
})();

window.HealthITApi = HealthITApi;

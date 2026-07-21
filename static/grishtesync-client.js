// static/grishtesync-client.js
// ============================================================
// GrishteSync API Client
// Full-featured client for the Flask backend (grishtesync-backend)
// ============================================================

// ------------------------------------------------------------
// 1. CONFIGURATION
// ------------------------------------------------------------
let API_BASE_URL = "https://grishtesync-backend.onrender.com";

/** Override the backend URL at runtime (e.g. for local dev / staging). */
export function setBaseUrl(url) {
    API_BASE_URL = url.replace(/\/$/, "");
}

export function getBaseUrl() {
    return API_BASE_URL;
}

const DEFAULT_TIMEOUT_MS = 30000;
const DEFAULT_RETRIES = 2;
const RETRYABLE_STATUS = new Set([408, 429, 500, 502, 503, 504]);

// ------------------------------------------------------------
// 2. ERROR TYPE
// ------------------------------------------------------------
export class GrishteSyncError extends Error {
    constructor(message, { status = null, endpoint = null, data = null } = {}) {
        super(message);
        this.name = "GrishteSyncError";
        this.status = status;
        this.endpoint = endpoint;
        this.data = data;
    }
}

// ------------------------------------------------------------
// 3. LIGHTWEIGHT EVENT BUS (for UI spinners / logging / metrics)
// ------------------------------------------------------------
const listeners = { start: [], end: [], error: [] };

export function on(event, callback) {
    if (!listeners[event]) throw new Error(`Unknown event "${event}"`);
    listeners[event].push(callback);
    return () => {
        listeners[event] = listeners[event].filter((cb) => cb !== callback);
    };
}

function emit(event, payload) {
    for (const cb of listeners[event] || []) {
        try {
            cb(payload);
        } catch (err) {
            console.error(`[grishtesync-client] listener for "${event}" threw:`, err);
        }
    }
}

// ------------------------------------------------------------
// 4. CORE REQUEST WRAPPER
//    - timeout via AbortController
//    - retry with exponential backoff on 429/5xx/network errors
//    - respects Retry-After header when present
//    - optional external AbortSignal for caller-initiated cancellation
// ------------------------------------------------------------
async function request(
    endpoint,
    {
        method = "GET",
        body = null,
        headers = {},
        token = null,
        timeoutMs = DEFAULT_TIMEOUT_MS,
        retries = DEFAULT_RETRIES,
        signal = null,
    } = {}
) {
    const url = `${API_BASE_URL}${endpoint}`;
    const finalHeaders = { "Content-Type": "application/json", ...headers };
    if (token) finalHeaders.Authorization = `Bearer ${token}`;

    let attempt = 0;
    let lastError;

    while (attempt <= retries) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

        // Chain an externally-provided signal so callers can cancel too
        const onExternalAbort = () => controller.abort();
        if (signal) signal.addEventListener("abort", onExternalAbort);

        emit("start", { endpoint, method, attempt });

        try {
            const response = await fetch(url, {
                method,
                headers: finalHeaders,
                body: body ? JSON.stringify(body) : null,
                signal: controller.signal,
            });

            clearTimeout(timeoutId);
            if (signal) signal.removeEventListener("abort", onExternalAbort);

            let data;
            try {
                data = await response.json();
            } catch {
                data = null;
            }

            if (!response.ok) {
                const message = data?.error || data?.message || `HTTP ${response.status}`;
                const err = new GrishteSyncError(message, { status: response.status, endpoint, data });

                if (RETRYABLE_STATUS.has(response.status) && attempt < retries) {
                    const retryAfter = Number(response.headers.get("Retry-After"));
                    const delay = retryAfter ? retryAfter * 1000 : backoffDelay(attempt);
                    await sleep(delay);
                    attempt++;
                    lastError = err;
                    continue;
                }
                emit("error", err);
                throw err;
            }

            emit("end", { endpoint, method, attempt });
            return data;
        } catch (error) {
            clearTimeout(timeoutId);
            if (signal) signal.removeEventListener("abort", onExternalAbort);

            if (error.name === "AbortError") {
                const isTimeout = !signal?.aborted;
                const err = new GrishteSyncError(
                    isTimeout ? `Request to ${endpoint} timed out after ${timeoutMs}ms` : "Request cancelled",
                    { endpoint }
                );
                emit("error", err);
                throw err;
            }

            if (error instanceof GrishteSyncError) throw error;

            // Network-level failure — retry if attempts remain
            if (attempt < retries) {
                await sleep(backoffDelay(attempt));
                attempt++;
                lastError = error;
                continue;
            }

            const err = new GrishteSyncError(error.message || "Network error", { endpoint });
            emit("error", err);
            throw err;
        }
    }

    throw lastError;
}

function backoffDelay(attempt) {
    const base = 500 * 2 ** attempt;
    const jitter = Math.random() * 200;
    return base + jitter;
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

// ------------------------------------------------------------
// 5. PUBLIC API METHODS (matches Flask routes)
// ------------------------------------------------------------

/** GET / — health check */
export async function healthCheck(opts = {}) {
    return request("/", opts);
}

/** GitHub OAuth login redirect URL */
export function getGitHubLoginUrl() {
    return `${API_BASE_URL}/auth/login`;
}

/**
 * Reads an auth token out of the current page URL (e.g. ?token=... after
 * an OAuth redirect), stores it, and strips it from the address bar.
 */
export function captureAuthTokenFromUrl(paramName = "token") {
    if (typeof window === "undefined") return null;
    const params = new URLSearchParams(window.location.search);
    const token = params.get(paramName);
    if (token) {
        setAuthToken(token);
        params.delete(paramName);
        const cleanUrl = `${window.location.pathname}${params.toString() ? `?${params}` : ""}${window.location.hash}`;
        window.history.replaceState({}, "", cleanUrl);
    }
    return token;
}

/** POST /api/generate — AI code generation */
export async function generateCode(prompt, repo = null, token = null, opts = {}) {
    if (!prompt || !prompt.trim()) throw new GrishteSyncError("prompt is required");
    return request("/api/generate", { method: "POST", body: { prompt, repo }, token, ...opts });
}

/** POST /api/deploy — deploy to GitHub */
export async function deployToGitHub(repo_name, files, version = "0.0.0", token, opts = {}) {
    validateFiles(files);
    if (!token) throw new GrishteSyncError("token is required to deploy to GitHub");
    return request("/api/deploy", { method: "POST", body: { repo_name, files, version }, token, ...opts });
}

/** POST /api/deploy-hf — deploy to Hugging Face Spaces */
export async function deployToHF(repo_full_name, files, options = {}, opts = {}) {
    validateFiles(files);
    const { space_name, sdk, token } = options;
    const body = { repo_full_name, files };
    if (space_name) body.space_name = space_name;
    if (sdk) body.sdk = sdk;
    if (token) body.token = token;
    return request("/api/deploy-hf", { method: "POST", body, ...opts });
}

/** POST /api/edit-selection — inline AI edit of a code selection */
export async function editSelection(instruction, selected_code, filename, all_files = {}, token = null, opts = {}) {
    if (!instruction || !instruction.trim()) throw new GrishteSyncError("instruction is required");
    if (!selected_code) throw new GrishteSyncError("selected_code is required");
    return request("/api/edit-selection", {
        method: "POST",
        body: { instruction, selected_code, filename, all_files },
        token,
        ...opts,
    });
}

/** POST /api/review — code review */
export async function reviewCode(files, token = null, opts = {}) {
    validateFiles(files);
    return request("/api/review", { method: "POST", body: { files }, token, ...opts });
}

/**
 * Convenience: review multiple independent file sets in parallel and
 * collect results/errors per set instead of failing the whole batch.
 */
export async function reviewCodeBatch(fileSets, token = null, opts = {}) {
    const results = await Promise.allSettled(fileSets.map((files) => reviewCode(files, token, opts)));
    return results.map((r, i) =>
        r.status === "fulfilled"
            ? { ok: true, files: fileSets[i], result: r.value }
            : { ok: false, files: fileSets[i], error: r.reason }
    );
}

function validateFiles(files) {
    if (!files || typeof files !== "object" || Array.isArray(files) || Object.keys(files).length === 0) {
        throw new GrishteSyncError("files must be a non-empty object of { filename: content }");
    }
}

// ------------------------------------------------------------
// 6. TOKEN HELPERS
//    NOTE: localStorage tokens are readable by any script on the page
//    (XSS risk). If this client is embedded alongside third-party JS,
//    prefer an httpOnly cookie issued by the backend instead.
// ------------------------------------------------------------
const TOKEN_KEY = "grishtesync_token";

export function setAuthToken(token) {
    if (typeof localStorage !== "undefined") localStorage.setItem(TOKEN_KEY, token);
}

export function getAuthToken() {
    return typeof localStorage !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
}

export function clearAuthToken() {
    if (typeof localStorage !== "undefined") localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated() {
    return Boolean(getAuthToken());
}

export function logout(redirectUrl = null) {
    clearAuthToken();
    if (redirectUrl && typeof window !== "undefined") window.location.href = redirectUrl;
}

// ------------------------------------------------------------
// 7. EXPOSE TO WINDOW (for non-module <script> tags)
// ------------------------------------------------------------
if (typeof window !== "undefined") {
    window.grishtesync = {
        setBaseUrl,
        getBaseUrl,
        GrishteSyncError,
        on,
        healthCheck,
        getGitHubLoginUrl,
        captureAuthTokenFromUrl,
        generateCode,
        deployToGitHub,
        deployToHF,
        editSelection,
        reviewCode,
        reviewCodeBatch,
        setAuthToken,
        getAuthToken,
        clearAuthToken,
        isAuthenticated,
        logout,
    };
}
 
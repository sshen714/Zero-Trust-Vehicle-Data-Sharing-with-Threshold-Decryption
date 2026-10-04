"use strict";

const API_BASE = "http://127.0.0.1:8000";
const TOKEN_KEY = "vehicle_access_token";
const message = document.getElementById("message");


function clearSession() {
    sessionStorage.removeItem(TOKEN_KEY);
}


async function apiRequest(path, options = {}) {
    let response;
    try {
        response = await fetch(`${API_BASE}${path}`, {
            ...options,
            cache: "no-store",
            signal: AbortSignal.timeout(10000),
        });
    } catch {
        throw new Error("無法連線至後端。請確認 FastAPI 已在 127.0.0.1:8000 啟動。");
    }

    const data = await response.json().catch(() => null);
    if (!response.ok) {
        const error = new Error(
            response.status === 401
                ? (path === "/auth/login"
                    ? "登入失敗。請輸入註冊時的 username（非 email）與原始密碼，並確認帳號已啟用。"
                    : "登入憑證無效或已過期，請重新登入。")
                : response.status === 403
                    ? "帳號已停權，或沒有存取權限。"
                    : response.status === 422
                        ? "輸入格式不正確，請檢查帳號與密碼。"
                        : "後端無法處理此請求，請稍後再試。"
        );
        error.status = response.status;
        throw error;
    }
    if (!data) throw new Error("後端回應格式不正確。");
    return data;
}


function authenticatedRequest(path, token, options = {}) {
    const headers = new Headers(options.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return apiRequest(path, {...options, headers});
}


async function loadWorkspace(workspace, token, expectedRole) {
    workspace.setAttribute("aria-busy", "true");
    message.textContent = "身分驗證成功，正在載入工作區資料…";

    try {
        const data = await authenticatedRequest("/workspace", token);
        if (
            typeof data.role !== "string"
            || typeof data.role_label !== "string"
            || typeof data.task !== "string"
            || data.role !== expectedRole
        ) {
            throw new Error("後端工作區資料格式不正確。");
        }

        workspace.dataset.loaded = "true";
        workspace.dispatchEvent(new CustomEvent("workspace:loaded", {
            detail: data,
        }));
        message.textContent = `後端工作區已連線：${data.role_label}－${data.task}`;
        return data;
    } finally {
        workspace.removeAttribute("aria-busy");
    }
}


function initializeLoginPage(form) {
    const button = form.querySelector("button");
    button.type = "submit";
    button.disabled = false;
    button.textContent = "登入";

    const wasSessionRejected = new URLSearchParams(location.search).get("reason") === "session";
    message.textContent = wasSessionRejected
        ? "登入憑證無效、已過期，或帳號已停權，請重新登入。"
        : "請輸入帳號與密碼。";

    if (sessionStorage.getItem(TOKEN_KEY)) {
        location.replace("index.html");
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        button.disabled = true;
        button.textContent = "登入中…";
        message.textContent = "正在驗證身分…";

        try {
            clearSession();
            const body = new URLSearchParams({
                username: form.elements.username.value.trim(),
                password: form.elements.password.value,
            });
            const result = await apiRequest("/auth/login", {
                method: "POST",
                body,
            });
            if (typeof result.access_token !== "string" || !result.access_token) {
                throw new Error("後端未回傳有效登入憑證。");
            }
            sessionStorage.setItem(TOKEN_KEY, result.access_token);
            location.replace("index.html");
        } catch (error) {
            clearSession();
            message.textContent = error.message;
        } finally {
            form.elements.password.value = "";
            button.disabled = false;
            button.textContent = "登入";
        }
    });
}


async function initializeProfilePage(profile) {
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (!token) {
        location.replace("login.html");
        return;
    }

    document.getElementById("logout")?.addEventListener("click", () => {
        clearSession();
        location.replace("login.html");
    });

    try {
        // Account and role come from /auth/me after backend validation.
        const user = await authenticatedRequest("/auth/me", token);
        if (typeof user.username !== "string" || typeof user.role !== "string") {
            throw new Error("後端使用者資料格式不正確。");
        }
        const destination = Object.hasOwn(ROLE_PAGES, user.role) ? ROLE_PAGES[user.role] : null;
        if (!destination) throw new Error('尚未支援此身份。');
        if (!profile || document.body.dataset.role !== user.role) {
            location.replace(destination.page);
            return;
        }
        document.getElementById("current-username").textContent = user.username;
        document.getElementById("current-role").textContent = destination.label;
        profile.hidden = false;
        const workspace = document.getElementById("workspace");
        workspace.hidden = false;
        document.querySelectorAll('[data-preview]').forEach(button => {
            button.addEventListener('click', () => {
                message.textContent = `「${button.textContent}」目前僅展示操作介面，未查詢或送出資料。`;
            });
        });
        await loadWorkspace(workspace, token, user.role);
    } catch (error) {
        if (error.status === 401 || error.status === 403) {
            clearSession();
            location.replace("login.html?reason=session");
            return;
        }
        message.textContent = error.message;
    }
}


const ROLE_PAGES = {
    owner: {page:'owner.html', label:'車主'},
    visitor: {page:'visitor.html', label:'訪客'},
    vendor: {page:'vendor.html', label:'合作廠商'},
    supervisor_a: {page:'supervisor_a.html', label:'主管 A'},
    supervisor_b: {page:'supervisor_b.html', label:'主管 B'},
    admin: {page:'admin.html', label:'系統管理者'},
    researcher: {page:'researcher.html', label:'交通研究者'},
    police: {page:'police.html', label:'警方'},
};

const loginForm = document.getElementById('login-form');
const profile = document.getElementById('profile');
if (loginForm) initializeLoginPage(loginForm);
if (profile || document.getElementById('role-router')) initializeProfilePage(profile);

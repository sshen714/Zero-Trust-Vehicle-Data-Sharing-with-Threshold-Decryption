"use strict";

// 本機開發用 API 位址；後端將在後續步驟建立。
const API_BASE = "http://127.0.0.1:8000";
const TOKEN_KEY = "vehicle_access_token";
const form = document.getElementById("login-form");
const button = form.querySelector("button");
const message = document.getElementById("message");
const profile = document.getElementById("profile");
const logoutButton = document.getElementById("logout");

function clearSession() {
    sessionStorage.removeItem(TOKEN_KEY);
    profile.hidden = true;
    document.getElementById("current-username").textContent = "";
    document.getElementById("current-role").textContent = "";
    form.hidden = false;
}

async function request(path, options = {}) {
    let response;
    try {
        response = await fetch(`${API_BASE}${path}`, {
            ...options,
            cache: "no-store",
            signal: AbortSignal.timeout(10000),
        });
    } catch {
        throw new Error("無法連線至後端。請確認 FastAPI 已啟動，且允許此前端來源連線。");
    }

    const data = await response.json().catch(() => null);
    if (!response.ok) {
        if (response.status === 401) {
            throw new Error("帳號或密碼錯誤，或登入憑證已過期。");
        }
        if (response.status === 403) {
            throw new Error("帳號已停權，或沒有存取權限。");
        }
        if (response.status === 422) {
            throw new Error("輸入格式不正確，請檢查帳號與密碼。");
        }
        throw new Error("後端無法處理此請求，請稍後再試。");
    }
    if (!data) throw new Error("後端回應格式不正確。");
    return data;
}

async function loadProfile(token) {
    // 帳號與角色由後端驗證並提供，不從前端輸入或 JWT 自行判定。
    const user = await request("/auth/me", {
        headers: { Authorization: `Bearer ${token}` },
    });
    if (typeof user.username !== "string" || typeof user.role !== "string") {
        throw new Error("後端使用者資料格式不正確。");
    }
    document.getElementById("current-username").textContent = user.username;
    document.getElementById("current-role").textContent = user.role;
    form.hidden = true;
    profile.hidden = false;
    message.textContent = "登入成功，身分已由後端驗證。";
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
        const result = await request("/auth/login", { method: "POST", body });
        if (typeof result.access_token !== "string" || !result.access_token) {
            throw new Error("後端未回傳有效登入憑證。");
        }
        sessionStorage.setItem(TOKEN_KEY, result.access_token);
        await loadProfile(result.access_token);
    } catch (error) {
        clearSession();
        message.textContent = error.message;
    } finally {
        form.elements.password.value = "";
        button.disabled = false;
        button.textContent = "登入";
    }
});

logoutButton.addEventListener("click", () => {
    clearSession();
    message.textContent = "已清除本分頁的登入憑證。";
    form.elements.username.focus();
});

async function initialize() {
    button.type = "submit";
    button.disabled = false;
    button.textContent = "登入";
    message.textContent = "請登入。後端尚未建立時，送出會顯示連線提示。";
    try {
        const token = sessionStorage.getItem(TOKEN_KEY);
        if (token) await loadProfile(token);
    } catch (error) {
        try { clearSession(); } catch { /* 瀏覽器可能禁止儲存存取。 */ }
        message.textContent = error.message;
    }
}

initialize();

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
                ? "帳號或密碼錯誤，或登入憑證已過期。"
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

    document.getElementById("logout").addEventListener("click", () => {
        clearSession();
        location.replace("login.html");
    });

    try {
        // Account and role come from /auth/me after backend validation.
        const user = await apiRequest("/auth/me", {
            headers: { Authorization: `Bearer ${token}` },
        });
        if (typeof user.username !== "string" || typeof user.role !== "string") {
            throw new Error("後端使用者資料格式不正確。");
        }
        document.getElementById("current-username").textContent = user.username;
        document.getElementById("current-role").textContent = user.role;
        profile.hidden = false;
        message.textContent = "身分與角色已由後端驗證。";
    } catch (error) {
        if (error.status === 401 || error.status === 403) {
            clearSession();
            location.replace("login.html?reason=session");
            return;
        }
        message.textContent = error.message;
    }
}


const loginForm = document.getElementById("login-form");
const profile = document.getElementById("profile");

if (loginForm) initializeLoginPage(loginForm);
if (profile) initializeProfilePage(profile);

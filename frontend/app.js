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
        bindWorkspace(token);
        await loadWorkspace(token);
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

const ROLE_LABELS = {owner: '車主', visitor: '訪客', vendor: '合作廠商', supervisor_a: '主管 A', supervisor_b: '主管 B', admin: '系統管理者'};
const FIELD_LABELS = {vehicle_id:'車輛', recorded_at:'紀錄時間', lat:'緯度', lng:'經度', speed_kmh:'時速', is_demo:'模擬資料', record_count:'紀錄數', average_speed_kmh:'平均時速', slow_record_count:'低速紀錄數', demo_record_count:'模擬紀錄數', id:'編號', vendor_id:'申請者編號', purpose:'使用目的', decision_a:'主管 A', decision_b:'主管 B', status:'狀態', created_at:'建立時間', username:'帳號', role:'角色', is_active:'已啟用', user_count:'帳號數', vehicle_record_count:'車輛紀錄數', request_count:'申請數', date:'日期'};
const STATES = {pending:'待審核', approved:'已核准', rejected:'已拒絕'};

function renderTable(container, title, rows) {
    const heading = document.createElement('h3');
    heading.textContent = title;
    container.append(heading);
    if (!rows.length) {
        const empty = document.createElement('p');
        empty.textContent = '目前沒有資料。';
        container.append(empty);
        return;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'table-scroll';
    const table = document.createElement('table');
    const keys = Object.keys(rows[0]);
    const head = document.createElement('tr');
    for (const key of keys) {
        const cell = document.createElement('th');
        cell.scope = 'col';
        cell.textContent = FIELD_LABELS[key] || key;
        head.append(cell);
    }
    const thead = document.createElement('thead');
    thead.append(head);
    table.append(thead);
    const body = document.createElement('tbody');
    for (const row of rows) {
        const tr = document.createElement('tr');
        for (const key of keys) {
            const td = document.createElement('td');
            const value = row[key];
            td.textContent = typeof value === 'boolean' ? (value ? '是' : '否') : (STATES[value] || ROLE_LABELS[value] || (value ?? '尚無資料'));
            tr.append(td);
        }
        body.append(tr);
    }
    table.append(body);
    wrapper.append(table);
    container.append(wrapper);
}

async function loadWorkspace(token) {
    const data = await apiRequest('/workspace', {headers:{Authorization:`Bearer ${token}`}});
    document.getElementById('current-role').textContent = data.role_label;
    document.getElementById('workspace-title').textContent = `${data.role_label}工作區`;
    document.getElementById('workspace-task').textContent = data.task;
    const container = document.getElementById('workspace-data');
    container.replaceChildren();
    if (data.records) renderTable(container, '我的車輛紀錄（最近 100 筆）', data.records);
    if (data.traffic) renderTable(container, '交通概況（不含個別車輛位置）', [data.traffic]);
    if (data.requests) renderTable(container, '資料申請（最近 100 筆）', data.requests);
    if (data.analysis) {
        renderTable(container, '核准後的交通分析', [data.analysis]);
        renderTable(container, '每日交通分析（最近 30 日）', data.daily_analysis);
    } else if (data.role === 'vendor') {
        const note = document.createElement('p');
        note.textContent = '申請經主管 A 與主管 B 分別核准後，才能查看交通分析。';
        container.append(note);
    }
    if (data.service) renderTable(container, '服務統計', [data.service]);
    if (data.users) renderTable(container, '帳號管理清單（前 100 筆）', data.users);
    document.getElementById('request-form').hidden = data.role !== 'vendor';
    document.getElementById('record-form').hidden = data.role !== 'owner';
    if (data.role === 'supervisor_a' || data.role === 'supervisor_b') {
        const field = data.role === 'supervisor_a' ? 'decision_a' : 'decision_b';
        for (const request of data.requests.filter(r => r[field] === 'pending')) {
            const group = document.createElement('p');
            group.textContent = `申請 #${request.id}：`;
            for (const decision of ['approved', 'rejected']) {
                const button = document.createElement('button');
                button.type = 'button';
                button.textContent = STATES[decision];
                button.addEventListener('click', () => workspaceAction(token, button, `/workspace/requests/${request.id}/decision`, {decision}));
                group.append(button);
            }
            container.append(group);
        }
    }
    document.getElementById('workspace').hidden = false;
}

async function workspaceAction(token, button, path, body) {
    button.disabled = true;
    try {
        await apiRequest(path, {method:'POST', headers:{Authorization:`Bearer ${token}`, 'Content-Type':'application/json'}, body:JSON.stringify(body)});
        await loadWorkspace(token);
        message.textContent = '資料已更新。';
    } catch (error) {
        handleWorkspaceError(error);
    } finally {
        button.disabled = false;
    }
}

function handleWorkspaceError(error) {
    if (error.status === 401 || error.status === 403) {
        document.getElementById('workspace').hidden = true;
    }
    if (error.status === 401) {
        clearSession();
        location.replace('login.html?reason=session');
    }
    message.textContent = error.message;
}

function bindWorkspace(token) {
    document.getElementById('refresh-workspace').addEventListener('click', () => loadWorkspace(token).catch(handleWorkspaceError));
    document.getElementById('request-form').addEventListener('submit', event => {
        event.preventDefault();
        const form = event.currentTarget;
        workspaceAction(token, form.querySelector('button'), '/workspace/requests', {purpose:form.elements.purpose.value.trim()});
    });
    document.getElementById('record-form').addEventListener('submit', event => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = Object.fromEntries(new FormData(form));
        for (const key of ['lat', 'lng', 'speed_kmh']) data[key] = Number(data[key]);
        workspaceAction(token, form.querySelector('button'), '/workspace/records', data);
    });
}

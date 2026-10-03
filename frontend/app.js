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
        renderRoleWorkspace(user.role);
        message.textContent = "登入身分已驗證；工作區目前為介面展示。";
    } catch (error) {
        if (error.status === 401 || error.status === 403) {
            clearSession();
            location.replace("login.html?reason=session");
            return;
        }
        message.textContent = error.message;
    }
}


const ROLE_SCREENS = {
    owner: {
        label: '車主', task: '查詢自己的車牌資料',
        access: ['只能查詢本人綁定的車牌'],
        sections: [
            {title:'我的車牌資料', description:'車牌由本人綁定資料帶入，不能輸入其他車牌。', fields:['車牌'], readonlyFields:['車牌'], action:'查詢我的資料', resultPlaceholder:'查詢結果將顯示於此。'},
        ],
    },
    visitor: {
        label:'訪客', task:'查看交通概況',
        access:['只提供彙總交通統計', '時間區間化', '不提供個別車輛位置或速度'],
        sections:[
            {title:'交通概況', description:'依時間區間查看車流量、平均速度及壅塞程度。', fields:['開始時間','結束時間'], action:'查看交通概況'},
        ], metrics:['車流量','平均速度','壅塞程度'],
    },
    vendor: {
        label:'合作廠商', task:'分析核准範圍內的車輛或事故資料',
        access:['依核准車輛與時間範圍查詢', '時間與速度精準', '位置預設模糊；主管 A OTP 解鎖'],
        sections:[
            {title:'資料使用申請', description:'說明使用目的及所需的車輛、時間範圍。', fields:['使用目的','車輛','開始時間','結束時間'], action:'送出申請'},
            {title:'核准資料分析', description:'查看核准範圍內的資料，並申請精準位置。', fields:['車輛','開始時間','結束時間'], action:'查看分析', extra:'申請主管 A OTP'},
        ],
    },
    supervisor_a: {
        label:'主管 A', task:'精準位置資料的審核者',
        access:['依車牌與時間查詢', '時間與位置精準', '速度預設模糊；主管 B OTP 解鎖'],
        sections:[
            {title:'位置資料審核', description:'查看資料使用目的，核准或拒絕位置資料申請。', action:'查看待審申請', extra:'核准／拒絕'},
            {title:'位置資料查詢', description:'依車牌及時間查看位置資料。', fields:['車牌','開始時間','結束時間'], action:'查詢位置', extra:'申請主管 B OTP'},
        ],
    },
    supervisor_b: {
        label:'主管 B', task:'精準速度資料的審核者',
        access:['依車牌與時間查詢', '時間與速度精準', '位置預設模糊；主管 A OTP 解鎖'],
        sections:[
            {title:'速度資料審核', description:'獨立核准或拒絕速度資料申請。', action:'查看待審申請', extra:'核准／拒絕'},
            {title:'速度資料查詢', description:'依車牌及時間查看速度資料。', fields:['車牌','開始時間','結束時間'], action:'查詢速度', extra:'申請主管 A OTP'},
        ],
    },
    admin: {
        label:'系統管理者', task:'維護帳號、網站、API、資料庫與日誌',
        access:['可依車牌、時間、位置與速度查詢', '位置與速度預設模糊', 'A OTP 解鎖位置；B OTP 解鎖速度'],
        sections:[
            {title:'帳號管理', description:'查看帳號、身份與啟用狀態。', fields:['帳號'], action:'查看帳號'},
            {title:'服務與日誌', description:'查看網站、API 及資料庫運作狀態。', action:'查看服務日誌'},
            {title:'資料查詢', description:'依條件查看資料並申請精準欄位。', fields:['車牌','開始時間','結束時間','位置','速度'], action:'查詢資料', extra:'申請 OTP'},
        ], metrics:['網站狀態','API 狀態','資料庫狀態'],
    },
    researcher: {
        label:'交通研究者', task:'研究車流與交通行為',
        access:['只能依時間查詢', '時間粗化、位置與速度模糊', '車牌假名化，使用完整 PETs'],
        sections:[
            {title:'研究資料', description:'取得經隱私處理的研究資料，不提供指定車牌查詢。', fields:['開始時間','結束時間'], action:'查看研究資料'},
        ],
    },
    police: {
        label:'警方', task:'肇逃、事故案件調查',
        access:['依案件查詢指定車牌、時間與位置', '時間精準，位置與速度預設模糊', 'Email OTP 驗證後依案件授權解鎖'],
        sections:[
            {title:'案件資料查詢', description:'填寫案件編號與查詢條件。', fields:['案件編號','車牌','開始時間','結束時間','位置'], action:'查詢案件'},
            {title:'案件授權驗證', description:'驗證 Email OTP 後查看案件授權欄位。', fields:['案件編號','Email OTP'], action:'驗證 OTP', extra:'申請 Email OTP'},
        ],
    },
};

function element(tag, content, className) {
    const node = document.createElement(tag);
    if (content) node.textContent = content;
    if (className) node.className = className;
    return node;
}

function previewButton(label) {
    const button = element('button', label);
    button.type = 'button';
    button.addEventListener('click', () => {
        message.textContent = `「${label}」目前僅展示操作介面，未查詢或送出資料。`;
    });
    return button;
}

function renderRoleWorkspace(role) {
    const screen = ROLE_SCREENS[role];
    if (!screen) throw new Error('尚未支援此身份。');
    document.getElementById('current-role').textContent = screen.label;
    document.getElementById('workspace-title').textContent = `${screen.label}工作區`;
    document.getElementById('workspace-task').textContent = screen.task;
    const container = document.getElementById('workspace-data');
    container.replaceChildren();
    const access = element('ul', '', 'access-list');
    for (const item of screen.access) access.append(element('li', item));
    container.append(access);
    if (screen.metrics) {
        const metrics = element('div', '', 'metric-grid');
        for (const title of screen.metrics) {
            const card = element('div', '', 'metric-card');
            card.append(element('span', title), element('strong', '—'), element('small', '尚未載入資料'));
            metrics.append(card);
        }
        container.append(metrics);
    }
    const grid = element('div', '', 'role-grid');
    for (const section of screen.sections) {
        const card = element('section', '', 'feature-card');
        card.append(element('h3', section.title), element('p', section.description));
        for (const field of section.fields || []) {
            const label = element('label', field);
            const input = document.createElement('input');
            input.type = field.includes('時間') ? 'datetime-local' : field === '資料檔案' ? 'file' : 'text';
            if (input.type === 'text') input.placeholder = `請輸入${field}`;
            if ((section.readonlyFields || []).includes(field)) {
                input.readOnly = true;
                input.placeholder = '尚未載入本人車牌';
            }
            label.append(input);
            card.append(label);
        }
        const actions = element('div', '', 'preview-actions');
        actions.append(previewButton(section.action));
        if (section.extra) actions.append(previewButton(section.extra));
        card.append(actions);
        if (section.resultPlaceholder) {
            card.append(element('p', section.resultPlaceholder, 'query-placeholder'));
        }
        grid.append(card);
    }
    container.append(grid);
    document.getElementById('workspace').hidden = false;
}

const loginForm = document.getElementById('login-form');
const profile = document.getElementById('profile');
if (loginForm) initializeLoginPage(loginForm);
if (profile) initializeProfilePage(profile);

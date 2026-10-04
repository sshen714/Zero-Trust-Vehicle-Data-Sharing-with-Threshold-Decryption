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
                    : response.status === 404 && data?.detail === "Vehicle is not available"
                        ? "找不到此車輛，請確認車輛代碼是否完整且正確。"
                    : response.status === 404 && data?.detail === "No trajectories available"
                        ? "此車牌在所選條件下沒有可下載的資料，請調整查詢條件。"
                    : response.status === 422
                        ? (path === "/auth/login"
                            ? "輸入格式不正確，請檢查帳號與密碼。"
                            : "輸入格式不正確，請檢查查詢條件。")
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


async function authenticatedDownload(path, token) {
    let response;
    try {
        response = await fetch(`${API_BASE}${path}`, {
            headers: {Authorization: `Bearer ${token}`},
            cache: "no-store",
            signal: AbortSignal.timeout(30000),
        });
    } catch {
        throw new Error("無法連線至後端，或下載等待時間過長。");
    }

    if (!response.ok) {
        const data = await response.json().catch(() => null);
        const error = new Error(
            response.status === 401
                ? "登入憑證無效或已過期，請重新登入。"
                : response.status === 403
                    ? "此車牌未綁定至目前帳號。"
                    : data?.detail === "Vehicle is not available"
                        ? "找不到此車輛，請確認車輛代碼是否完整且正確。"
                    : data?.detail === "No trajectories available"
                        ? "此車牌在所選條件下沒有可下載的資料，請調整查詢條件。"
                    : (typeof data?.detail === "string"
                        ? data.detail
                        : "後端無法產生 CSV，請稍後再試。")
        );
        error.status = response.status;
        throw error;
    }
    return response.blob();
}


async function authenticatedPostDownload(path, token, body) {
    let response;
    try {
        response = await fetch(`${API_BASE}${path}`, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${token}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify(body),
            cache: "no-store",
            signal: AbortSignal.timeout(30000),
        });
    } catch {
        throw new Error("無法連線至後端，或下載等待時間過長。");
    }

    if (!response.ok) {
        const data = await response.json().catch(() => null);
        const error = new Error(
            data?.detail === "No trajectories available"
                ? "此車牌在所選條件下沒有可下載的資料，請調整查詢條件。"
                : typeof data?.detail === "string"
                ? data.detail
                : "後端無法驗證 OTP 或產生 CSV。"
        );
        error.status = response.status;
        throw error;
    }
    return response.blob();
}


async function requestPersonalDownloadOtp(token, payload, filename, buttons) {
    buttons.forEach(button => { button.disabled = true; });
    message.textContent = "正在建立本人下載 OTP…";
    try {
        const request = await authenticatedRequest(
            "/workspace/personal-download-requests",
            token,
            {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload),
            },
        );
        const container = buttons[0].closest(".feature-card") || buttons[0].parentElement;
        container.querySelector("[data-personal-download-otp]")?.remove();
        const otpPanel = document.createElement("div");
        otpPanel.className = "otp-entry";
        otpPanel.dataset.personalDownloadOtp = "";
        const label = document.createElement("label");
        label.textContent = "本人下載 OTP";
        const input = document.createElement("input");
        input.type = "text";
        input.inputMode = "numeric";
        input.maxLength = 6;
        input.autocomplete = "one-time-code";
        input.placeholder = "請輸入 6 位數 OTP";
        const verifyButton = document.createElement("button");
        verifyButton.type = "button";
        verifyButton.textContent = "驗證並下載";
        otpPanel.append(label, input, verifyButton);
        buttons[0].closest(".preview-actions")?.after(otpPanel);
        buttons.forEach(button => { button.hidden = true; });
        input.addEventListener("input", () => {
            input.value = input.value.replace(/\D/g, "").slice(0, 6);
        });
        verifyButton.addEventListener("click", async () => {
            if (!/^\d{6}$/.test(input.value)) {
                message.textContent = "請輸入完整的 6 位數本人下載 OTP。";
                return;
            }
            input.disabled = true;
            verifyButton.disabled = true;
            message.textContent = "正在驗證本人 OTP 並產生 CSV…";
            try {
                const blob = await authenticatedPostDownload(
                    `/workspace/personal-download-requests/${request.request_id}/verify-otp`,
                    token,
                    {...payload, otp: input.value},
                );
                const url = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.href = url;
                link.download = filename;
                document.body.appendChild(link);
                link.click();
                link.remove();
                URL.revokeObjectURL(url);
                verifyButton.hidden = true;
                message.textContent = "本人 OTP 驗證成功，CSV 已下載。";
            } catch (error) {
                if (error.status === 401) {
                    clearSession();
                    location.replace("login.html?reason=session");
                    return;
                }
                if ([404, 409, 410, 429].includes(error.status)) {
                    otpPanel.remove();
                    buttons.forEach(button => {
                        button.hidden = false;
                        button.disabled = false;
                    });
                } else {
                    input.disabled = false;
                    verifyButton.disabled = false;
                    input.focus();
                }
                const messages = {
                    404: "找不到申請或資料，請重新送出下載申請。",
                    410: "OTP 已過期，請重新送出下載申請。",
                    422: "OTP 不正確，請重新輸入。",
                    429: "OTP 錯誤次數已達上限，請重新送出下載申請。",
                };
                message.textContent = messages[error.status] || error.message;
            }
        });
        input.focus();
        message.textContent = request.delivery === "email"
            ? `驗證碼已寄至 ${request.recipient_email}，請於 5 分鐘內輸入。`
            : `Demo OTP：${request.demo_otp}（寄送對象：${request.recipient_email}，5 分鐘內有效）`;
    } catch (error) {
        if (error.status === 401) {
            clearSession();
            location.replace("login.html?reason=session");
            return;
        }
        buttons.forEach(button => { button.disabled = false; });
        message.textContent = error.message;
    }
}


function displayDateTime(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(value);
    if (!match) return value;
    return `${match[1]}/${match[2]}/${match[3]} ${match[4]}:${match[5]}:${match[6]}`;
}


function initializeOwnerWorkspace(token, workspaceData) {
    const plateInput = document.getElementById("owner-plate");
    const startInput = document.getElementById("owner-start");
    const endInput = document.getElementById("owner-end");
    const rangeText = document.getElementById("owner-available-range");
    const buttons = [...document.querySelectorAll("[data-owner-export]")];
    if (!plateInput || !startInput || !endInput || !rangeText || !buttons.length) return;

    const availableRange = workspaceData.available_time_range;
    if (
        availableRange
        && typeof availableRange.start === "string"
        && typeof availableRange.end === "string"
    ) {
        const rangeStart = availableRange.start.slice(0, 19);
        const rangeEnd = availableRange.end.slice(0, 19);
        startInput.min = rangeStart;
        startInput.max = rangeEnd;
        startInput.value = rangeStart;
        endInput.min = rangeStart;
        endInput.max = rangeEnd;
        endInput.value = rangeEnd;
        rangeText.textContent = `可查詢時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
    } else {
        rangeText.textContent = "目前沒有可查詢的模擬資料。";
        buttons.forEach((item) => { item.disabled = true; });
    }

    buttons.forEach((button) => {
        button.addEventListener("click", async () => {
            const plate = plateInput.value.trim();
            if (!plate) {
                message.textContent = "請先輸入車牌。";
                plateInput.focus();
                return;
            }
            if (!startInput.value || !endInput.value) {
                message.textContent = "請選擇開始時間與結束時間。";
                return;
            }
            if (startInput.value > endInput.value) {
                message.textContent = "開始時間不能晚於結束時間。";
                startInput.focus();
                return;
            }

            const dataType = button.dataset.ownerExport;
            await requestPersonalDownloadOtp(token, {
                data_type: dataType,
                plate,
                start: startInput.value,
                end: endInput.value,
                min_speed: null,
                max_speed: null,
            }, `owner-${dataType}-trajectories.csv`, buttons);
        });
    });
}


function initializeVendorWorkspace(token, workspaceData) {
    const purposeInput = document.getElementById("vendor-0-0");
    const requestVehicleInput = document.getElementById("vendor-0-1");
    const requestStartInput = document.getElementById("vendor-0-2");
    const requestEndInput = document.getElementById("vendor-0-3");
    const requestRangeText = document.getElementById("vendor-request-available-range");
    const requestButton = document.getElementById("vendor-request-submit");
    const otpEntry = document.getElementById("vendor-otp-entry");
    const otpInput = document.getElementById("vendor-otp-code");
    const otpButton = document.getElementById("vendor-otp-submit");
    const plateInput = document.getElementById("vendor-plate");
    const startInput = document.getElementById("vendor-start");
    const endInput = document.getElementById("vendor-end");
    const rangeText = document.getElementById("vendor-available-range");
    const buttons = [...document.querySelectorAll("[data-vendor-export]")];
    if (
        !purposeInput || !requestVehicleInput || !requestStartInput || !requestEndInput
        || !requestRangeText || !requestButton || !otpEntry || !otpInput || !otpButton
        || !plateInput || !startInput || !endInput || !rangeText || !buttons.length
    ) return;

    if (
        purposeInput && requestVehicleInput && requestStartInput && requestEndInput
        && requestRangeText
        && requestButton && otpEntry && otpInput && otpButton
    ) {
        let requestId = null;
        otpInput.addEventListener("input", () => {
            otpInput.value = otpInput.value.replace(/\D/g, "").slice(0, 6);
        });
        requestButton.addEventListener("click", async () => {
            if (!purposeInput.value.trim() || !requestVehicleInput.value.trim()) {
                message.textContent = "請填寫使用目的與車輛。";
                return;
            }
            if (!requestStartInput.value || !requestEndInput.value) {
                message.textContent = "請選擇申請的開始時間與結束時間。";
                return;
            }
            if (requestStartInput.value > requestEndInput.value) {
                message.textContent = "申請的開始時間不能晚於結束時間。";
                return;
            }
            requestButton.disabled = true;
            message.textContent = "正在建立精準位置申請與 Demo OTP…";
            try {
                const result = await authenticatedRequest(
                    "/workspace/vendor/location-requests",
                    token,
                    {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({
                            purpose: purposeInput.value.trim(),
                            plate: requestVehicleInput.value.trim(),
                            start: requestStartInput.value,
                            end: requestEndInput.value,
                        }),
                    },
                );
                requestId = result.request_id;
                requestButton.hidden = true;
                otpEntry.hidden = false;
                otpInput.focus();
                message.textContent = `Demo OTP：${result.demo_otp}（5 分鐘內有效）`;
            } catch (error) {
                if (error.status === 401) {
                    clearSession();
                    location.replace("login.html?reason=session");
                    return;
                }
                message.textContent = error.message;
            } finally {
                requestButton.disabled = false;
            }
        });
        otpButton.addEventListener("click", async () => {
            if (!Number.isInteger(requestId)) {
                message.textContent = "請先送出申請。";
                return;
            }
            if (!/^\d{6}$/.test(otpInput.value)) {
                message.textContent = "請輸入完整的 6 位數 OTP。";
                return;
            }
            otpButton.disabled = true;
            message.textContent = "正在驗證 OTP…";
            try {
                const blob = await authenticatedPostDownload(
                    `/workspace/vendor/location-requests/${requestId}/verify-otp`,
                    token,
                    {
                        otp: otpInput.value,
                        plate: requestVehicleInput.value.trim(),
                        start: requestStartInput.value,
                        end: requestEndInput.value,
                    },
                );
                const url = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.href = url;
                link.download = "vendor-authorized-locations.csv";
                document.body.appendChild(link);
                link.click();
                link.remove();
                URL.revokeObjectURL(url);
                otpInput.disabled = true;
                otpButton.hidden = true;
                message.textContent = "OTP 驗證成功，精準位置 CSV 已下載。";
            } catch (error) {
                if (error.status === 401) {
                    clearSession();
                    location.replace("login.html?reason=session");
                    return;
                }
                message.textContent = error.message;
            } finally {
                otpButton.disabled = false;
            }
        });
    }

    const availableRange = workspaceData.available_time_range;
    if (availableRange?.start && availableRange?.end) {
        const rangeStart = availableRange.start.slice(0, 19);
        const rangeEnd = availableRange.end.slice(0, 19);
        for (const input of [requestStartInput, requestEndInput, startInput, endInput]) {
            input.min = rangeStart;
            input.max = rangeEnd;
        }
        requestStartInput.value = rangeStart;
        requestEndInput.value = rangeEnd;
        startInput.value = rangeStart;
        endInput.value = rangeEnd;
        requestRangeText.textContent = `可申請時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
        rangeText.textContent = `可查詢時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
    } else {
        requestRangeText.textContent = "目前沒有可申請的模擬資料。";
        requestButton.disabled = true;
        rangeText.textContent = "目前沒有可查詢的模擬資料。";
        buttons.forEach((button) => { button.disabled = true; });
    }

    buttons.forEach((button) => {
        button.addEventListener("click", async () => {
            const plate = plateInput.value.trim();
            if (!plate) {
                message.textContent = "請先輸入車牌。";
                plateInput.focus();
                return;
            }
            if (!startInput.value || !endInput.value) {
                message.textContent = "請選擇開始時間與結束時間。";
                return;
            }
            if (startInput.value > endInput.value) {
                message.textContent = "開始時間不能晚於結束時間。";
                return;
            }

            const dataType = button.dataset.vendorExport;
            await requestPersonalDownloadOtp(token, {
                data_type: dataType,
                plate,
                start: startInput.value,
                end: endInput.value,
                min_speed: null,
                max_speed: null,
            }, `vendor-${dataType}-trajectories.csv`, buttons);
        });
    });
}


function initializeSupervisorAWorkspace(token, workspaceData) {
    const purposeInput = document.getElementById("supervisor_a-0-0");
    const requestVehicleInput = document.getElementById("supervisor_a-0-1");
    const requestStartInput = document.getElementById("supervisor_a-0-2");
    const requestEndInput = document.getElementById("supervisor_a-0-3");
    const requestRangeText = document.getElementById("supervisor-a-request-available-range");
    const requestButton = document.getElementById("supervisor-a-request-submit");
    const otpEntry = document.getElementById("supervisor-a-otp-entry");
    const otpInput = document.getElementById("supervisor-a-otp-code");
    const otpButton = document.getElementById("supervisor-a-otp-submit");
    const plateInput = document.getElementById("supervisor-a-plate");
    const startInput = document.getElementById("supervisor-a-start");
    const endInput = document.getElementById("supervisor-a-end");
    const rangeText = document.getElementById("supervisor-a-available-range");
    const downloadButton = document.getElementById("supervisor-a-download");
    if (
        !purposeInput || !requestVehicleInput || !requestStartInput || !requestEndInput
        || !requestRangeText || !requestButton || !otpEntry || !otpInput || !otpButton
        || !plateInput || !startInput || !endInput || !rangeText || !downloadButton
    ) return;

    let requestId = null;
    otpInput.addEventListener("input", () => {
        otpInput.value = otpInput.value.replace(/\D/g, "").slice(0, 6);
    });
    requestButton.addEventListener("click", async () => {
        if (!purposeInput.value.trim() || !requestVehicleInput.value.trim()) {
            message.textContent = "請填寫使用目的與車輛。";
            return;
        }
        if (!requestStartInput.value || !requestEndInput.value) {
            message.textContent = "請選擇申請的開始時間與結束時間。";
            return;
        }
        if (requestStartInput.value > requestEndInput.value) {
            message.textContent = "申請的開始時間不能晚於結束時間。";
            return;
        }
        requestButton.disabled = true;
        message.textContent = "正在建立精準速度申請與 Demo OTP…";
        try {
            const result = await authenticatedRequest(
                "/workspace/supervisor-a/speed-requests",
                token,
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        purpose: purposeInput.value.trim(),
                        plate: requestVehicleInput.value.trim(),
                        start: requestStartInput.value,
                        end: requestEndInput.value,
                    }),
                },
            );
            requestId = result.request_id;
            requestButton.hidden = true;
            otpEntry.hidden = false;
            otpInput.focus();
            message.textContent = `Demo OTP：${result.demo_otp}（5 分鐘內有效）`;
        } catch (error) {
            if (error.status === 401) {
                clearSession();
                location.replace("login.html?reason=session");
                return;
            }
            message.textContent = error.message;
        } finally {
            requestButton.disabled = false;
        }
    });
    otpButton.addEventListener("click", async () => {
        if (!Number.isInteger(requestId)) {
            message.textContent = "請先送出申請。";
            return;
        }
        if (!/^\d{6}$/.test(otpInput.value)) {
            message.textContent = "請輸入完整的 6 位數 OTP。";
            return;
        }
        otpButton.disabled = true;
        message.textContent = "正在驗證 OTP…";
        try {
            const blob = await authenticatedPostDownload(
                `/workspace/supervisor-a/speed-requests/${requestId}/verify-otp`,
                token,
                {
                    otp: otpInput.value,
                    plate: requestVehicleInput.value.trim(),
                    start: requestStartInput.value,
                    end: requestEndInput.value,
                },
            );
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = "supervisor-a-authorized-speeds.csv";
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            otpInput.disabled = true;
            otpButton.hidden = true;
            message.textContent = "OTP 驗證成功，精準速度 CSV 已下載。";
        } catch (error) {
            if (error.status === 401) {
                clearSession();
                location.replace("login.html?reason=session");
                return;
            }
            message.textContent = error.message;
        } finally {
            otpButton.disabled = false;
        }
    });

    const availableRange = workspaceData.available_time_range;
    if (availableRange?.start && availableRange?.end) {
        const rangeStart = availableRange.start.slice(0, 19);
        const rangeEnd = availableRange.end.slice(0, 19);
        for (const input of [requestStartInput, requestEndInput, startInput, endInput]) {
            input.min = rangeStart;
            input.max = rangeEnd;
        }
        requestStartInput.value = rangeStart;
        requestEndInput.value = rangeEnd;
        startInput.value = rangeStart;
        endInput.value = rangeEnd;
        requestRangeText.textContent = `可申請時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
        rangeText.textContent = `可查詢時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
    } else {
        requestRangeText.textContent = "目前沒有可申請的模擬資料。";
        requestButton.disabled = true;
        rangeText.textContent = "目前沒有可查詢的模擬資料。";
        downloadButton.disabled = true;
    }

    downloadButton.addEventListener("click", async () => {
        const plate = plateInput.value.trim();
        if (!plate) {
            message.textContent = "請先輸入車牌。";
            plateInput.focus();
            return;
        }
        if (!startInput.value || !endInput.value) {
            message.textContent = "請選擇開始時間與結束時間。";
            return;
        }
        if (startInput.value > endInput.value) {
            message.textContent = "開始時間不能晚於結束時間。";
            return;
        }

        await requestPersonalDownloadOtp(token, {
            data_type: "location",
            plate,
            start: startInput.value,
            end: endInput.value,
            min_speed: null,
            max_speed: null,
        }, "supervisor-a-locations.csv", [downloadButton]);
    });
}


function initializeSupervisorBWorkspace(token, workspaceData) {
    const purposeInput = document.getElementById("supervisor_b-0-0");
    const requestVehicleInput = document.getElementById("supervisor_b-0-1");
    const requestStartInput = document.getElementById("supervisor_b-0-2");
    const requestEndInput = document.getElementById("supervisor_b-0-3");
    const requestRangeText = document.getElementById("supervisor-b-request-available-range");
    const requestButton = document.getElementById("supervisor-b-request-submit");
    const otpEntry = document.getElementById("supervisor-b-otp-entry");
    const otpInput = document.getElementById("supervisor-b-otp-code");
    const otpButton = document.getElementById("supervisor-b-otp-submit");
    const plateInput = document.getElementById("supervisor-b-plate");
    const startInput = document.getElementById("supervisor-b-start");
    const endInput = document.getElementById("supervisor-b-end");
    const rangeText = document.getElementById("supervisor-b-available-range");
    const downloadButton = document.getElementById("supervisor-b-download");
    if (
        !purposeInput || !requestVehicleInput || !requestStartInput || !requestEndInput
        || !requestRangeText || !requestButton || !otpEntry || !otpInput || !otpButton
        || !plateInput || !startInput || !endInput || !rangeText || !downloadButton
    ) return;

    let requestId = null;
    otpInput.addEventListener("input", () => {
        otpInput.value = otpInput.value.replace(/\D/g, "").slice(0, 6);
    });
    requestButton.addEventListener("click", async () => {
        if (!purposeInput.value.trim() || !requestVehicleInput.value.trim()) {
            message.textContent = "請填寫使用目的與車輛。";
            return;
        }
        if (!requestStartInput.value || !requestEndInput.value) {
            message.textContent = "請選擇申請的開始時間與結束時間。";
            return;
        }
        if (requestStartInput.value > requestEndInput.value) {
            message.textContent = "申請的開始時間不能晚於結束時間。";
            return;
        }
        requestButton.disabled = true;
        message.textContent = "正在建立精準位置申請與 Demo OTP…";
        try {
            const result = await authenticatedRequest(
                "/workspace/supervisor-b/location-requests",
                token,
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        purpose: purposeInput.value.trim(),
                        plate: requestVehicleInput.value.trim(),
                        start: requestStartInput.value,
                        end: requestEndInput.value,
                    }),
                },
            );
            requestId = result.request_id;
            requestButton.hidden = true;
            otpEntry.hidden = false;
            otpInput.focus();
            message.textContent = `Demo OTP：${result.demo_otp}（5 分鐘內有效）`;
        } catch (error) {
            if (error.status === 401) {
                clearSession();
                location.replace("login.html?reason=session");
                return;
            }
            message.textContent = error.message;
        } finally {
            requestButton.disabled = false;
        }
    });
    otpButton.addEventListener("click", async () => {
        if (!Number.isInteger(requestId)) {
            message.textContent = "請先送出申請。";
            return;
        }
        if (!/^\d{6}$/.test(otpInput.value)) {
            message.textContent = "請輸入完整的 6 位數 OTP。";
            return;
        }
        otpButton.disabled = true;
        message.textContent = "正在驗證 OTP…";
        try {
            const blob = await authenticatedPostDownload(
                `/workspace/supervisor-b/location-requests/${requestId}/verify-otp`,
                token,
                {
                    otp: otpInput.value,
                    plate: requestVehicleInput.value.trim(),
                    start: requestStartInput.value,
                    end: requestEndInput.value,
                },
            );
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = "supervisor-b-authorized-locations.csv";
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            otpInput.disabled = true;
            otpButton.hidden = true;
            message.textContent = "OTP 驗證成功，精準位置 CSV 已下載。";
        } catch (error) {
            if (error.status === 401) {
                clearSession();
                location.replace("login.html?reason=session");
                return;
            }
            message.textContent = error.message;
        } finally {
            otpButton.disabled = false;
        }
    });

    const availableRange = workspaceData.available_time_range;
    if (availableRange?.start && availableRange?.end) {
        const rangeStart = availableRange.start.slice(0, 19);
        const rangeEnd = availableRange.end.slice(0, 19);
        for (const input of [requestStartInput, requestEndInput, startInput, endInput]) {
            input.min = rangeStart;
            input.max = rangeEnd;
        }
        requestStartInput.value = rangeStart;
        requestEndInput.value = rangeEnd;
        startInput.value = rangeStart;
        endInput.value = rangeEnd;
        requestRangeText.textContent = `可申請時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
        rangeText.textContent = `可查詢時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
    } else {
        requestRangeText.textContent = "目前沒有可申請的模擬資料。";
        requestButton.disabled = true;
        rangeText.textContent = "目前沒有可查詢的模擬資料。";
        downloadButton.disabled = true;
    }

    downloadButton.addEventListener("click", async () => {
        const plate = plateInput.value.trim();
        if (!plate) {
            message.textContent = "請先輸入車牌。";
            plateInput.focus();
            return;
        }
        if (!startInput.value || !endInput.value) {
            message.textContent = "請選擇開始時間與結束時間。";
            return;
        }
        if (startInput.value > endInput.value) {
            message.textContent = "開始時間不能晚於結束時間。";
            return;
        }

        await requestPersonalDownloadOtp(token, {
            data_type: "speed",
            plate,
            start: startInput.value,
            end: endInput.value,
            min_speed: null,
            max_speed: null,
        }, "supervisor-b-speeds.csv", [downloadButton]);
    });
}


function initializeAdminAccountLookup(token) {
    const form = document.getElementById("admin-account-form");
    const input = document.getElementById("admin-0-0");
    const button = document.getElementById("admin-account-submit");
    const result = document.getElementById("admin-account-result");
    const usernameText = document.getElementById("admin-account-username");
    const roleText = document.getElementById("admin-account-role");
    const emailText = document.getElementById("admin-account-email");
    const statusText = document.getElementById("admin-account-message");
    if (!form || !input || !button || !result || !usernameText
        || !roleText || !emailText || !statusText) return;

    input.addEventListener("input", () => {
        result.hidden = true;
        statusText.textContent = "";
    });
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (button.disabled) return;
        result.hidden = true;
        const username = input.value.trim();
        if (!username) {
            statusText.textContent = "請輸入帳號（username）。";
            input.focus();
            return;
        }
        button.disabled = true;
        input.disabled = true;
        statusText.textContent = "正在查詢帳號…";
        try {
            const params = new URLSearchParams({username});
            const account = await authenticatedRequest(`/users/lookup?${params}`, token);
            usernameText.textContent = account.username;
            roleText.textContent = ROLE_PAGES[account.role]?.label
                || (account.role === "visitor" ? "訪客" : account.role);
            emailText.textContent = account.email;
            result.hidden = false;
            statusText.textContent = "查詢完成。";
        } catch (error) {
            statusText.textContent = error.status === 404
                ? "找不到此帳號，請確認輸入的是完整的 username。"
                : error.message;
        } finally {
            button.disabled = false;
            input.disabled = false;
        }
    });
}


function initializeAdminOtpWorkspace(token, workspaceData) {
    const form = document.getElementById("admin-otp-form");
    const requestVehicleInput = document.getElementById("admin-otp-plate");
    const requestStartInput = document.getElementById("admin-otp-start");
    const requestEndInput = document.getElementById("admin-otp-end");
    const requestRangeText = document.getElementById("admin-otp-available-range");
    const statusText = document.getElementById("admin-otp-message");
    const otpEntry = document.getElementById("admin-otp-entry");
    const otpInput = document.getElementById("admin-otp-code");
    const otpLabel = document.getElementById("admin-otp-label");
    const otpButton = document.getElementById("admin-otp-verify");
    const requestButtons = [document.getElementById("admin-otp-location-submit"),
                            document.getElementById("admin-otp-speed-submit")];
    if (!form || !requestVehicleInput || !requestStartInput || !requestEndInput || !requestRangeText || !statusText
        || !otpEntry || !otpInput || !otpLabel || !otpButton || requestButtons.some(button => !button)) return;
    const availableRange = workspaceData.available_time_range;
    const hasAvailableData = Boolean(availableRange?.start && availableRange?.end);
    if (hasAvailableData) {
        const rangeStart = availableRange.start.slice(0, 19);
        const rangeEnd = availableRange.end.slice(0, 19);
        for (const input of [requestStartInput, requestEndInput]) {
            input.min = rangeStart;
            input.max = rangeEnd;
        }
        requestStartInput.value = rangeStart;
        requestEndInput.value = rangeEnd;
        requestRangeText.textContent = `可申請時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
    } else {
        requestRangeText.textContent = "目前沒有可申請的模擬資料。";
        requestButtons.forEach(button => { button.disabled = true; });
    }
    let requestScope = null;
    let completed = false;
    let busy = false;
    function setBusy(value) {
        busy = value;
        for (const control of [requestVehicleInput, requestStartInput, requestEndInput, otpInput, otpButton, ...requestButtons]) {
            control.disabled = value;
        }
        otpInput.disabled = value || completed;
    }
    function clearRequest() {
        requestScope = null;
        completed = false;
        otpButton.hidden = false;
        otpInput.disabled = false;
        requestButtons.forEach(button => { button.hidden = false; });
        otpEntry.hidden = true;
        otpInput.value = "";
    }
    form.addEventListener("input", () => {
        clearRequest();
        statusText.textContent = "";
    });
    otpInput.addEventListener("input", () => {
        otpInput.value = otpInput.value.replace(/\D/g, "").slice(0, 6);
    });
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy || !hasAvailableData || requestScope) return;
        const plate = requestVehicleInput.value.trim();
        const start = requestStartInput.value;
        const end = requestEndInput.value;
        if (!plate) {
            statusText.textContent = "請先輸入車牌，才能申請 OTP 與下載資料。";
            requestVehicleInput.focus();
            return;
        }
        if ((start && !end) || (!start && end)) {
            statusText.textContent = "請同時填寫開始時間與結束時間。";
            return;
        }
        if (start && end && new Date(start) > new Date(end)) {
            statusText.textContent = "開始時間不能晚於結束時間。";
            return;
        }
        const dataType = event.submitter?.value === "speed" ? "speed" : "location";
        const dataLabel = dataType === "speed" ? "精準速度" : "精準位置";
        clearRequest();
        setBusy(true);
        statusText.textContent = `正在建立${dataLabel}申請…`;
        try {
            const result = await authenticatedRequest(`/workspace/admin/${dataType}-requests`, token, {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({plate, start: start || null, end: end || null}),
            });
            requestScope = result;
            requestButtons.forEach(button => { button.hidden = true; });
            otpButton.hidden = false;
            otpLabel.textContent = dataType === "location" ? "主管 A OTP（精準位置）" : "主管 B OTP（精準速度）";
            otpEntry.hidden = false;
            statusText.textContent = `Demo OTP：${result.demo_otp}（5 分鐘內有效）。範圍：${result.plate || "所有車輛"}，${displayDateTime(result.start)} ～ ${displayDateTime(result.end)}`;
        } catch (error) {
            if (error.status === 401) {
                clearSession();
                location.replace("login.html?reason=session");
                return;
            }
            statusText.textContent = error.message;
        } finally {
            setBusy(false);
            if (requestScope) otpInput.focus();
        }
    });
    otpButton.addEventListener("click", async () => {
        if (busy) return;
        if (!Number.isInteger(requestScope?.request_id)) {
            statusText.textContent = "請先送出申請。";
            return;
        }
        if (!/^\d{6}$/.test(otpInput.value)) {
            statusText.textContent = "請輸入完整的 6 位數 OTP。";
            return;
        }
        const request = requestScope;
        const dataLabel = request.data_type === "speed" ? "精準速度" : "精準位置";
        setBusy(true);
        statusText.textContent = "正在驗證 OTP…";
        try {
            const blob = await authenticatedPostDownload(
                `/workspace/admin/${request.data_type}-requests/${request.request_id}/verify-otp`, token,
                {otp: otpInput.value, plate: request.plate, start: request.start, end: request.end},
            );
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `admin-authorized-${request.data_type}.csv`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            requestScope = null;
            completed = true;
            otpInput.disabled = true;
            otpButton.hidden = true;
            statusText.textContent = `OTP 驗證成功，${dataLabel} CSV 已下載。`;
        } catch (error) {
            if (error.status === 401) {
                clearSession();
                location.replace("login.html?reason=session");
                return;
            }
            const messages = {
                409: "OTP 已使用，請重新送出申請。",
                410: "OTP 已過期，請重新送出申請。",
                422: "OTP 不正確，請重新輸入。",
                429: "OTP 錯誤次數已達上限，請重新送出申請。",
            };
            if ([404, 409, 410, 429].includes(error.status)) clearRequest();
            statusText.textContent = messages[error.status] || error.message;
        } finally {
            setBusy(false);
        }
    });
}


function initializeAdminWorkspace(token, workspaceData) {
    initializeAdminAccountLookup(token);
    initializeAdminOtpWorkspace(token, workspaceData);
    const memberCount = document.getElementById("admin-member-count");
    const vehicleCount = document.getElementById("admin-vehicle-count");
    const roleCount = document.getElementById("admin-role-count");
    const statusNote = document.getElementById("admin-site-status-note");
    if (!memberCount || !vehicleCount || !roleCount || !statusNote) return;

    const service = workspaceData.service;
    if (
        !service
        || !Number.isInteger(service.member_count)
        || !Number.isInteger(service.vehicle_count)
        || !Number.isInteger(service.role_count)
    ) {
        statusNote.textContent = "網站統計資料格式不正確。";
        return;
    }

    memberCount.textContent = String(service.member_count);
    vehicleCount.textContent = String(service.vehicle_count);
    roleCount.textContent = String(service.role_count);
    statusNote.textContent = "統計資料已載入";

    const minSpeedInput = document.getElementById("admin-min-speed");
    const maxSpeedInput = document.getElementById("admin-max-speed");
    const plateInput = document.getElementById("admin-query-plate");
    const startInput = document.getElementById("admin-query-start");
    const endInput = document.getElementById("admin-query-end");
    const rangeText = document.getElementById("admin-available-range");
    const queryButton = document.getElementById("admin-query-download");
    if (
        !minSpeedInput || !maxSpeedInput || !plateInput
        || !startInput || !endInput || !rangeText || !queryButton
    ) return;

    const availableRange = workspaceData.available_time_range;
    if (availableRange?.start && availableRange?.end) {
        const rangeStart = availableRange.start.slice(0, 19);
        const rangeEnd = availableRange.end.slice(0, 19);
        for (const input of [startInput, endInput]) {
            input.min = rangeStart;
            input.max = rangeEnd;
        }
        startInput.value = rangeStart;
        endInput.value = rangeEnd;
        rangeText.textContent = `可查詢時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
    } else {
        rangeText.textContent = "目前沒有可查詢的模擬資料。";
        queryButton.disabled = true;
    }

    queryButton.addEventListener("click", async () => {
        const plate = plateInput.value.trim();
        const minSpeed = minSpeedInput.value;
        const maxSpeed = maxSpeedInput.value;
        const hasMinSpeed = minSpeed !== "";
        const hasMaxSpeed = maxSpeed !== "";
        if (!plate) {
            message.textContent = "請先輸入車牌，才能下載資料。";
            plateInput.focus();
            return;
        }
        if (hasMinSpeed !== hasMaxSpeed) {
            message.textContent = "速度下限與上限必須一起填寫。";
            return;
        }
        if (hasMinSpeed && Number(minSpeed) > Number(maxSpeed)) {
            message.textContent = "速度下限不能大於速度上限。";
            return;
        }
        if (!startInput.value || !endInput.value) {
            message.textContent = "請選擇開始時間與結束時間。";
            return;
        }
        if (startInput.value > endInput.value) {
            message.textContent = "開始時間不能晚於結束時間。";
            return;
        }

        await requestPersonalDownloadOtp(token, {
            data_type: "trajectories",
            plate,
            start: startInput.value,
            end: endInput.value,
            min_speed: hasMinSpeed ? Number(minSpeed) : null,
            max_speed: hasMaxSpeed ? Number(maxSpeed) : null,
        }, "admin-trajectories.csv", [queryButton]);
    });
}


function initializeResearcherWorkspace(token, workspaceData) {
    const startInput = document.getElementById("researcher-start");
    const endInput = document.getElementById("researcher-end");
    const rangeText = document.getElementById("researcher-available-range");
    const downloadButton = document.getElementById("researcher-download");
    if (!startInput || !endInput || !rangeText || !downloadButton) return;

    const availableRange = workspaceData.available_time_range;
    if (availableRange?.start && availableRange?.end) {
        const rangeStart = availableRange.start.slice(0, 19);
        const rangeEnd = availableRange.end.slice(0, 19);
        for (const input of [startInput, endInput]) {
            input.min = rangeStart;
            input.max = rangeEnd;
        }
        startInput.value = rangeStart;
        endInput.value = rangeEnd;
        rangeText.textContent = `可查詢時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
    } else {
        rangeText.textContent = "目前沒有可查詢的模擬資料。";
        downloadButton.disabled = true;
    }

    downloadButton.addEventListener("click", async () => {
        if (!startInput.value || !endInput.value) {
            message.textContent = "請選擇開始時間與結束時間。";
            return;
        }
        if (startInput.value > endInput.value) {
            message.textContent = "開始時間不能晚於結束時間。";
            return;
        }

        const params = new URLSearchParams({
            start: startInput.value,
            end: endInput.value,
        });
        downloadButton.disabled = true;
        message.textContent = "正在解密並套用完整 PETs…";
        try {
            const blob = await authenticatedDownload(
                `/workspace/researcher/trajectories?${params.toString()}`,
                token,
            );
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = "researcher-trajectories.csv";
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            message.textContent = "研究資料 CSV 已下載。";
        } catch (error) {
            if (error.status === 401) {
                clearSession();
                location.replace("login.html?reason=session");
                return;
            }
            message.textContent = error.message;
        } finally {
            downloadButton.disabled = false;
        }
    });
}


async function initializePublicVisitorPage() {
    const startInput = document.getElementById("visitor-start");
    const endInput = document.getElementById("visitor-end");
    const rangeText = document.getElementById("visitor-available-range");
    const queryButton = document.getElementById("visitor-query");
    const averageValue = document.getElementById("visitor-average-speed");
    const averageNote = document.getElementById("visitor-average-note");
    if (!startInput || !endInput || !rangeText || !queryButton || !averageValue || !averageNote) return;

    queryButton.disabled = true;
    try {
        const range = await apiRequest("/public/traffic-range");
        if (typeof range.start !== "string" || typeof range.end !== "string") {
            rangeText.textContent = "目前沒有可查詢的模擬資料。";
            message.textContent = "公開統計已連線，但資料庫目前沒有軌跡資料。";
            return;
        }
        const rangeStart = range.start.slice(0, 19);
        const rangeEnd = range.end.slice(0, 19);
        for (const input of [startInput, endInput]) {
            input.min = rangeStart;
            input.max = rangeEnd;
        }
        startInput.value = rangeStart;
        endInput.value = rangeEnd;
        rangeText.textContent = `可查詢時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
        queryButton.disabled = false;
        message.textContent = "請選擇時間並查詢整體平均速度。";
    } catch (error) {
        rangeText.textContent = "無法載入可查詢時間。";
        message.textContent = error.message;
        return;
    }

    queryButton.addEventListener("click", async () => {
        if (!startInput.value || !endInput.value) {
            message.textContent = "請選擇開始時間與結束時間。";
            return;
        }
        if (startInput.value > endInput.value) {
            message.textContent = "開始時間不能晚於結束時間。";
            return;
        }

        queryButton.disabled = true;
        averageValue.textContent = "—";
        averageNote.textContent = "正在計算…";
        message.textContent = "正在計算所選時間內的整體平均速度…";
        try {
            const params = new URLSearchParams({
                start: startInput.value,
                end: endInput.value,
            });
            const data = await apiRequest(`/public/average-speed?${params.toString()}`);
            if (data.average_speed_kmh === null) {
                averageValue.textContent = "—";
                averageNote.textContent = "資料不足，無法提供統計";
                message.textContent = "所選時間內不足三台車，為保護個別車輛不提供平均速度。";
                return;
            }
            if (typeof data.average_speed_kmh !== "number") {
                throw new Error("後端平均速度格式不正確。");
            }
            averageValue.textContent = `${data.average_speed_kmh.toFixed(1)} km/h`;
            averageNote.textContent = "所選時間內所有車輛的整體平均";
            message.textContent = "平均速度查詢完成。";
        } catch (error) {
            averageNote.textContent = "查詢失敗";
            message.textContent = error.message;
        } finally {
            queryButton.disabled = false;
        }
    });
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


async function initializePoliceOtpWorkspace(token) {
    const form = document.getElementById("police-otp-form");
    const plateInput = document.getElementById("police-otp-plate");
    const startInput = document.getElementById("police-otp-start");
    const endInput = document.getElementById("police-otp-end");
    const rangeText = document.getElementById("police-otp-available-range");
    const requestActions = document.getElementById("police-otp-request-actions");
    const requestButtons = [...requestActions?.querySelectorAll("button") || []];
    const otpEntry = document.getElementById("police-otp-entry");
    const otpLabel = document.getElementById("police-otp-label");
    const otpInput = document.getElementById("police-otp-code");
    const otpButton = document.getElementById("police-otp-submit");
    const statusText = document.getElementById("police-otp-message");
    if (!form || !plateInput || !startInput || !endInput || !rangeText
        || !requestActions || requestButtons.length !== 2 || !otpEntry
        || !otpLabel || !otpInput || !otpButton || !statusText) return;

    let requestScope = null;
    let completed = false;
    let busy = false;
    function setBusy(value) {
        busy = value;
        for (const control of [plateInput, startInput, endInput, otpInput,
            otpButton, ...requestButtons]) {
            control.disabled = value;
        }
        otpInput.disabled = value || completed;
    }
    function clearRequest() {
        requestScope = null;
        completed = false;
        otpButton.hidden = false;
        otpInput.disabled = false;
        requestActions.hidden = false;
        otpEntry.hidden = true;
        otpInput.value = "";
    }
    try {
        const availableRange = await apiRequest("/public/traffic-range");
        if (availableRange?.start && availableRange?.end) {
            const rangeStart = availableRange.start.slice(0, 19);
            const rangeEnd = availableRange.end.slice(0, 19);
            for (const input of [startInput, endInput]) {
                input.min = rangeStart;
                input.max = rangeEnd;
            }
            startInput.value = rangeStart;
            endInput.value = rangeEnd;
            rangeText.textContent = `可申請時間：${displayDateTime(rangeStart)} ～ ${displayDateTime(rangeEnd)}`;
        } else {
            rangeText.textContent = "目前沒有可申請的模擬資料。";
            requestButtons.forEach(button => { button.disabled = true; });
        }
    } catch (error) {
        rangeText.textContent = "無法載入可申請時間。";
        requestButtons.forEach(button => { button.disabled = true; });
        statusText.textContent = error.message;
    }
    form.addEventListener("input", () => {
        clearRequest();
        statusText.textContent = "";
    });
    otpInput.addEventListener("input", () => {
        otpInput.value = otpInput.value.replace(/\D/g, "").slice(0, 6);
        statusText.textContent = "";
    });
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy || requestScope) return;
        const plate = plateInput.value.trim();
        if (!plate) {
            statusText.textContent = "請先輸入車牌。";
            plateInput.focus();
            return;
        }
        if (!startInput.value || !endInput.value) {
            statusText.textContent = "請選擇開始時間與結束時間。";
            return;
        }
        if (startInput.value > endInput.value) {
            statusText.textContent = "開始時間不能晚於結束時間。";
            return;
        }
        const dataType = event.submitter?.value === "speed" ? "speed" : "location";
        const dataLabel = dataType === "speed" ? "精準速度" : "精準位置";
        setBusy(true);
        statusText.textContent = `正在建立${dataLabel}申請與 Demo OTP…`;
        try {
            const result = await authenticatedRequest(
                `/workspace/police/${dataType}-requests`,
                token,
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        plate,
                        start: startInput.value,
                        end: endInput.value,
                    }),
                },
            );
            requestScope = result;
            requestActions.hidden = true;
            otpLabel.textContent = `${dataLabel} Email OTP`;
            otpInput.value = "";
            otpEntry.hidden = false;
            statusText.textContent = `Demo OTP：${result.demo_otp}（5 分鐘內有效）`;
        } catch (error) {
            if (error.status === 401) {
                clearSession();
                location.replace("login.html?reason=session");
                return;
            }
            statusText.textContent = error.message;
        } finally {
            setBusy(false);
            if (requestScope) otpInput.focus();
        }
    });
    otpButton.addEventListener("click", async () => {
        if (busy) return;
        if (!Number.isInteger(requestScope?.request_id)) {
            statusText.textContent = "請先送出申請。";
            return;
        }
        if (!/^\d{6}$/.test(otpInput.value)) {
            statusText.textContent = "請輸入完整的 6 位數 Email OTP。";
            return;
        }
        const request = requestScope;
        const dataLabel = request.data_type === "speed" ? "精準速度" : "精準位置";
        setBusy(true);
        statusText.textContent = "正在驗證 OTP…";
        try {
            const blob = await authenticatedPostDownload(
                `/workspace/police/${request.data_type}-requests/${request.request_id}/verify-otp`,
                token,
                {
                    otp: otpInput.value,
                    plate: request.plate,
                    start: request.start,
                    end: request.end,
                },
            );
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `police-authorized-${request.data_type}.csv`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            requestScope = null;
            completed = true;
            otpInput.disabled = true;
            otpButton.hidden = true;
            statusText.textContent = `OTP 驗證成功，${dataLabel} CSV 已下載。`;
        } catch (error) {
            if (error.status === 401) {
                clearSession();
                location.replace("login.html?reason=session");
                return;
            }
            const messages = {
                404: "找不到申請、車輛資料或 OTP 已失效，請重新送出申請。",
                409: "OTP 已使用，請重新送出申請。",
                410: "OTP 已過期，請重新送出申請。",
                422: "OTP 不正確，請重新輸入。",
                429: "OTP 錯誤次數已達上限，請重新送出申請。",
            };
            if ([404, 409, 410, 429].includes(error.status)) clearRequest();
            statusText.textContent = messages[error.status] || error.message;
        } finally {
            setBusy(false);
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
        const workspaceData = await loadWorkspace(workspace, token, user.role);
        if (user.role === "owner") initializeOwnerWorkspace(token, workspaceData);
        if (user.role === "vendor") initializeVendorWorkspace(token, workspaceData);
        if (user.role === "supervisor_a") initializeSupervisorAWorkspace(token, workspaceData);
        if (user.role === "supervisor_b") initializeSupervisorBWorkspace(token, workspaceData);
        if (user.role === "admin") initializeAdminWorkspace(token, workspaceData);
        if (user.role === "researcher") initializeResearcherWorkspace(token, workspaceData);
        if (user.role === "police") initializePoliceOtpWorkspace(token);
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
if (document.body.dataset.publicPage === 'visitor') initializePublicVisitorPage();

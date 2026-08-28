let logCursor = 0;
let selectedMode = null;
let replayCatalog = [];
let resumeCatalog = [];
const cameraStreamLoaded = { wrist: false, front: false };
let latestStatus = null;
let focusOpen = false;
let enlargedCamera = null;
const clientId = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;

const el = (id) => document.getElementById(id);

async function api(path, payload = {}) {
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    toast(result.message || "요청을 처리했습니다.", !result.ok);
    return result;
  } catch (_) {
    const result = { ok: false, message: "GUI 서버와 통신하지 못했습니다. 창을 다시 열어주세요." };
    toast(result.message, true);
    return result;
  }
}

function toast(message, isError = false) {
  const node = el("toast");
  node.textContent = message;
  node.className = `show ${isError ? "error" : ""}`;
  window.clearTimeout(window.toastTimer);
  window.toastTimer = window.setTimeout(() => { node.className = ""; }, 4300);
}

function updateStatus(data) {
  latestStatus = data;
  const modeNames = { idle: "대기", doctor: "환경 진단", transition: "안전 전환", teleop: "텔레옵", record: "데이터 수집", replay: "성공 시연 재생", camera: "카메라 보기", init: "초기 자세 복귀", c31: "C31 복구", c19: "C19 복구", c1: "C1 복구" };
  el("mode").textContent = modeNames[data.mode] || data.mode;
  el("phase").textContent = data.phase || "";
  el("process").textContent = data.active || "없음";
  el("pid").textContent = data.pid ? `PID ${data.pid}` : "PID 없음";
  const conn = el("connection");
  conn.textContent = data.active ? "로컬 제어판 연결됨 · 실행 중" : "로컬 제어판 연결됨";
  conn.className = `pill ${data.active ? "ok" : "muted"}`;

  const error = data.last_error;
  el("error-title").textContent = error ? error.title : "감지된 오류 없음";
  el("error-detail").textContent = error ? `${error.detail} ${error.recovery}` : "환경 진단 버튼으로 현재 xArm/GELLO/카메라 상태를 확인하세요.";
  el("error-card").style.borderColor = error ? "#d98991" : "#f0d4d7";

  const recordReady = data.mode === "record" && data.record_ready;
  document.querySelectorAll("[data-record-key]").forEach((button) => { button.disabled = !recordReady; });
  el("record-hint").textContent = recordReady
    ? "녹화 준비가 완료되었습니다. 화면 버튼으로 녹화 시작·저장·폐기·종료를 선택하세요."
    : "데이터 수집 준비 뒤, 로그에 키 입력 안내가 나오면 녹화 버튼이 활성화됩니다.";

  for (const name of ["wrist", "front"]) {
    const camera = (data.cameras || {})[name] || {};
    const status = el(`camera-status-${name}`);
    const image = el(`camera-image-${name}`);
    const empty = el(`camera-empty-${name}`);
    if (camera.receiving) {
      status.textContent = `${camera.width}×${camera.height} · 연결됨`;
      status.className = "camera-state ok";
      if (!cameraStreamLoaded[name]) {
        cameraStreamLoaded[name] = true;
        image.src = `/api/camera/stream/${name}?v=${Date.now()}`;
      }
      image.classList.add("active");
    } else if (camera.running) {
      status.textContent = camera.error ? "오류" : "연결 중";
      status.className = `camera-state ${camera.error ? "bad" : "muted"}`;
      empty.textContent = camera.error || "카메라 연결 중…";
    } else {
      status.textContent = data.mode === "record" ? "녹화에서 사용 중" : "꺼짐";
      status.className = "camera-state muted";
      empty.textContent = data.mode === "record" ? "데이터 녹화 프로그램이 카메라를 사용합니다" : "테스트 또는 텔레옵을 시작하세요";
      image.classList.remove("active");
      image.removeAttribute("src");
      cameraStreamLoaded[name] = false;
    }
  }
  updateFocusMode(data);

  const c31Stage = data.c31_stage || "idle";
  document.querySelector('[data-action="c31-start"]').disabled = ["c31", "c19", "c1"].includes(data.mode);
  document.querySelector('[data-action="c31-clear"]').disabled = c31Stage !== "clear";
  document.querySelector('[data-action="c31-return"]').disabled = c31Stage !== "return";
  const c31Hints = {
    idle: "C31(충돌/과전류): 먼저 C31 복구 시작을 누르세요.",
    diagnosing: "C31 오류인지 읽기 전용으로 확인하고 있습니다.",
    clear: "충돌 물체·케이블을 제거한 뒤 ‘장애물 제거 완료’를 누르세요.",
    clearing: "C31 오류를 해제하고 안전 상태를 확인 중입니다. 로봇은 아직 이동하지 않습니다.",
    return: "C31이 해제됐습니다. 작업영역을 확인한 뒤 ‘초기 자세 복귀 승인’을 누르세요.",
    returning: "3초 안전 대기 뒤 초기 자세로 복귀 중입니다.",
  };
  el("c31-hint").textContent = c31Hints[c31Stage] || "C31 복구 상태를 확인 중입니다.";

  const recovering = ["c31", "c19", "c1"].includes(data.mode);
  const c19Stage = data.c19_stage || "idle";
  document.querySelector('[data-action="c19-start"]').disabled = recovering;
  document.querySelector('[data-action="c19-check"]').disabled = c19Stage !== "check";

  const c1Stage = data.c1_stage || "idle";
  document.querySelector('[data-action="c1-start"]').disabled = recovering;
  document.querySelector('[data-action="c1-release"]').disabled = c1Stage !== "release";
  document.querySelector('[data-action="c1-return"]').disabled = c1Stage !== "return";
  const c1Hints = {
    idle: "C1(비상정지): 버튼을 물리적으로 해제한 뒤 단계별로 승인합니다.",
    diagnosing: "C1 오류인지 읽기 전용으로 확인하고 있습니다.",
    release: "비상정지 원인을 확인하고 버튼을 돌려서 해제한 뒤 ‘비상정지 해제 완료’를 누르세요.",
    enabling: "C1 해제와 모터 재활성화 중입니다. 팔은 이동하지 않습니다.",
    return: "모터가 다시 켜졌습니다. 작업영역을 확인한 뒤 ‘초기 자세 복귀 승인’을 누르세요.",
    returning: "3초 안전 대기 뒤 초기 자세로 복귀 중입니다.",
  };
  el("c1-hint").textContent = c1Hints[c1Stage] || "C1 복구 상태를 확인 중입니다.";
  const c19Hints = {
    idle: "C19(그리퍼/끝단 통신): 케이블 점검 후 통신만 복구하며 팔·그리퍼는 움직이지 않습니다.",
    diagnosing: "C19 오류인지 읽기 전용으로 확인하고 있습니다.",
    check: "그리퍼 커넥터와 손목 카메라 케이블을 점검한 뒤 ‘케이블 점검 완료’를 누르세요.",
    recovering: "C19 해제와 그리퍼 통신 복구 중입니다. 팔과 그리퍼는 움직이지 않습니다.",
  };
  el("c19-hint").textContent = c19Hints[c19Stage] || "C19 복구 상태를 확인 중입니다.";
}

async function pollStatus() {
  try {
    const response = await fetch("/api/status");
    const result = await response.json();
    if (result.ok) updateStatus(result.data);
  } catch (_) {
    el("connection").textContent = "GUI 서버 연결 끊김";
    el("connection").className = "pill bad";
  }
}

async function pollLogs() {
  try {
    const response = await fetch(`/api/logs?after=${logCursor}`);
    const result = await response.json();
    if (!result.ok || !result.lines.length) return;
    const log = el("log");
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
    for (const line of result.lines) {
      log.textContent += `[${line.timestamp}] ${line.text}\n`;
      logCursor = line.number;
    }
    if (atBottom) log.scrollTop = log.scrollHeight;
  } catch (_) { /* status polling displays the connection problem */ }
}

async function heartbeat() {
  try {
    await fetch(`/api/heartbeat?client=${encodeURIComponent(clientId)}`, { cache: "no-store" });
  } catch (_) { /* pollStatus가 사용자에게 연결 문제를 표시한다. */ }
}

function setFocusCamera(name, active, source, statusText) {
  const image = el(`focus-image-${name}`);
  const empty = el(`focus-empty-${name}`);
  el(`focus-camera-status-${name}`).textContent = statusText;
  if (active) {
    if (image.dataset.source !== source) {
      image.dataset.source = source;
      image.src = source;
    }
    image.classList.add("active");
  } else {
    image.classList.remove("active");
    image.removeAttribute("src");
    image.dataset.source = "";
    empty.textContent = statusText;
  }
}

function updateFocusMode(data) {
  const modeNames = { idle: "대기", teleop: "텔레옵 실행 중", record: "데이터 수집 중", transition: "전환 중" };
  el("focus-mode-status").textContent = modeNames[data.mode] || data.mode;
  const record = data.record || {};
  const phaseNames = {
    inactive: "녹화 대기", starting: "녹화 프로그램 준비 중", ready: "다음 녹화 대기", waiting: "녹화 시작 대기",
    recording: "에피소드 녹화 중", decision: "성공 저장 또는 실패 폐기 선택", processing: "판정/저장 처리 중",
    resetting: "다음 에피소드 준비 중", stopped: "녹화 종료", stale: "상태 연결 확인 필요",
  };
  el("focus-record-phase").textContent = phaseNames[record.phase] || record.phase || "대기";
  const stopButton = el("focus-stop");
  stopButton.innerHTML = data.mode === "teleop" ? "텔레옵 정지 <kbd>Space</kbd>" : "현재 모드 중지";
  el("focus-saved").textContent = String(record.saved_episodes || 0);
  el("focus-discarded").textContent = String(record.discarded_episodes || 0);
  const limit = Number(record.episode_time_s || el("focus-episode-time").value || 0);
  el("focus-time-limit").textContent = `설정 시간 ${limit || "--"}초`;
  let elapsed = 0;
  if (record.phase === "recording" && record.episode_started_at) {
    elapsed = Math.max(0, Date.now() / 1000 - Number(record.episode_started_at));
  }
  el("focus-timer").textContent = limit ? `${Math.min(elapsed, limit).toFixed(1)}초` : "--:--";
  el("focus-progress-bar").style.width = limit ? `${Math.min(100, elapsed / limit * 100)}%` : "0%";

  for (const name of ["wrist", "front"]) {
    if (data.mode === "record" && record.frames && record.frames[name]) {
      // 정적 JPEG를 주기적으로 갱신한다. 녹화가 읽은 동일 프레임의 UI 복사본이다.
      setFocusCamera(name, true, `/api/record/frame/${name}?v=${Math.floor(Date.now() / 100)}`, "녹화 영상 · 최대 10fps 표시");
    } else {
      const camera = (data.cameras || {})[name] || {};
      setFocusCamera(name, Boolean(camera.receiving), `/api/camera/stream/${name}`, camera.receiving ? "실시간 연결됨" : "카메라 대기 중");
    }
  }
}

function openFocusMode() {
  focusOpen = true;
  syncMainSettingsToFocus();
  el("focus-mode").classList.add("open");
  el("focus-mode").setAttribute("aria-hidden", "false");
  if (latestStatus) updateFocusMode(latestStatus);
}

function closeFocusMode() {
  focusOpen = false;
  el("focus-mode").classList.remove("open");
  el("focus-mode").setAttribute("aria-hidden", "true");
  if (document.fullscreenElement) document.exitFullscreen();
}

function selectedFocusTracking() {
  const checked = document.querySelector('input[name="focus-tracking-mode"]:checked');
  return checked ? checked.value : "joint";
}

function syncFocusSettingsToMain() {
  const tracking = selectedFocusTracking();
  const mainTracking = document.querySelector(`input[name="tracking-mode"][value="${tracking}"]`);
  if (mainTracking) mainTracking.checked = true;
  el("episode-time").value = el("focus-episode-time").value;
}

function syncMainSettingsToFocus() {
  const tracking = selectedTracking();
  const focusTracking = document.querySelector(`input[name="focus-tracking-mode"][value="${tracking}"]`);
  if (focusTracking) focusTracking.checked = true;
  el("focus-episode-time").value = el("episode-time").value;
}

async function openCameraEnlarge(name) {
  enlargedCamera = name;
  const labels = { wrist: "손목 카메라 크게 보기", front: "전면 카메라 크게 보기" };
  el("camera-enlarge-title").textContent = labels[name] || "카메라 크게 보기";
  el("camera-enlarge").classList.add("open");
  el("camera-enlarge").setAttribute("aria-hidden", "false");
  const camera = ((latestStatus || {}).cameras || {})[name] || {};
  if ((latestStatus || {}).mode !== "record" && !camera.running) {
    await api("/api/camera/start", { camera: name });
  }
  updateEnlargedCamera();
}

function updateEnlargedCamera() {
  if (!enlargedCamera || !latestStatus) return;
  const image = el("camera-enlarge-image");
  const empty = el("camera-enlarge-empty");
  const record = latestStatus.record || {};
  let source = "";
  if (latestStatus.mode === "record" && record.frames && record.frames[enlargedCamera]) {
    source = `/api/record/frame/${enlargedCamera}?v=${Math.floor(Date.now() / 100)}`;
  } else if (((latestStatus.cameras || {})[enlargedCamera] || {}).receiving) {
    source = `/api/camera/stream/${enlargedCamera}`;
  }
  if (source) {
    if (image.dataset.source !== source) {
      image.dataset.source = source;
      image.src = source;
    }
    image.classList.add("active");
  } else {
    image.classList.remove("active");
    image.removeAttribute("src");
    image.dataset.source = "";
    empty.textContent = "카메라 테스트 또는 텔레옵을 먼저 시작하세요.";
  }
}

function closeCameraEnlarge() {
  enlargedCamera = null;
  el("camera-enlarge").classList.remove("open");
  el("camera-enlarge").setAttribute("aria-hidden", "true");
  el("camera-enlarge-image").removeAttribute("src");
  el("camera-enlarge-image").classList.remove("active");
  if (document.fullscreenElement) document.exitFullscreen();
}

function selectedTracking() {
  const checked = document.querySelector('input[name="tracking-mode"]:checked');
  return checked ? checked.value : "joint";
}

function askMode(mode) {
  if (["record", "record-new"].includes(mode)) {
    const seconds = Number(el("episode-time").value);
    if (!Number.isInteger(seconds) || seconds < 5 || seconds > 300) {
      toast("에피소드 시간은 5~300초 사이의 정수로 입력하세요.", true);
      el("episode-time").focus();
      return;
    }
  }
  selectedMode = mode;
  const labels = { teleop: "텔레옵 시작", record: "데이터 수집 준비", "record-new": "새 수집 세션 시작", init: "초기 자세 복귀" };
  const dialog = el("confirm-dialog");
  const trackingLabel = selectedTracking() === "endpoint" ? "Endpoint 추적" : "관절값 추적";
  el("dialog-title").textContent = ["teleop", "record", "record-new"].includes(mode)
    ? `${labels[mode]} (${trackingLabel})`
    : labels[mode];
  const endpointNote = selectedTracking() === "endpoint"
    ? " Endpoint 추적: GELLO TCP만 추종하고 관절 궤적은 xArm planning이 결정합니다. 첫 3초는 TCP 20mm/s입니다."
    : "";
  const messages = {
    teleop: `기존 모드를 종료하고 초기 자세로 자동 복귀한 뒤 텔레옵을 시작합니다.${endpointNote}`,
    record: `기존 모드를 종료하고 초기 자세로 자동 복귀한 뒤 ${el("episode-time").value}초 에피소드의 새 데이터 수집 세션을 준비합니다.${endpointNote}`,
    "record-new": `실행 중인 수집이 있으면 정상 종료한 뒤, 초기 자세 복귀 후 ${el("episode-time").value}초 에피소드의 새 data/날짜/session_NNN 세션을 만듭니다. 기존 세션은 덮어쓰지 않습니다.${endpointNote}`,
    init: "팔 관절이 8°/s로 초기 자세까지 실제 이동합니다. 그리퍼는 움직이지 않습니다.",
    camera: "카메라만 연결하며 로봇에는 명령을 보내지 않습니다.",
  };
  el("dialog-message").textContent = messages[mode];
  const needsSafety = mode !== "camera";
  el("safety-check").checked = !needsSafety;
  el("safety-check").disabled = !needsSafety;
  el("dialog-confirm").disabled = needsSafety;
  el("dialog-confirm").textContent = needsSafety ? "3초 안전 절차 시작" : "카메라 보기 시작";
  dialog.showModal();
}

function populateReplayEpisodes() {
  const dataset = replayCatalog.find((item) => item.key === el("replay-dataset").value);
  const episodeSelect = el("replay-episode");
  episodeSelect.textContent = "";
  if (!dataset) {
    episodeSelect.disabled = true;
    el("replay-start").disabled = true;
    return;
  }
  for (let index = 0; index < dataset.episodes; index += 1) {
    const option = document.createElement("option");
    option.value = String(index);
    const trackingLabel = dataset.tracking === "endpoint" ? "Endpoint 추적" : "관절값 추적";
    option.textContent = `성공 시연 ${index + 1} (번호 ${index}) · ${trackingLabel}`;
    episodeSelect.append(option);
  }
  episodeSelect.disabled = false;
  el("replay-start").disabled = false;
  el("replay-hint").textContent = "재생 전 현재 관절·그리퍼 시작 상태, 오류 0, 작업영역 확인을 모두 검사합니다.";
}

async function loadReplayCatalog() {
  try {
    const response = await fetch("/api/replay/catalog");
    const result = await response.json();
    replayCatalog = result.ok ? result.datasets : [];
    const datasetSelect = el("replay-dataset");
    datasetSelect.textContent = "";
    for (const dataset of replayCatalog) {
      const option = document.createElement("option");
      option.value = dataset.key;
      option.textContent = dataset.label;
      datasetSelect.append(option);
    }
    datasetSelect.disabled = replayCatalog.length === 0;
    if (!replayCatalog.length) {
      el("replay-hint").textContent = "재생 가능한 xArm 성공 시연 세션을 찾지 못했습니다.";
      return;
    }
    populateReplayEpisodes();
  } catch (_) {
    el("replay-hint").textContent = "성공 시연 목록을 불러오지 못했습니다. GUI를 다시 열어주세요.";
  }
}

async function loadResumeCatalog() {
  try {
    const response = await fetch("/api/record/catalog");
    const result = await response.json();
    resumeCatalog = result.ok ? result.sessions : [];
    const select = el("resume-session");
    select.textContent = "";
    for (const session of resumeCatalog) {
      const option = document.createElement("option");
      option.value = session.key;
      option.textContent = session.label;
      select.append(option);
    }
    select.disabled = resumeCatalog.length === 0;
    el("resume-start").disabled = resumeCatalog.length === 0;
  } catch (_) { /* 상태 폴링이 연결 문제를 표시한다. */ }
}

async function waitForServerRestart() {
  const conn = el("connection");
  conn.textContent = "GUI 서버 재시작 중...";
  conn.className = "pill muted";
  let wentDown = false;
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (response.ok && wentDown) {
        window.location.reload();
        return;
      }
      if (response.ok && !wentDown) continue; // 아직 옛 서버가 종료 전
    } catch (_) {
      wentDown = true; // 옛 서버가 내려감 → 새 서버 기동 대기
    }
  }
  conn.textContent = "재시작 확인 실패: 페이지를 수동 새로고침하세요";
  conn.className = "pill bad";
}

function askRestart() {
  selectedMode = "server-restart";
  const dialog = el("confirm-dialog");
  el("dialog-title").textContent = "GUI 서버 재시작";
  el("dialog-message").textContent =
    "실행 중인 텔레옵/녹화 모드를 안전하게 정리한 뒤 GUI 서버 프로세스를 새로 시작합니다. " +
    "로봇에는 새 모션 명령을 보내지 않으며, 완료되면 이 화면이 자동으로 다시 연결됩니다.";
  el("safety-check").checked = true;
  el("safety-check").disabled = true;
  el("dialog-confirm").disabled = false;
  el("dialog-confirm").textContent = "재시작";
  dialog.showModal();
}

function askResume() {
  const session = resumeCatalog.find((item) => item.key === el("resume-session").value);
  if (!session) {
    toast("먼저 이어서 수집할 세션을 선택하세요.", true);
    return;
  }
  selectedMode = "record-resume";
  const dialog = el("confirm-dialog");
  el("dialog-title").textContent = `세션 이어서 수집: ${session.key}`;
  el("dialog-message").textContent =
    `저장된 ${session.episodes}개 에피소드 뒤에 새 에피소드를 추가합니다. ` +
    `추적 모드는 이 세션이 만들어질 때의 설정(${session.tracking === "endpoint" ? "Endpoint" : "관절값"} 추적)을 그대로 사용하며, ` +
    "기존 모드 종료와 초기 자세 복귀 후 시작됩니다.";
  el("safety-check").checked = false;
  el("safety-check").disabled = false;
  el("dialog-confirm").disabled = true;
  el("dialog-confirm").textContent = "이어서 수집 시작";
  dialog.showModal();
}

function askReplay() {
  const dataset = el("replay-dataset").value;
  const episode = el("replay-episode").value;
  if (!dataset || episode === "") {
    toast("먼저 데이터 수집 세션과 성공 시연 번호를 선택하세요.", true);
    return;
  }
  selectedMode = "replay";
  const dialog = el("confirm-dialog");
  el("dialog-title").textContent = "선택한 성공 시연 재생 (원본 1배속)";
  el("dialog-message").textContent = "선택한 관절·그리퍼 action을 원본 30fps로 실제 로봇에 보냅니다. 현재 자세가 첫 프레임과 2° 이내이고 오류가 0일 때만 시작됩니다.";
  el("safety-check").checked = false;
  el("safety-check").disabled = false;
  el("dialog-confirm").disabled = true;
  el("dialog-confirm").textContent = "3초 안전 대기 후 1배속 재생";
  dialog.showModal();
}

el("safety-check").addEventListener("change", (event) => { el("dialog-confirm").disabled = !event.target.checked; });
el("confirm-dialog").addEventListener("close", async () => {
  if (el("confirm-dialog").returnValue === "confirm" && selectedMode) {
    if (selectedMode === "replay") {
      await api("/api/replay", { dataset: el("replay-dataset").value, episode: Number(el("replay-episode").value) });
    } else if (selectedMode === "record-resume") {
      await api("/api/record/resume", { session: el("resume-session").value });
    } else if (selectedMode === "server-restart") {
      const result = await api("/api/restart");
      if (result.ok) waitForServerRestart();
    } else {
      // "새 세션 시작"은 record 모드 재시작과 같다. run.sh record가 실행될 때마다
      // prepare_record_session.py가 새 session_NNN을 예약한다.
      const target = selectedMode === "record-new" ? "record" : selectedMode;
      await api("/api/mode", { target, tracking: selectedTracking(), episode_time: Number(el("episode-time").value) });
    }
  }
  selectedMode = null;
});

document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => askMode(button.dataset.mode)));
document.querySelectorAll("[data-camera-start]").forEach((button) => button.addEventListener("click", () => api("/api/camera/start", { camera: button.dataset.cameraStart })));
document.querySelectorAll("[data-camera-stop]").forEach((button) => button.addEventListener("click", () => api("/api/camera/stop", { camera: button.dataset.cameraStop })));
document.querySelectorAll("[data-camera-enlarge]").forEach((button) => button.addEventListener("click", () => openCameraEnlarge(button.dataset.cameraEnlarge)));
document.querySelector('[data-action="doctor"]').addEventListener("click", () => api("/api/doctor"));
document.querySelector('[data-action="restart"]').addEventListener("click", askRestart);
document.querySelector('[data-action="stop"]').addEventListener("click", () => api("/api/stop"));
document.querySelectorAll('[data-action="focus-open"]').forEach((button) => button.addEventListener("click", openFocusMode));
document.querySelector('[data-action="focus-close"]').addEventListener("click", closeFocusMode);
document.querySelector('[data-action="focus-fullscreen"]').addEventListener("click", () => {
  if (!document.fullscreenElement) el("focus-mode").requestFullscreen();
  else document.exitFullscreen();
});
document.querySelector('[data-action="focus-stop"]').addEventListener("click", () => api("/api/stop"));
document.querySelectorAll("[data-focus-mode]").forEach((button) => button.addEventListener("click", () => {
  syncFocusSettingsToMain();
  askMode(button.dataset.focusMode);
}));
el("focus-episode-time").addEventListener("input", () => { el("episode-time").value = el("focus-episode-time").value; });
el("episode-time").addEventListener("input", () => { el("focus-episode-time").value = el("episode-time").value; });
document.querySelectorAll('input[name="focus-tracking-mode"]').forEach((radio) => radio.addEventListener("change", syncFocusSettingsToMain));
document.querySelectorAll('input[name="tracking-mode"]').forEach((radio) => radio.addEventListener("change", syncMainSettingsToFocus));
document.querySelector('[data-action="camera-enlarge-close"]').addEventListener("click", closeCameraEnlarge);
document.querySelector('[data-action="camera-enlarge-fullscreen"]').addEventListener("click", () => {
  if (!document.fullscreenElement) el("camera-enlarge").requestFullscreen();
  else document.exitFullscreen();
});
document.querySelector('[data-action="c31-start"]').addEventListener("click", () => api("/api/c31/start"));
document.querySelector('[data-action="c31-clear"]').addEventListener("click", () => api("/api/c31/continue", { stage: "clear" }));
document.querySelector('[data-action="c31-return"]').addEventListener("click", () => api("/api/c31/continue", { stage: "return" }));
document.querySelector('[data-action="c19-start"]').addEventListener("click", () => api("/api/c19/start"));
document.querySelector('[data-action="c19-check"]').addEventListener("click", () => api("/api/c19/continue"));
document.querySelector('[data-action="c1-start"]').addEventListener("click", () => api("/api/c1/start"));
document.querySelector('[data-action="c1-release"]').addEventListener("click", () => api("/api/c1/continue", { stage: "release" }));
document.querySelector('[data-action="c1-return"]').addEventListener("click", () => api("/api/c1/continue", { stage: "return" }));
document.querySelectorAll("[data-key]").forEach((button) => button.addEventListener("click", () => api("/api/record-key", { key: button.dataset.key })));
el("replay-dataset").addEventListener("change", populateReplayEpisodes);
el("replay-start").addEventListener("click", askReplay);
el("resume-start").addEventListener("click", askResume);
el("clear-log").addEventListener("click", () => { el("log").textContent = ""; });

window.addEventListener("keydown", (event) => {
  if (!focusOpen || event.target.matches("input, textarea, select")) return;
  const mode = latestStatus ? latestStatus.mode : "idle";
  if (mode === "record") {
    const keyMap = { " ": "space", ArrowRight: "right", ArrowLeft: "left", Escape: "esc" };
    const key = keyMap[event.key];
    if (!key || !latestStatus.record_ready) return;
    event.preventDefault();
    api("/api/record-key", { key });
  } else if (mode === "teleop" && event.key === " ") {
    event.preventDefault();
    api("/api/stop");
  }
});

pollStatus(); pollLogs(); heartbeat(); loadReplayCatalog(); loadResumeCatalog();
window.setInterval(pollStatus, 1000);
window.setInterval(pollLogs, 700);
window.setInterval(heartbeat, 3000);
window.setInterval(() => { if (focusOpen && latestStatus) updateFocusMode(latestStatus); }, 200);
window.setInterval(() => { if (enlargedCamera) updateEnlargedCamera(); }, 100);
// 새 세션/에피소드가 생기면 드롭다운 목록도 따라와야 한다.
window.setInterval(loadReplayCatalog, 15000);
window.setInterval(loadResumeCatalog, 15000);

// [room-main.js] 멀티플레이 화면 시작점 — API 주소 결정, 게스트 토큰, 서버 요청 도우미, 화면 mount
import { FunctionComponent } from "../core/component.js";
import { RoomApp } from "./RoomApp.js";
import { guestStorageKey, normalizeCode, resolveApiBase } from "./roomLogic.js";

const API = resolveApiBase(location, document.querySelector('meta[name="poker-api-base"]')?.content);
const GUEST_KEY = guestStorageKey(location.search);
let guest = null; // { guest_token, display_name } — 토큰은 이 브라우저에만 있고, 서버는 해시만 저장한다

function createGuestToken() {
  if (!globalThis.crypto?.getRandomValues) throw new Error("이 브라우저는 안전한 게스트 토큰을 만들 수 없습니다.");
  const bytes = new Uint8Array(32);
  globalThis.crypto.getRandomValues(bytes);
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function loadGuest() {
  try {
    const saved = JSON.parse(localStorage.getItem(GUEST_KEY) || "null");
    if (saved && typeof saved.guest_token === "string" && /^[A-Za-z0-9_-]{43,128}$/.test(saved.guest_token) && typeof saved.display_name === "string") return saved;
  } catch { /* 깨진 저장값은 무시하고 새로 만든다 */ }
  return null;
}

async function readJson(response) {
  let result;
  try {
    result = await response.json();
  } catch {
    result = {};
  }
  if (!response.ok) throw Object.assign(new Error(result.message || result.error || "요청 실패 (" + response.status + ")"), { payload: result, status: response.status });
  return result;
}

const client = {
  api: API,
  // body가 있으면 POST, 없으면 GET. 서버에 닿지 못하면 status 없는 오류가 난다(재시도 가능 여부 판단에 쓴다)
  async request(path, body, signal) {
    const headers = { "Content-Type": "application/json" };
    if (guest) headers.Authorization = "Bearer " + guest.guest_token;
    const response = await fetch(API + path, { method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined, signal });
    return readJson(response);
  },
  // 닉네임 등록(같은 토큰·같은 이름이면 몇 번을 보내도 같은 계정) → 저장된 이름
  async signIn(name) {
    const candidate = { guest_token: guest?.guest_token || loadGuest()?.guest_token || createGuestToken(), display_name: name };
    let response;
    try {
      response = await fetch(API + "/api/guest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(candidate) });
    } catch {
      throw new Error("서버(" + API + ")에 연결할 수 없습니다. 서버가 켜져 있는지, 주소가 맞는지 확인하세요.");
    }
    try {
      await readJson(response);
    } catch (error) {
      if (error.payload?.error === "guest_name_immutable") throw new Error("이 브라우저의 게스트는 이미 다른 닉네임으로 등록돼 있습니다. 닉네임은 바꿀 수 없습니다.");
      throw error;
    }
    guest = candidate;
    localStorage.setItem(GUEST_KEY, JSON.stringify(guest));
    return name;
  },
  rememberRoom(code) {
    history.replaceState(null, "", location.pathname + location.search + "#room=" + code);
  },
  forgetRoom() {
    history.replaceState(null, "", location.pathname + location.search);
  },
};

async function start() {
  const root = document.getElementById("root");
  const initialCode = normalizeCode((location.hash.match(/room=([A-Za-z0-9]+)/) || [])[1] || "");
  const saved = loadGuest();
  let initialName = "";
  let startError = "";
  if (saved) {
    try {
      guest = saved;
      initialName = await client.signIn(saved.display_name);
    } catch (error) {
      guest = null;
      startError = error.message;
    }
  }
  root.textContent = "";
  new FunctionComponent(RoomApp, root, { client, initialName, initialCode, startError }).mount();
}

start();

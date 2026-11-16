import { FunctionComponent } from "../core/component.js";
import { PokerApp } from "./PokerApp.js?v=cyber-ui-3";

const API = document.querySelector('meta[name="poker-api-base"]')?.content?.trim().replace(/\/+$/, "");
const GUEST_KEY = "poker-lab.guest.v1";

function createGuestToken() {
  if (!globalThis.crypto?.getRandomValues) throw new Error("이 브라우저는 안전한 게스트 토큰을 만들 수 없습니다.");
  const bytes = new Uint8Array(32);
  globalThis.crypto.getRandomValues(bytes);
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function loadOrCreateGuest() {
  try {
    const saved = JSON.parse(localStorage.getItem(GUEST_KEY) || "null");
    if (saved && typeof saved.guest_token === "string" && /^[A-Za-z0-9_-]{43,128}$/.test(saved.guest_token)) return saved;
  } catch { /* corrupted local preferences are replaced with a new guest identity */ }
  const guest = { guest_token: createGuestToken(), display_name: "Guest Player" };
  localStorage.setItem(GUEST_KEY, JSON.stringify(guest));
  return guest;
}

async function readJson(response) {
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(result.message || result.error || "요청 실패"), { payload: result, status: response.status });
  return result;
}

async function initialize() {
  if (!API) throw new Error("poker-api-base 설정이 없습니다.");
  const guest = loadOrCreateGuest();
  const registration = await readJson(await fetch(API + "/api/guest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(guest),
  }));

  async function request(path, body) {
    const response = await fetch(API + path, {
      method: body ? "POST" : "GET",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + guest.guest_token,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    return readJson(response);
  }

  const profileResult = await request("/api/profile");
  const gameResult = await request("/api/game");
  return { request, profile: profileResult.profile, game: gameResult.game, traces: gameResult.traces || registration.traces || [] };
}

const root = document.getElementById("root");
root.textContent = "게스트 프로필과 저장된 게임 기록을 불러오는 중…";
initialize().then(({ request, profile, game, traces }) => {
  root.textContent = "";
  new FunctionComponent(PokerApp, root, { request, profile, initialGame: game, initialTraces: traces }).mount();
}).catch((error) => {
  root.textContent = "Poker Lab 연결 실패: " + error.message + " · Mini DBMS, Mini Redis, Poker API가 실행 중인지 확인하세요.";
});

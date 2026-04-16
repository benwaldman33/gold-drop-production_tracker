const memory = new Map();

export function readJson(key, fallback) {
  try {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(key) : memory.get(key);
    if (!raw) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function writeJson(key, value) {
  const raw = JSON.stringify(value);
  if (typeof window !== "undefined") {
    window.localStorage.setItem(key, raw);
    return;
  }
  memory.set(key, raw);
}

export function removeValue(key) {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(key);
    return;
  }
  memory.delete(key);
}

export function resetStorage() {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem("gold-drop-purchasing-agent-state-v1");
    window.localStorage.removeItem("gold-drop-purchasing-agent-session-v1");
    return;
  }
  memory.clear();
}

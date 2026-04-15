export function getAppConfig() {
  const fallback = {
    mode: "mock",
    apiBaseUrl: "",
    appName: "Gold Drop Receiving Intake",
  };
  if (typeof window === "undefined") return fallback;
  return { ...fallback, ...(window.__RECEIVING_APP_CONFIG__ || {}) };
}

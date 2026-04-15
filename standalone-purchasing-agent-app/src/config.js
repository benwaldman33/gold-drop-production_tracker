export function getAppConfig() {
  const fallback = {
    mode: "mock",
    apiBaseUrl: "",
    appName: "Gold Drop Purchasing Agent",
  };
  if (typeof window === "undefined") return fallback;
  return { ...fallback, ...(window.__PURCHASING_APP_CONFIG__ || {}) };
}

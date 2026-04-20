export function getAppConfig() {
  const fallback = {
    mode: "mock",
    apiBaseUrl: "",
    appName: "Gold Drop Extraction Lab",
  };
  if (typeof window === "undefined") return fallback;
  return { ...fallback, ...(window.__EXTRACTION_APP_CONFIG__ || {}) };
}

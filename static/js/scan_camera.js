(function () {
  const config = window.goldDropScanConfig || {};
  const video = document.getElementById("scan-video");
  const emptyState = document.getElementById("scan-preview-empty");
  const statusText = document.getElementById("scan-status-text");
  const startBtn = document.getElementById("scan-start-btn");
  const stopBtn = document.getElementById("scan-stop-btn");
  const manualForm = document.getElementById("scan-manual-form");
  const manualInput = document.getElementById("tracking-id-input");

  if (!video || !statusText || !startBtn || !stopBtn || !manualForm || !manualInput) {
    return;
  }

  let stream = null;
  let detector = null;
  let scanTimer = null;
  let lastValue = null;

  function setStatus(message) {
    statusText.textContent = message;
  }

  function lotUrlForValue(rawValue) {
    const value = (rawValue || "").trim();
    if (!value) return "";
    if (/^https?:\/\//i.test(value)) return value;
    if (value.startsWith("/scan/lot/")) return value;
    return (config.scanLotBase || "/scan/lot/__TRACKING_ID__").replace("__TRACKING_ID__", encodeURIComponent(value));
  }

  function stopCamera() {
    if (scanTimer) {
      window.clearTimeout(scanTimer);
      scanTimer = null;
    }
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
    video.srcObject = null;
    video.removeAttribute("data-live");
    emptyState.hidden = false;
    stopBtn.disabled = true;
    startBtn.disabled = false;
    setStatus("Camera scan is idle.");
  }

  async function scanFrame() {
    if (!detector || !video.srcObject) {
      return;
    }
    try {
      const barcodes = await detector.detect(video);
      if (Array.isArray(barcodes) && barcodes.length > 0) {
        const rawValue = (barcodes[0].rawValue || "").trim();
        if (rawValue && rawValue !== lastValue) {
          lastValue = rawValue;
          setStatus(`Scanned ${rawValue}. Opening lot...`);
          window.location.assign(lotUrlForValue(rawValue));
          return;
        }
      }
    } catch (error) {
      setStatus(`Camera scan error: ${error.message || "unknown error"}`);
      stopCamera();
      return;
    }
    scanTimer = window.setTimeout(scanFrame, 250);
  }

  async function startCamera() {
    if (!("mediaDevices" in navigator) || !navigator.mediaDevices.getUserMedia) {
      setStatus("This browser does not expose camera access. Use the manual field instead.");
      return;
    }
    if (!("BarcodeDetector" in window)) {
      setStatus("Barcode scanning is not supported in this browser. Use the manual field or a Bluetooth scanner.");
      return;
    }
    try {
      detector = new window.BarcodeDetector({ formats: ["code_39", "code_128", "qr_code"] });
    } catch (error) {
      setStatus("This browser cannot initialize barcode detection. Use the manual field instead.");
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      video.srcObject = stream;
      await video.play();
      video.dataset.live = "1";
      emptyState.hidden = true;
      startBtn.disabled = true;
      stopBtn.disabled = false;
      setStatus("Camera live. Point it at a lot barcode or QR code.");
      scanFrame();
    } catch (error) {
      setStatus(`Unable to start camera: ${error.message || "permission denied"}`);
      stopCamera();
    }
  }

  startBtn.addEventListener("click", function () {
    startCamera();
  });

  stopBtn.addEventListener("click", function () {
    stopCamera();
  });

  manualForm.addEventListener("submit", function (event) {
    event.preventDefault();
    const value = manualInput.value.trim();
    if (!value) {
      setStatus("Enter a tracking ID before opening the lot.");
      manualInput.focus();
      return;
    }
    window.location.assign(lotUrlForValue(value));
  });

  window.addEventListener("beforeunload", stopCamera);
})();

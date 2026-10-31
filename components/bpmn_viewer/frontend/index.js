const MIN_ZOOM = 0.2;
const MAX_ZOOM = 4;
const STEP = 1.2;

const post = (type, payload = {}) => {
  window.parent.postMessage({ isStreamlitMessage: true, type, ...payload }, "*");
};
const $ = (selector) => document.querySelector(selector);

const app = $("#app");
const canvasElement = $("#canvas");
const message = $("#message");
const zoomLabel = $("#zoom-level");
const downloadButtons = [$("#download-svg"), $("#download-bpmn")];

let viewer = null;
let currentXml = null;
let fileName = "process";
let frameHeight = 0;
let userAdjusted = false;

const showMessage = (text) => {
  message.textContent = text || "";
  message.classList.toggle("visible", Boolean(text));
};

const setHeight = (height) => {
  if (!height || height === frameHeight) return;
  frameHeight = height;
  app.style.height = `${height}px`;
  post("streamlit:setFrameHeight", { height });
  if (viewer) viewer.get("canvas").resized();
};

const clamp = (value) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));

const zoomTo = (scale, center) => {
  if (!viewer) return;
  userAdjusted = true;
  viewer.get("canvas").zoom(clamp(scale), center || "auto");
};

const fit = () => {
  if (!viewer) return;
  userAdjusted = false;
  const canvas = viewer.get("canvas");
  canvas.zoom("fit-viewport", "auto");
  if (canvas.zoom() > 1) canvas.zoom(1, "auto");
};

const download = (content, type, extension) => {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = Object.assign(document.createElement("a"), { href: url, download: `${fileName}.${extension}` });
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

const render = async (xml) => {
  if (!viewer || xml === currentXml) return;
  currentXml = xml;
  downloadButtons.forEach((button) => (button.disabled = true));
  if (!xml) {
    viewer.clear();
    showMessage("");
    return;
  }
  try {
    const { warnings } = await viewer.importXML(xml);
    if (xml !== currentXml) return;
    if (warnings && warnings.length) console.warn("bpmn-js import warnings", warnings);
    fit();
    showMessage("");
    downloadButtons.forEach((button) => (button.disabled = false));
  } catch (error) {
    showMessage(`Unable to render this diagram: ${error.message}`);
  }
};

if (!window.BpmnJS) {
  showMessage("The diagram viewer could not be loaded. Check your connection to cdn.jsdelivr.net.");
} else {
  viewer = new window.BpmnJS({ container: canvasElement });
  viewer.on("canvas.viewbox.changed", ({ viewbox }) => {
    zoomLabel.textContent = `${Math.round(viewbox.scale * 100)}%`;
  });

  // Plain mouse-wheel zooms around the cursor; Shift+wheel pans horizontally.
  canvasElement.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      event.stopPropagation();
      const canvas = viewer.get("canvas");
      if (event.shiftKey) {
        userAdjusted = true;
        canvas.scroll({ dx: -(event.deltaY || event.deltaX), dy: 0 });
        return;
      }
      const rect = canvasElement.getBoundingClientRect();
      const unit = event.deltaMode === 1 ? 0.05 : 0.0015;
      const factor = Math.exp(-event.deltaY * unit);
      zoomTo(canvas.zoom() * factor, { x: event.clientX - rect.left, y: event.clientY - rect.top });
    },
    { passive: false, capture: true },
  );

  $("#zoom-in").addEventListener("click", () => zoomTo(viewer.get("canvas").zoom() * STEP));
  $("#zoom-out").addEventListener("click", () => zoomTo(viewer.get("canvas").zoom() / STEP));
  $("#zoom-level").addEventListener("click", () => zoomTo(1));
  $("#fit").addEventListener("click", fit);
  $("#download-svg").addEventListener("click", async () => {
    const { svg } = await viewer.saveSVG();
    download(svg, "image/svg+xml", "svg");
  });
  $("#download-bpmn").addEventListener("click", async () => {
    const { xml } = await viewer.saveXML({ format: true });
    download(xml, "application/xml", "bpmn");
  });
  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const canvas = viewer.get("canvas");
    if (event.key === "+" || event.key === "=") zoomTo(canvas.zoom() * STEP);
    else if (event.key === "-") zoomTo(canvas.zoom() / STEP);
    else if (event.key === "0") zoomTo(1);
    else if (event.key === "f" || event.key === "F") fit();
  });
  canvasElement.addEventListener("mousedown", () => (userAdjusted = true));
  window.addEventListener("resize", () => {
    viewer.get("canvas").resized();
    if (!userAdjusted && currentXml) fit();
  });
}

window.addEventListener("message", (event) => {
  const data = event.data;
  if (!data || data.type !== "streamlit:render" || !data.args) return;
  const { xml, height, file_name: name, theme } = data.args;
  const accent = (data.theme && data.theme.primaryColor) || (theme && theme.primaryColor);
  if (accent) document.documentElement.style.setProperty("--accent", accent);
  fileName = (name || "process").replace(/[^\w.-]+/g, "_");
  setHeight(height || 600);
  render(xml || null);
});

post("streamlit:componentReady", { apiVersion: 1 });

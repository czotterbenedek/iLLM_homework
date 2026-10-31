const post = (type, payload = {}) => {
  window.parent.postMessage(
    { isStreamlitMessage: true, type, ...payload },
    "*",
  );
};

const viewer = new window.BpmnJS({ container: "#canvas" });
post("streamlit:componentReady", { apiVersion: 1 });
post("streamlit:setFrameHeight", { height: 540 });
window.addEventListener("message", async (event) => {
  const data = event.data;
  if (!data || !data.args || !data.args.xml) return;
  try {
    await viewer.importXML(data.args.xml);
    viewer.get("canvas").zoom("fit-viewport");
    const { svg } = await viewer.saveSVG();
    post("streamlit:setComponentValue", { value: svg });
  } catch (error) {
    document.querySelector("#error").textContent = `Unable to render BPMN: ${error.message}`;
    post("streamlit:setComponentValue", { value: { error: error.message } });
  }
});

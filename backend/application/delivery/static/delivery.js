/* Checkout de entrega: máscara de CPF, captura do documento (câmera ou arquivo) e contagem do código. */
(function () {
  const cpf = document.querySelector("input[name=cpf]");
  if (cpf) cpf.addEventListener("input", () => {
    const d = cpf.value.replace(/\D/g, "").slice(0, 11);
    cpf.value = d.replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d{1,2})$/, "$1-$2");
  });

  const input = document.getElementById("document");
  const preview = document.getElementById("doc-preview");
  function show(file) {
    if (!preview || !file) return;
    preview.src = URL.createObjectURL(file); preview.hidden = false;
  }
  function setFile(file) {
    const dt = new DataTransfer(); dt.items.add(file); input.files = dt.files; show(file);
  }
  if (input) input.addEventListener("change", () => show(input.files[0]));

  const open = document.getElementById("cam-open"), box = document.getElementById("cam-box");
  const video = document.getElementById("cam-video"), shot = document.getElementById("cam-shot"), close = document.getElementById("cam-close");
  const fallback = document.getElementById("document-capture");
  let stream = null;
  function stop() { if (stream) stream.getTracks().forEach(t => t.stop()); stream = null; if (box) box.hidden = true; }
  if (fallback) fallback.addEventListener("change", () => fallback.files[0] && setFile(fallback.files[0]));
  if (open) open.addEventListener("click", async () => {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("sem câmera");
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      video.srcObject = stream; box.hidden = false;
    } catch (e) {   // sem HTTPS/permissão: usa o seletor nativo (no celular abre a câmera)
      if (fallback) fallback.click();
    }
  });
  if (close) close.addEventListener("click", stop);
  if (shot) shot.addEventListener("click", () => {
    const c = document.createElement("canvas"); c.width = video.videoWidth || 1280; c.height = video.videoHeight || 720;
    c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
    c.toBlob(blob => { if (blob) setFile(new File([blob], "documento-capturado.jpg", { type: "image/jpeg" })); stop(); }, "image/jpeg", 0.9);
  });

  const timer = document.getElementById("code-timer");
  if (timer) {
    const end = new Date(timer.dataset.expires).getTime();
    const tick = () => {
      const s = Math.max(0, Math.round((end - Date.now()) / 1000));
      timer.textContent = s > 0 ? `expira em ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "código expirado — reenvie um novo";
      timer.className = s > 0 ? "badge warn" : "badge lost";
    };
    tick(); setInterval(tick, 1000);
  }
})();

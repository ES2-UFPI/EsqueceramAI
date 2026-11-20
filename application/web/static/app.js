/* Ações do painel: chamam a API REST (cookie de sessão) e recarregam a página. */
(function () {
  function initToasts() {
    const box = document.createElement("div");
    box.className = "toasts";
    document.body.appendChild(box);

    function toast(title, desc, bad) {
      const t = document.createElement("div");
      t.className = "toast" + (bad ? " bad" : "");
      t.innerHTML = "<b></b>" + (desc ? "<small></small>" : "");
      t.querySelector("b").textContent = title;
      if (desc) t.querySelector("small").textContent = desc;
      box.appendChild(t);
      setTimeout(() => t.remove(), 4500);
    }

    window.toast = toast;
    document.querySelectorAll(".flash").forEach((f) => toast(f.dataset.msg, "", f.dataset.tone === "error"));
    try {
      const msg = sessionStorage.getItem("toast");
      if (msg) {
        sessionStorage.removeItem("toast");
        toast(msg);
      }
    } catch (e) {}
    return toast;
  }

  async function apiCall(url, method, body) {
    const resp = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(payload.error || "Não foi possível concluir a ação.");
    return payload;
  }

  function initApiActions(toast) {
    document.addEventListener("click", async (ev) => {
      const btn = ev.target.closest("[data-api]");
      if (!btn) return;
      ev.preventDefault();
      if (btn.dataset.confirm && !window.confirm(btn.dataset.confirm)) return;
      btn.disabled = true;
      try {
        await apiCall(btn.dataset.api, btn.dataset.method || "POST", btn.dataset.body ? JSON.parse(btn.dataset.body) : null);
        try {
          sessionStorage.setItem("toast", btn.dataset.success || "Ação concluída");
        } catch (e) {}
        if (btn.dataset.redirect) location.href = btn.dataset.redirect;
        else location.reload();
      } catch (e) {
        toast("Algo deu errado", e.message, true);
        btn.disabled = false;
      }
    });
  }

  function initRoleSelector(toast) {
    document.addEventListener("change", async (ev) => {
      const select = ev.target.closest("[data-role-user]");
      if (!select) return;
      try {
        await apiCall("/api/admin/users", "PATCH", { userId: +select.dataset.roleUser, role: select.value });
        toast("Permissão atualizada", "Novo papel: " + select.value);
      } catch (e) {
        toast("Não foi possível alterar", e.message, true);
        location.reload();
      }
    });
  }

  // Preenche latitude/longitude pelo GPS ou por um ponto de coleta
  function initGeoLocation() {
    function geoBox(el) {
      const box = el.closest("[data-geo-box]");
      return { form: el.closest("form"), status: box && box.querySelector("[data-geo-status]") };
    }

    function geoSay(el, text) {
      const { status } = geoBox(el);
      if (status) status.textContent = text;
    }

    function geoApply(el, lat, lng) {
      const { form } = geoBox(el);
      const btn = form.querySelector("[data-geo-locate]") || el;
      const latEl = form.elements[btn.dataset.geoLatName || "lat"];
      const lngEl = form.elements[btn.dataset.geoLngName || "lng"];
      latEl.value = Number(lat).toFixed(6);
      lngEl.value = Number(lng).toFixed(6);
      if (form.elements.raio) {
        // formulário de busca: define raio e ordem padrão e já pesquisa
        if (!form.elements.raio.value) form.elements.raio.value = "1";
        if (form.elements.ordem) form.elements.ordem.value = "proximity";
        form.requestSubmit();
      }
    }

    document.addEventListener("click", (ev) => {
      const clear = ev.target.closest("[data-geo-clear]");
      if (clear) {
        ev.preventDefault();
        const { form } = geoBox(clear);
        form.elements.lat.value = "";
        form.elements.lng.value = "";
        form.elements.raio.value = "";
        form.requestSubmit();
        return;
      }
      const btn = ev.target.closest("[data-geo-locate]");
      if (!btn) return;
      if (!navigator.geolocation) {
        geoSay(btn, "Seu navegador não permite obter a localização.");
        return;
      }
      btn.disabled = true;
      geoSay(btn, "Obtendo localização…");
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          geoSay(btn, "Localização preenchida (precisão de cerca de " + Math.round(pos.coords.accuracy) + " m).");
          btn.disabled = false;
          geoApply(btn, pos.coords.latitude, pos.coords.longitude);
        },
        (err) => {
          geoSay(
            btn,
            err.code === 1
              ? "Permissão negada. Informe as coordenadas ou escolha um ponto de coleta."
              : "Não foi possível obter a localização."
          );
          btn.disabled = false;
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
      );
    });

    document.addEventListener("change", (ev) => {
      const sel = ev.target.closest("[data-geo-point]");
      if (!sel || !sel.value) return;
      const opt = sel.selectedOptions[0];
      geoApply(sel, opt.dataset.lat, opt.dataset.lng);
    });
  }

  function initDynamicFormFields() {
    // Campos dinâmicos por categoria no formulário de item
    const categorySelect = document.querySelector("[data-category-select]");
    if (categorySelect) {
      const syncCategory = () =>
        document.querySelectorAll("[data-category-group]").forEach((group) => {
          const on = group.dataset.categoryGroup === categorySelect.value;
          group.hidden = !on;
          group.querySelectorAll("input").forEach((input) => (input.disabled = !on));
        });
      categorySelect.addEventListener("change", syncCategory);
      syncCategory();
    }

    // Validação de posse só existe para itens encontrados
    const secretBox = document.querySelector("[data-secret-box]");
    if (secretBox) {
      const syncSecret = () => {
        const found = document.querySelector("[data-record-type][value='FOUND']");
        const on = !found || found.checked;
        secretBox.hidden = !on;
        secretBox.querySelectorAll("input, textarea").forEach((input) => (input.disabled = !on));
      };
      document.querySelectorAll("[data-record-type]").forEach((radio) => radio.addEventListener("change", syncSecret));
      syncSecret();
    }
  }

  // Menu retrátil no mobile (drawer do painel e menu do cabeçalho público)
  function initMobileDrawers() {
    const drawer = document.querySelector("[data-drawer]");
    const backdrop = document.querySelector("[data-drawer-backdrop]");
    const setDrawer = (open) => {
      if (!drawer) return;
      drawer.classList.toggle("open", open);
      drawer.setAttribute("aria-hidden", open ? "false" : "true");
      if (backdrop) backdrop.classList.toggle("open", open);
      document.querySelectorAll("[data-drawer-toggle]").forEach((btn) => btn.setAttribute("aria-expanded", open ? "true" : "false"));
    };

    document.addEventListener("click", (ev) => {
      if (ev.target.closest("[data-drawer-toggle]")) {
        setDrawer(!drawer.classList.contains("open"));
        return;
      }
      if (ev.target.closest("[data-drawer-close]") || (drawer && drawer.classList.contains("open") && ev.target.closest("[data-drawer] a.nav"))) {
        setDrawer(false);
      }
      const pubBtn = ev.target.closest("[data-public-nav-toggle]");
      if (pubBtn) {
        const nav = document.querySelector("[data-public-nav]");
        if (nav) {
          const open = nav.classList.toggle("open");
          pubBtn.setAttribute("aria-expanded", open ? "true" : "false");
        }
      }
    });

    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") setDrawer(false);
    });
  }

  function initPhotoCapture() {
    const itemImgInput = document.getElementById("item-image-input");
    const itemPreviewBox = document.getElementById("item-photo-preview-box");
    const itemPreview = document.getElementById("item-photo-preview");
    const itemMeta = document.getElementById("item-photo-meta");
    const itemClear = document.getElementById("item-photo-clear");
    let itemPreviewUrl = null;

    function showItemPhoto(file) {
      if (!itemPreviewBox || !itemPreview) return;
      if (itemPreviewUrl) {
        URL.revokeObjectURL(itemPreviewUrl);
        itemPreviewUrl = null;
      }
      if (!file) {
        itemPreviewBox.hidden = true;
        itemPreview.removeAttribute("src");
        return;
      }
      itemPreviewUrl = URL.createObjectURL(file);
      itemPreview.src = itemPreviewUrl;
      if (itemMeta) itemMeta.textContent = `${file.name || "foto"} · ${Math.max(1, Math.round((file.size || 0) / 1024))} KB`;
      itemPreviewBox.hidden = false;
    }

    function setItemPhoto(file) {
      if (!itemImgInput || !file) return;
      const dt = new DataTransfer();
      dt.items.add(file);
      itemImgInput.files = dt.files;
      showItemPhoto(file);
    }

    if (itemImgInput) itemImgInput.addEventListener("change", () => showItemPhoto(itemImgInput.files[0]));
    if (itemClear) itemClear.addEventListener("click", () => {
      if (itemImgInput) itemImgInput.value = "";
      showItemPhoto(null);
    });

    const camOpen = document.getElementById("item-cam-open");
    const camBox = document.getElementById("item-cam-box");
    const camVideo = document.getElementById("item-cam-video");
    const camShot = document.getElementById("item-cam-shot");
    const camClose = document.getElementById("item-cam-close");
    const camFallback = document.getElementById("item-image-capture");
    let camStream = null;

    function stopCam() {
      if (camStream) camStream.getTracks().forEach((track) => track.stop());
      camStream = null;
      if (camBox) camBox.hidden = true;
    }

    if (camFallback) camFallback.addEventListener("change", () => camFallback.files[0] && setItemPhoto(camFallback.files[0]));
    if (camOpen) {
      camOpen.addEventListener("click", async () => {
        try {
          if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("sem camera");
          camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
          camVideo.srcObject = camStream;
          camBox.hidden = false;
        } catch (e) {
          if (camFallback) camFallback.click();
        }
      });
    }
    if (camClose) camClose.addEventListener("click", stopCam);
    if (camShot) {
      camShot.addEventListener("click", () => {
        const canvas = document.createElement("canvas");
        canvas.width = camVideo.videoWidth || 1280;
        canvas.height = camVideo.videoHeight || 720;
        canvas.getContext("2d").drawImage(camVideo, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => {
          if (blob) setItemPhoto(new File([blob], "item-capturado.jpg", { type: "image/jpeg" }));
          stopCam();
        }, "image/jpeg", 0.9);
      });
    }
  }

  function applyVisionSuggestions(analysis) {
    const fillIfEmpty = (selector, value) => {
      const el = document.querySelector(selector);
      if (el && value && !el.value.trim()) el.value = value;
    };
    if (analysis.category) {
      const catEl = document.querySelector("[data-category-select]");
      if (catEl) {
        catEl.value = analysis.category;
        catEl.dispatchEvent(new Event("change"));
      }
    }
    fillIfEmpty("input[name=title]", analysis.title);
    fillIfEmpty("textarea[name=description]", analysis.description);
    if (analysis.color) {
      const colorEl = document.querySelector("select[name=color]");
      if (colorEl && !colorEl.value) colorEl.value = analysis.color;
    }
    fillIfEmpty("input[name=brand]", analysis.brand);
    fillIfEmpty("input[name=model]", analysis.model);
  }

  function initVisionAnalyze(toast) {
    const visionBtn = document.querySelector("[data-vision-analyze]");
    if (!visionBtn) return;
    const statusEl = document.querySelector("[data-vision-status]");
    const fileInput = document.querySelector("input[name=image]");

    visionBtn.addEventListener("click", async () => {
      const file = fileInput && fileInput.files && fileInput.files[0];
      if (!file) {
        if (statusEl) statusEl.textContent = "Selecione uma foto antes de analisar com a IA.";
        return;
      }
      visionBtn.disabled = true;
      if (statusEl) statusEl.textContent = "Analisando foto com IA...";
      try {
        const formData = new FormData();
        formData.append("image", file);
        const resp = await fetch("/api/vision/analyze", { method: "POST", body: formData });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.analysis) throw new Error(data.error || "Não foi possível analisar a foto.");
        applyVisionSuggestions(data.analysis);
        if (statusEl) {
          statusEl.textContent = data.analysis.visualSummary
            ? `IA: ${data.analysis.visualSummary}`
            : "Campos sugeridos preenchidos!";
        }
        toast("Campos sugeridos pela IA a partir da foto.");
      } catch (e) {
        if (statusEl) statusEl.textContent = e.message;
        toast(e.message, true);
      } finally {
        visionBtn.disabled = false;
      }
    });
  }

  function init() {
    const toast = initToasts();
    initApiActions(toast);
    initRoleSelector(toast);
    initGeoLocation();
    initDynamicFormFields();
    initMobileDrawers();
    initPhotoCapture();
    initVisionAnalyze(toast);
  }

  init();
})();

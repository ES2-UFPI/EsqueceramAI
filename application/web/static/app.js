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

    const mapToggle = document.querySelector("[data-geo-map-toggle]");
    const mapBox = document.getElementById("item-geo-map-box");
    const mapContainer = document.getElementById("item-geo-map");
    if (mapToggle && mapBox && mapContainer) {
      let mapInstance = null;
      let mapMarker = null;

      function ensureLeaflet(cb) {
        if (window.L) {
          cb(window.L);
          return;
        }
        if (!document.getElementById("leaflet-css")) {
          const css = document.createElement("link");
          css.id = "leaflet-css";
          css.rel = "stylesheet";
          css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
          document.head.appendChild(css);
        }
        const script = document.createElement("script");
        script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
        script.onload = () => window.L && cb(window.L);
        script.onerror = () => geoSay(mapToggle, "Não foi possível carregar o mapa. Informe as coordenadas manualmente.");
        document.head.appendChild(script);
      }

      mapToggle.addEventListener("click", () => {
        const opening = mapBox.hidden;
        mapBox.hidden = !opening;
        mapToggle.setAttribute("aria-expanded", opening ? "true" : "false");
        if (!opening) return;

        ensureLeaflet((L) => {
          const { form } = geoBox(mapToggle);
          const latVal = parseFloat(form && form.elements.latitude ? form.elements.latitude.value : "");
          const lngVal = parseFloat(form && form.elements.longitude ? form.elements.longitude.value : "");
          const hasCoords = Number.isFinite(latVal) && Number.isFinite(lngVal);
          const center = hasCoords ? [latVal, lngVal] : [-5.0563, -42.7894];

          if (!mapInstance) {
            mapInstance = L.map(mapContainer).setView(center, 16);
            L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
              attribution: "&copy; OpenStreetMap",
              maxZoom: 19,
            }).addTo(mapInstance);
            if (hasCoords) mapMarker = L.marker(center).addTo(mapInstance);
            mapInstance.on("click", (ev) => {
              const { lat, lng } = ev.latlng;
              if (mapMarker) mapMarker.setLatLng([lat, lng]);
              else mapMarker = L.marker([lat, lng]).addTo(mapInstance);
              geoApply(mapToggle, lat, lng);
              geoSay(mapToggle, `Ponto selecionado no mapa (${lat.toFixed(6)}, ${lng.toFixed(6)}).`);
            });
          } else {
            mapInstance.invalidateSize();
            if (hasCoords) {
              mapInstance.setView(center, 16);
              if (mapMarker) mapMarker.setLatLng(center);
              else mapMarker = L.marker(center).addTo(mapInstance);
            }
          }
        });
      });
    }
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

    // Campos exclusivos de itens encontrados (ponto de coleta e validação de posse)
    const secretBox = document.querySelector("[data-secret-box]");
    const foundOnlyBoxes = Array.from(document.querySelectorAll("[data-found-only]") || []);
    if (secretBox) foundOnlyBoxes.unshift(secretBox);
    if (foundOnlyBoxes.length) {
      const syncFoundOnly = () => {
        const found = document.querySelector("[data-record-type][value='FOUND']");
        const on = !found || found.checked;
        foundOnlyBoxes.forEach((box) => {
          box.hidden = !on;
          (box.querySelectorAll("input, textarea") || []).forEach((el) => (el.disabled = !on));
          (box.querySelectorAll("select") || []).forEach((el) => (el.disabled = !on));
        });
      };
      document.querySelectorAll("[data-record-type]").forEach((radio) => radio.addEventListener("change", syncFoundOnly));
      syncFoundOnly();
    }

    const locInput = document.querySelector("[data-location-group] input[name='location']");
    const latInput = document.querySelector("input[name='latitude']");
    const lngInput = document.querySelector("input[name='longitude']");
    if (locInput && latInput && lngInput) {
      const syncLocRequired = () => {
        const hasCoords = Boolean(latInput.value.trim() && lngInput.value.trim());
        locInput.required = !hasCoords;
      };
      latInput.addEventListener("input", syncLocRequired);
      lngInput.addEventListener("input", syncLocRequired);
      syncLocRequired();
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
    const itemForm = document.querySelector("[data-item-form]");
    const itemImgInput = document.getElementById("item-image-input");
    const itemPreviewBox = document.getElementById("item-photo-preview-box");
    const itemPreview = document.getElementById("item-photo-preview");
    const itemMeta = document.getElementById("item-photo-meta");
    const itemClear = document.getElementById("item-photo-clear");
    const PENDING_PHOTO_KEY = "esqueceram_pending_photo";
    let itemPreviewUrl = null;

    function clearPendingPhoto() {
      try {
        sessionStorage.removeItem(PENDING_PHOTO_KEY);
      } catch (e) {}
    }

    function savePendingPhoto(file) {
      if (!file || typeof FileReader === "undefined") return;
      try {
        const reader = new FileReader();
        reader.onload = () => {
          try {
            sessionStorage.setItem(PENDING_PHOTO_KEY, JSON.stringify({
              name: file.name || "foto.jpg",
              type: file.type || "image/jpeg",
              dataUrl: reader.result,
            }));
          } catch (e) {}
        };
        reader.readAsDataURL(file);
      } catch (e) {}
    }

    function restorePendingPhoto() {
      if (!itemForm || itemForm.dataset.hasError !== "1") {
        clearPendingPhoto();
        return;
      }
      if (!itemImgInput || (itemImgInput.files && itemImgInput.files.length)) return;
      try {
        const raw = sessionStorage.getItem(PENDING_PHOTO_KEY);
        if (!raw) return;
        const saved = JSON.parse(raw);
        if (!saved || !saved.dataUrl) return;
        const parts = saved.dataUrl.split(",");
        if (parts.length !== 2) return;
        const bin = atob(parts[1]);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
        const restored = new File([bytes], saved.name || "foto.jpg", { type: saved.type || "image/jpeg" });
        setItemPhoto(restored, false);
      } catch (e) {}
    }

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

    function setItemPhoto(file, shouldSave = true) {
      if (!itemImgInput || !file) return;
      if (typeof DataTransfer !== "undefined") {
        const dt = new DataTransfer();
        dt.items.add(file);
        itemImgInput.files = dt.files;
      }
      if (shouldSave) savePendingPhoto(file);
      showItemPhoto(file);
    }

    if (itemImgInput) {
      itemImgInput.addEventListener("change", () => {
        const file = itemImgInput.files[0];
        if (file) savePendingPhoto(file);
        else clearPendingPhoto();
        showItemPhoto(file);
      });
    }
    if (itemClear) {
      itemClear.addEventListener("click", () => {
        if (itemImgInput) itemImgInput.value = "";
        clearPendingPhoto();
        showItemPhoto(null);
      });
    }
    restorePendingPhoto();

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
    fillIfEmpty("textarea[name=description]", analysis.description || analysis.visualSummary);
    if (analysis.color) {
      const colorEl = document.querySelector("select[name=color]");
      if (colorEl && !colorEl.value) colorEl.value = analysis.color;
    }
    fillIfEmpty("input[name='attributes.customColor']", analysis.customColor);
    fillIfEmpty("input[name=brand]", analysis.brand);
    fillIfEmpty("input[name=model]", analysis.model);

    const attrs = analysis.attributes && typeof analysis.attributes === "object" ? analysis.attributes : {};
    for (const [key, val] of Object.entries(attrs)) {
      if (val) fillIfEmpty(`input[name='attributes.${key}']`, String(val));
    }

    const tags = Array.isArray(analysis.visualTags) ? analysis.visualTags.filter(Boolean) : [];
    const tagsText = tags.join(", ");
    if (tagsText) {
      if (analysis.category === "ACCESSORY") fillIfEmpty("input[name='attributes.visualDetails']", tagsText);
      else if (analysis.category === "ELECTRONIC") fillIfEmpty("input[name='attributes.compatibility']", tagsText);
      else if (analysis.category === "DOCUMENT") fillIfEmpty("input[name='attributes.documentType']", analysis.title || tagsText);
    }

    const tagsBox = document.querySelector("[data-vision-tags]");
    if (tagsBox) {
      tagsBox.innerHTML = "";
      tags.forEach((tag) => {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = `#${tag}`;
        tagsBox.appendChild(chip);
      });
      tagsBox.hidden = tags.length === 0;
    }
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

  function initBrowserPush(toast) {
    const pushBtn = document.querySelector("[data-push-enable]");
    const pushStatus = document.querySelector("[data-push-status]");
    const isAuthed = document.body && document.body.dataset && document.body.dataset.userAuthed === "1";
    const hasNotificationApi = typeof Notification !== "undefined";
    const SEEN_KEY = "esqueceram_seen_notifs";
    let swReg = null;

    function getSeenIds() {
      try {
        const raw = localStorage.getItem(SEEN_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
      } catch (e) {
        return [];
      }
    }

    function saveSeenIds(ids) {
      try {
        localStorage.setItem(SEEN_KEY, JSON.stringify(ids.slice(-100)));
      } catch (e) {}
    }

    function updatePushStatus() {
      if (!pushStatus && !pushBtn) return;
      if (!hasNotificationApi) {
        if (pushStatus) pushStatus.textContent = "Este navegador não suporta notificações nativas.";
        if (pushBtn) pushBtn.disabled = true;
        return;
      }
      if (Notification.permission === "granted") {
        if (pushStatus) pushStatus.textContent = "Notificações no dispositivo ativadas para novos avisos.";
        if (pushBtn) pushBtn.textContent = "🔔 Notificações ativadas";
      } else if (Notification.permission === "denied") {
        if (pushStatus) pushStatus.textContent = "Notificações bloqueadas nas permissões do navegador.";
      } else if (pushStatus) {
        pushStatus.textContent = "Ative para receber alertas no navegador ou celular.";
      }
    }

    async function showNativeNotification(notif) {
      const options = {
        body: notif.body || "",
        icon: "/static/logo-esqueceram-ai.png",
        tag: `esqueceram-notif-${notif.id}`,
        data: { url: notif.link || "/painel/notificacoes" },
      };
      if (swReg && typeof swReg.showNotification === "function") {
        await swReg.showNotification(notif.title || "Esqueceram AI", options);
        return;
      }
      const n = new Notification(notif.title || "Esqueceram AI", options);
      n.onclick = () => {
        if (options.data.url) location.href = options.data.url;
      };
    }

    async function checkUnreadNotifications() {
      if (!isAuthed || !hasNotificationApi || Notification.permission !== "granted") return;
      try {
        const data = await apiCall("/api/notifications", "GET");
        const unread = (data.notifications || []).filter((n) => !n.isRead);
        if (!unread.length) return;
        const seen = new Set(getSeenIds());
        const fresh = unread.filter((n) => !seen.has(n.id));
        if (!fresh.length) return;
        for (const notif of fresh) {
          await showNativeNotification(notif);
          seen.add(notif.id);
        }
        saveSeenIds(Array.from(seen));
      } catch (e) {}
    }

    if (typeof navigator !== "undefined" && navigator.serviceWorker && typeof navigator.serviceWorker.register === "function") {
      navigator.serviceWorker.register("/sw.js").then((reg) => {
        swReg = reg;
        checkUnreadNotifications();
      }).catch(() => {});
    }

    updatePushStatus();

    if (pushBtn && hasNotificationApi) {
      pushBtn.addEventListener("click", async () => {
        try {
          const perm = await Notification.requestPermission();
          updatePushStatus();
          if (perm === "granted") {
            toast("Notificações ativadas no dispositivo.");
            await checkUnreadNotifications();
          } else if (perm === "denied") {
            toast("Permissão negada", "Libere as notificações nas configurações do navegador.", true);
          }
        } catch (e) {
          toast("Não foi possível ativar as notificações.", e.message, true);
        }
      });
    }

    if (isAuthed && hasNotificationApi) {
      checkUnreadNotifications();
      setInterval(checkUnreadNotifications, 20000);
    }
  }

  function initMatchChats(toast) {
    document.querySelectorAll("[data-match-chat]").forEach((box) => {
      const matchId = box.dataset.matchChat;
      const logEl = box.querySelector("[data-chat-log]");
      const form = box.querySelector("[data-chat-form]");
      const input = form && form.querySelector("input[name='body']");
      if (!matchId || !logEl || !form || !input) return;

      const render = (messages) => {
        if (!messages.length) {
          logEl.innerHTML = '<p class="xs muted">Nenhuma mensagem ainda. Envie a primeira para combinar a entrega.</p>';
          return;
        }
        logEl.innerHTML = "";
        messages.forEach((m) => {
          const item = document.createElement("div");
          item.className = "chat-msg" + (m.isMine ? " mine" : "");
          const meta = document.createElement("div");
          meta.className = "xs muted";
          const hhmm = m.createdAt ? new Date(m.createdAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "";
          meta.textContent = `${m.senderName} (${m.senderRole})${hhmm ? " · " + hhmm : ""}`;
          const body = document.createElement("div");
          body.className = "sm";
          body.textContent = m.body;
          item.append(meta, body);
          logEl.appendChild(item);
        });
        logEl.scrollTop = logEl.scrollHeight;
      };

      const load = async () => {
        try {
          const r = await fetch(`/api/matches/${matchId}/messages`, { credentials: "same-origin" });
          if (!r.ok) return;
          const d = await r.json();
          render(d.messages || []);
        } catch (e) {}
      };

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        const btn = form.querySelector("button[type='submit']");
        if (btn) btn.disabled = true;
        try {
          const res = await fetch(`/api/matches/${matchId}/messages`, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ body: text }),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.error || "Erro ao enviar mensagem.");
          input.value = "";
          await load();
        } catch (err) {
          toast("Não foi possível enviar", err.message, true);
        } finally {
          if (btn) btn.disabled = false;
        }
      });

      load();
      setInterval(() => { if (!document.hidden) load(); }, 5000);
    });
  }

  function initItemFormSubmit() {
    const form = document.querySelector("[data-item-form]");
    if (!form) return;
    const btn = form.querySelector("[data-submit-btn]");
    const spinner = form.querySelector("[data-submit-spinner]");
    if (!btn) return;
    form.addEventListener("submit", (e) => {
      if (btn.disabled) {
        e.preventDefault();
        return;
      }
      btn.disabled = true;
      if (spinner) spinner.hidden = false;
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
    initBrowserPush(toast);
    initMatchChats(toast);
    initItemFormSubmit();
  }

  init();
})();

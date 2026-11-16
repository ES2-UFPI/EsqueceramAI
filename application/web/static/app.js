/* Ações do painel: chamam a API REST (cookie de sessão) e recarregam a página. */
(function () {
  const box = document.createElement("div"); box.className = "toasts"; document.body.appendChild(box);
  function toast(title, desc, bad) {
    const t = document.createElement("div"); t.className = "toast" + (bad ? " bad" : "");
    t.innerHTML = "<b></b>" + (desc ? "<small></small>" : ""); t.querySelector("b").textContent = title;
    if (desc) t.querySelector("small").textContent = desc; box.appendChild(t); setTimeout(() => t.remove(), 4500);
  }
  window.toast = toast;
  document.querySelectorAll(".flash").forEach(f => toast(f.dataset.msg, "", f.dataset.tone === "error"));
  try { const m = sessionStorage.getItem("toast"); if (m) { sessionStorage.removeItem("toast"); toast(m); } } catch (e) {}

  async function call(url, method, body) {
    const r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
    const p = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(p.error || "Não foi possível concluir a ação.");
    return p;
  }
  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-api]"); if (!b) return;
    ev.preventDefault();
    if (b.dataset.confirm && !window.confirm(b.dataset.confirm)) return;
    b.disabled = true;
    try {
      await call(b.dataset.api, b.dataset.method || "POST", b.dataset.body ? JSON.parse(b.dataset.body) : null);
      try { sessionStorage.setItem("toast", b.dataset.success || "Ação concluída"); } catch (e) {}
      if (b.dataset.redirect) location.href = b.dataset.redirect; else location.reload();
    } catch (e) { toast("Algo deu errado", e.message, true); b.disabled = false; }
  });
  document.addEventListener("change", async (ev) => {
    const s = ev.target.closest("[data-role-user]"); if (!s) return;
    try { await call("/api/admin/users", "PATCH", { userId: +s.dataset.roleUser, role: s.value }); toast("Permissão atualizada", "Novo papel: " + s.value); }
    catch (e) { toast("Não foi possível alterar", e.message, true); location.reload(); }
  });
  // Preenche latitude/longitude pelo GPS ou por um ponto de coleta
  function geoBox(el) { const box = el.closest("[data-geo-box]"); return { form: el.closest("form"), status: box && box.querySelector("[data-geo-status]") }; }
  function geoSay(el, text) { const { status } = geoBox(el); if (status) status.textContent = text; }
  function geoApply(el, lat, lng) {
    const { form } = geoBox(el); const btn = form.querySelector("[data-geo-locate]") || el;
    const latEl = form.elements[btn.dataset.geoLatName || "lat"], lngEl = form.elements[btn.dataset.geoLngName || "lng"];
    latEl.value = Number(lat).toFixed(6); lngEl.value = Number(lng).toFixed(6);
    if (form.elements.raio) {  // formulário de busca: define raio e ordem padrão e já pesquisa
      if (!form.elements.raio.value) form.elements.raio.value = "1";
      if (form.elements.ordem) form.elements.ordem.value = "proximity";
      form.requestSubmit();
    }
  }
  document.addEventListener("click", (ev) => {
    const clear = ev.target.closest("[data-geo-clear]");
    if (clear) {
      ev.preventDefault(); const { form } = geoBox(clear);
      form.elements.lat.value = ""; form.elements.lng.value = ""; form.elements.raio.value = ""; form.requestSubmit(); return;
    }
    const btn = ev.target.closest("[data-geo-locate]"); if (!btn) return;
    if (!navigator.geolocation) { geoSay(btn, "Seu navegador não permite obter a localização."); return; }
    btn.disabled = true; geoSay(btn, "Obtendo localização…");
    navigator.geolocation.getCurrentPosition((pos) => {
      geoSay(btn, "Localização preenchida (precisão de cerca de " + Math.round(pos.coords.accuracy) + " m).");
      btn.disabled = false; geoApply(btn, pos.coords.latitude, pos.coords.longitude);
    }, (err) => {
      geoSay(btn, err.code === 1 ? "Permissão negada. Informe as coordenadas ou escolha um ponto de coleta." : "Não foi possível obter a localização.");
      btn.disabled = false;
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  });
  document.addEventListener("change", (ev) => {
    const sel = ev.target.closest("[data-geo-point]"); if (!sel || !sel.value) return;
    const opt = sel.selectedOptions[0]; geoApply(sel, opt.dataset.lat, opt.dataset.lng);
  });
  // Campos dinâmicos por categoria no formulário de item
  const cat = document.querySelector("[data-category-select]");
  if (cat) {
    const sync = () => document.querySelectorAll("[data-category-group]").forEach(g => {
      const on = g.dataset.categoryGroup === cat.value; g.hidden = !on; g.querySelectorAll("input").forEach(i => i.disabled = !on);
    });
    cat.addEventListener("change", sync); sync();
  }
  // Validação de posse só existe para itens encontrados
  const secretBox = document.querySelector("[data-secret-box]");
  if (secretBox) {
    const syncSecret = () => {
      const found = document.querySelector("[data-record-type][value='FOUND']");
      const on = !found || found.checked;
      secretBox.hidden = !on;
      secretBox.querySelectorAll("input, textarea").forEach(i => i.disabled = !on);
    };
    document.querySelectorAll("[data-record-type]").forEach(r => r.addEventListener("change", syncSecret));
    syncSecret();
  }
  // Menu retrátil no mobile (drawer do painel e menu do cabeçalho público)
  const drawer = document.querySelector("[data-drawer]"), backdrop = document.querySelector("[data-drawer-backdrop]");
  const setDrawer = (open) => {
    if (!drawer) return;
    drawer.classList.toggle("open", open);
    drawer.setAttribute("aria-hidden", open ? "false" : "true");
    if (backdrop) backdrop.classList.toggle("open", open);
    document.querySelectorAll("[data-drawer-toggle]").forEach(b => b.setAttribute("aria-expanded", open ? "true" : "false"));
  };
  document.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-drawer-toggle]")) { setDrawer(!drawer.classList.contains("open")); return; }
    if (ev.target.closest("[data-drawer-close]") || (drawer && drawer.classList.contains("open") && ev.target.closest("[data-drawer] a.nav"))) { setDrawer(false); }
    const pubBtn = ev.target.closest("[data-public-nav-toggle]");
    if (pubBtn) {
      const nav = document.querySelector("[data-public-nav]");
      if (nav) { const open = nav.classList.toggle("open"); pubBtn.setAttribute("aria-expanded", open ? "true" : "false"); }
    }
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") setDrawer(false); });

  const visionBtn = document.querySelector("[data-vision-analyze]");
  if (visionBtn) {
    const statusEl = document.querySelector("[data-vision-status]");
    const fileInput = document.querySelector("input[name=image]");
    visionBtn.addEventListener("click", async () => {
      const file = fileInput && fileInput.files && fileInput.files[0];
      if (!file) { if (statusEl) statusEl.textContent = "Selecione uma foto antes de analisar com a IA."; return; }
      visionBtn.disabled = true;
      if (statusEl) statusEl.textContent = "Analisando foto com IA...";
      try {
        const fd = new FormData();
        fd.append("image", file);
        const r = await fetch("/api/vision/analyze", { method: "POST", body: fd });
        const d = await r.json().catch(() => ({}));
        if (!r.ok || !d.analysis) throw new Error(d.error || "Não foi possível analisar a foto.");
        const a = d.analysis;
        const setVal = (sel, val) => { const el = document.querySelector(sel); if (el && val && !el.value.trim()) el.value = val; };
        if (a.category) {
          const catEl = document.querySelector("[data-category-select]");
          if (catEl) { catEl.value = a.category; catEl.dispatchEvent(new Event("change")); }
        }
        setVal("input[name=title]", a.title);
        setVal("textarea[name=description]", a.description);
        if (a.color) { const cEl = document.querySelector("select[name=color]"); if (cEl && !cEl.value) cEl.value = a.color; }
        setVal("input[name=brand]", a.brand);
        setVal("input[name=model]", a.model);
        if (statusEl) statusEl.textContent = a.visualSummary ? `IA: ${a.visualSummary}` : "Campos sugeridos preenchidos!";
        toast("Campos sugeridos pela IA a partir da foto.");
      } catch (e) {
        if (statusEl) statusEl.textContent = e.message;
        toast(e.message, true);
      } finally {
        visionBtn.disabled = false;
      }
    });
  }
})();

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
  // Localização (US10): preenche latitude/longitude pelo GPS ou por um ponto de coleta
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
  // US04: validação de posse só existe para itens encontrados
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
})();

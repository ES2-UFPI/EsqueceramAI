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
  // Campos dinâmicos por categoria no formulário de item
  const cat = document.querySelector("[data-category-select]");
  if (cat) {
    const sync = () => document.querySelectorAll("[data-category-group]").forEach(g => {
      const on = g.dataset.categoryGroup === cat.value; g.hidden = !on; g.querySelectorAll("input").forEach(i => i.disabled = !on);
    });
    cat.addEventListener("change", sync); sync();
  }
})();

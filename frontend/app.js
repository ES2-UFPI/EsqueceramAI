const API = "http://localhost:5000/api";

function mostrar(texto) {
  document.getElementById("msg").textContent = texto;
}

async function carregar() {
  try {
    const resp = await fetch(`${API}/itens`);
    if (!resp.ok) throw new Error(`Erro ${resp.status}`);
    const itens = await resp.json();
    const lista = document.getElementById("lista");
    lista.innerHTML = "";
    itens.forEach((i) => {
      const li = document.createElement("li");
      li.textContent = `${i.nome} — ${i.local}`;
      lista.appendChild(li);
    });
  } catch (e) {
    mostrar("Falha ao carregar: " + e.message);
  }
}

document.getElementById("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const corpo = {
    nome: document.getElementById("nome").value,
    local: document.getElementById("local").value,
  };
  try {
    const resp = await fetch(`${API}/itens`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    });
    const dados = await resp.json();
    if (!resp.ok) throw new Error(dados.erro || resp.status);
    ev.target.reset();
    mostrar("Item cadastrado!");
    carregar();
  } catch (e) {
    mostrar("Falha ao cadastrar: " + e.message);
  }
});

carregar();
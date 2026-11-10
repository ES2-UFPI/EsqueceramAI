// Produção (GitHub Pages) usa a API publicada no Render.
// Em ambiente local tudo fica no host atual: o Nginx do Compose encaminha /api
// para o serviço api, sem CORS e sem depender da URL pública.
const PRODUCAO = location.hostname.endsWith("github.io");

const API = window.ESQUECERAM_API || (PRODUCAO
  ? "https://esqueceramai.onrender.com/api"
  : location.protocol === "file:"
    ? "http://localhost:5000/api"
    : "/api");

const ROTULO_CATEGORIA = {
  ELETRONICO: "Eletrônico",
  DOCUMENTO: "Documento",
  ACESSORIO: "Acessório",
};

const ROTULO_STATUS = {
  ABERTO: "Aberto",
  RESERVADO: "Reservado",
  DEVOLVIDO: "Devolvido",
  ARQUIVADO: "Arquivado",
};

let itensCarregados = [];
// Ponto de referência da busca por proximidade (definido por "Perto de mim").
let referencia = null;

function el(id) {
  return document.getElementById(id);
}

function mostrar(texto, tipo = "info") {
  const alvo = el("message");
  alvo.textContent = texto;
  alvo.dataset.tipo = tipo;
}

function limparMensagem() {
  const alvo = el("message");
  alvo.textContent = "";
  delete alvo.dataset.tipo;
}

async function pedir(caminho, opcoes = {}) {
  const resp = await fetch(`${API}${caminho}`, opcoes);
  let dados = null;
  try {
    dados = await resp.json();
  } catch (e) {
    dados = null;
  }
  if (!resp.ok) {
    const detalhe = dados && dados.erro ? dados.erro : `erro ${resp.status}`;
    throw new Error(detalhe);
  }
  return dados;
}

// ------------------------------------------------------- geolocalização ----
function obterPosicao() {
  return new Promise((resolver, rejeitar) => {
    if (!navigator.geolocation) {
      rejeitar(new Error("Seu navegador não permite obter a localização."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolver(pos.coords),
      (erro) => rejeitar(new Error(erro.code === 1
        ? "Permissão de localização negada. Informe as coordenadas manualmente."
        : "Não foi possível obter a localização.")),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  });
}

function formatarDistancia(km) {
  if (km === null || km === undefined) return "";
  if (km < 0.01) return "menos de 10 m";
  const metros = Math.round(km * 100) * 10;
  return metros < 1000 ? `${metros} m` : `${km.toFixed(1).replace(".", ",")} km`;
}

// ---------------------------------------------------------------- abas -----
function abrirAba(nome) {
  document.querySelectorAll(".aba").forEach((botao) => {
    botao.classList.toggle("ativa", botao.dataset.aba === nome);
  });
  document.querySelectorAll(".painel").forEach((painel) => {
    painel.hidden = painel.id !== `aba-${nome}`;
  });
  limparMensagem();
}

document.querySelectorAll(".aba").forEach((botao) => {
  botao.addEventListener("click", () => abrirAba(botao.dataset.aba));
});

// ------------------------------------------------------------ listagem -----
function descreverItem(item) {
  const partes = [item.descricao];
  if (item.cor) partes.push(`cor ${item.cor}`);
  if (item.marca) partes.push(item.marca);
  if (item.modelo) partes.push(item.modelo);
  return partes.join(" · ");
}

function renderizarItens(itens) {
  const lista = el("lista-itens");
  lista.innerHTML = "";

  if (!itens.length) {
    const vazio = document.createElement("li");
    vazio.className = "vazio";
    vazio.textContent = "Nenhum item encontrado com esses filtros.";
    lista.appendChild(vazio);
    return;
  }

  itens.forEach((item) => {
    const li = document.createElement("li");
    li.className = "cartao-item";

    const titulo = document.createElement("div");
    titulo.className = "cartao-titulo";
    const tipo = document.createElement("span");
    tipo.className = `etiqueta tipo-${item.tipo_registro.toLowerCase()}`;
    tipo.textContent = item.tipo_registro === "PERDIDO" ? "Perdido" : "Encontrado";
    const status = document.createElement("span");
    status.className = "etiqueta status";
    status.textContent = ROTULO_STATUS[item.status] || item.status;
    titulo.append(tipo, status);

    const descricao = document.createElement("p");
    descricao.className = "cartao-descricao";
    descricao.textContent = descreverItem(item);

    const meta = document.createElement("p");
    meta.className = "cartao-meta";
    const dados = [ROTULO_CATEGORIA[item.categoria] || item.categoria];
    if (item.localizacao) dados.push(item.localizacao);
    if (item.distancia_km !== null && item.distancia_km !== undefined) {
      dados.push(`a ${formatarDistancia(item.distancia_km)}`);
    }
    if (item.posto_nome) dados.push(`posto: ${item.posto_nome}`);
    meta.textContent = dados.join(" • ");

    li.append(titulo, descricao, meta);

    if (item.imagem_url) {
      const foto = document.createElement("img");
      const raiz = API.endsWith("/api") ? API.slice(0, -4) : API;
      foto.src = item.imagem_url.startsWith("http") ? item.imagem_url : `${raiz}${item.imagem_url}`;
      foto.alt = `Foto do item: ${item.descricao}`;
      foto.className = "cartao-foto";
      foto.loading = "lazy";
      li.appendChild(foto);
    }

    lista.appendChild(li);
  });
}

function filtrosAtuais() {
  const params = new URLSearchParams();
  const mapa = {
    q: el("busca-q").value.trim(),
    tipo_registro: el("busca-tipo").value,
    categoria: el("busca-categoria").value,
    status: el("busca-status").value,
    localizacao: el("busca-local").value.trim(),
  };
  if (referencia) {
    mapa.lat = referencia.latitude;
    mapa.lng = referencia.longitude;
    mapa.raio_km = el("busca-raio").value;
  }
  Object.entries(mapa).forEach(([chave, valor]) => {
    if (valor !== "" && valor !== null && valor !== undefined) params.set(chave, valor);
  });
  return params.toString();
}

function atualizarReferencia() {
  el("busca-referencia").textContent = referencia
    ? `Referência: ${referencia.latitude.toFixed(4)}, ${referencia.longitude.toFixed(4)}. `
      + "Os itens mais próximos aparecem primeiro; itens sem coordenadas ficam de fora quando há raio."
    : "";
}

async function carregarItens() {
  try {
    const consulta = filtrosAtuais();
    const itens = await pedir(`/itens${consulta ? `?${consulta}` : ""}`);
    itensCarregados = itens;
    renderizarItens(itens);
  } catch (e) {
    mostrar(`Falha ao carregar itens: ${e.message}`, "erro");
  }
}

el("form-busca").addEventListener("submit", (ev) => {
  ev.preventDefault();
  limparMensagem();
  carregarItens();
});

el("busca-limpar").addEventListener("click", () => {
  el("form-busca").reset();
  referencia = null;
  atualizarReferencia();
  carregarItens();
});

el("busca-perto").addEventListener("click", async () => {
  limparMensagem();
  try {
    const { latitude, longitude } = await obterPosicao();
    referencia = { latitude, longitude };
    if (!el("busca-raio").value) el("busca-raio").value = "1";
    atualizarReferencia();
    await carregarItens();
  } catch (e) {
    mostrar(e.message, "erro");
  }
});

el("busca-raio").addEventListener("change", () => {
  if (el("busca-raio").value && !referencia) {
    mostrar('Para filtrar por raio, use "Perto de mim" e permita o acesso à sua localização.', "erro");
  }
});

// --------------------------------------------------------- cadastro item ---
el("item-categoria").addEventListener("change", (ev) => {
  el("campo-tipo-documento").hidden = ev.target.value !== "DOCUMENTO";
});

el("item-usar-localizacao").addEventListener("click", async () => {
  limparMensagem();
  try {
    const { latitude, longitude } = await obterPosicao();
    el("item-latitude").value = latitude.toFixed(6);
    el("item-longitude").value = longitude.toFixed(6);
    mostrar("Coordenadas preenchidas com a sua localização atual.", "sucesso");
  } catch (e) {
    mostrar(e.message, "erro");
  }
});

function corpoDoItem() {
  const tipoRegistro = el("item-tipo").value;
  const categoria = el("item-categoria").value;

  const atributos = {};
  if (categoria === "DOCUMENTO") {
    atributos.tipo_documento = el("item-tipo-documento").value.trim();
  }

  const dados = {
    tipo_registro: tipoRegistro,
    categoria,
    descricao: el("item-descricao").value.trim(),
    cor: el("item-cor").value.trim(),
    marca: el("item-marca").value.trim(),
    modelo: el("item-modelo").value.trim(),
    localizacao: el("item-localizacao").value.trim(),
    data_ocorrencia: el("item-data").value || undefined,
  };

  const latitude = el("item-latitude").value;
  const longitude = el("item-longitude").value;
  if (latitude) dados.latitude = latitude;
  if (longitude) dados.longitude = longitude;

  const posto = el("item-posto").value;
  if (posto) dados.posto_id = posto;

  if (Object.keys(atributos).length) {
    dados.atributos = JSON.stringify(atributos);
  }

  return { dados, arquivo: el("item-imagem").files[0] };
}

el("form-encontrado").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  limparMensagem();

  const { dados, arquivo } = corpoDoItem();
  if (!dados.descricao) {
    mostrar("Informe uma descrição para o item.", "erro");
    return;
  }
  if (dados.categoria === "DOCUMENTO" && !JSON.parse(dados.atributos || "{}").tipo_documento) {
    mostrar("Documentos exigem o tipo de documento.", "erro");
    return;
  }
  if (dados.posto_id && dados.tipo_registro !== "ENCONTRADO") {
    mostrar("Apenas itens encontrados podem ser entregues em um ponto de coleta.", "erro");
    return;
  }

  const corpo = new FormData();
  Object.entries(dados).forEach(([chave, valor]) => {
    if (valor !== undefined && valor !== null && valor !== "") corpo.append(chave, valor);
  });
  if (arquivo) corpo.append("imagem", arquivo);

  try {
    const item = await pedir("/itens", { method: "POST", body: corpo });
    ev.target.reset();
    el("campo-tipo-documento").hidden = true;
    mostrar(`Item #${item.id} cadastrado com sucesso como ${item.tipo_registro.toLowerCase()}.`, "sucesso");
    await carregarItens();
  } catch (e) {
    mostrar(`Falha ao cadastrar: ${e.message}`, "erro");
  }
});

// -------------------------------------------------------- pontos de coleta -
async function carregarPostos() {
  try {
    const postos = await pedir("/postos");
    const lista = el("lista-postos");
    const seletor = el("item-posto");
    lista.innerHTML = "";

    const restantes = [...seletor.options].slice(0, 1);
    seletor.replaceChildren(...restantes);

    if (!postos.length) {
      const vazio = document.createElement("li");
      vazio.className = "vazio";
      vazio.textContent = "Nenhum ponto de coleta cadastrado ainda.";
      lista.appendChild(vazio);
      return;
    }

    postos.forEach((posto) => {
      const li = document.createElement("li");
      li.className = "cartao-item";
      const nome = document.createElement("strong");
      nome.textContent = posto.nome;
      const endereco = document.createElement("p");
      endereco.className = "cartao-meta";
      endereco.textContent = posto.endereco;
      li.append(nome, endereco);
      if (posto.horario_funcionamento) {
        const horario = document.createElement("p");
        horario.className = "cartao-meta";
        horario.textContent = posto.horario_funcionamento;
        li.appendChild(horario);
      }
      lista.appendChild(li);

      const opcao = document.createElement("option");
      opcao.value = posto.id;
      opcao.textContent = posto.nome;
      seletor.appendChild(opcao);
    });
  } catch (e) {
    mostrar(`Falha ao carregar pontos de coleta: ${e.message}`, "erro");
  }
}

el("form-posto").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  limparMensagem();

  const dados = {
    nome: el("posto-nome").value.trim(),
    endereco: el("posto-endereco").value.trim(),
    latitude: el("posto-latitude").value,
    longitude: el("posto-longitude").value,
    horario_funcionamento: el("posto-horario").value.trim() || undefined,
  };

  try {
    const posto = await pedir("/postos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    });
    ev.target.reset();
    mostrar(`Ponto de coleta "${posto.nome}" cadastrado com sucesso.`, "sucesso");
    await carregarPostos();
  } catch (e) {
    mostrar(`Falha ao cadastrar ponto de coleta: ${e.message}`, "erro");
  }
});

// ---------------------------------------------------------------- início ---
async function iniciar() {
  abrirAba("busca");
  await Promise.all([carregarItens(), carregarPostos()]);
}

iniciar();

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_JS_PATH = path.resolve(__dirname, "../../application/web/static/app.js");
const APP_JS_SOURCE = fs.readFileSync(APP_JS_PATH, "utf-8");

function createClassList(initial = []) {
  const set = new Set(initial);
  return {
    add: (...cls) => cls.forEach((c) => set.add(c)),
    remove: (...cls) => cls.forEach((c) => set.delete(c)),
    contains: (c) => set.has(c),
    toggle: (c, force) => {
      if (force === undefined) {
        if (set.has(c)) {
          set.delete(c);
          return false;
        }
        set.add(c);
        return true;
      }
      if (force) set.add(c);
      else set.delete(c);
      return force;
    },
  };
}

function createElement(tagName = "div", opts = {}) {
  const listeners = new Map();
  const attrs = new Map(Object.entries(opts.attrs || {}));
  const el = {
    tagName: tagName.toUpperCase(),
    id: opts.id || "",
    value: opts.value ?? "",
    checked: opts.checked ?? false,
    disabled: opts.disabled ?? false,
    hidden: opts.hidden ?? false,
    textContent: opts.textContent || "",
    dataset: { ...(opts.dataset || {}) },
    style: {},
    files: opts.files || [],
    elements: opts.elements || {},
    selectedOptions: opts.selectedOptions || [],
    children: [],
    parentNode: null,
    classList: createClassList(opts.classes || []),
    _matches: new Set(opts.matches || []),
    _innerHTML: "",
    set className(val) {
      this.classList = createClassList(String(val).split(/\s+/).filter(Boolean));
    },
    get innerHTML() {
      return this._innerHTML;
    },
    set innerHTML(val) {
      this._innerHTML = val;
    },
    appendChild(child) {
      child.parentNode = this;
      this.children.push(child);
      return child;
    },
    remove() {
      if (this.parentNode) {
        this.parentNode.children = this.parentNode.children.filter((c) => c !== this);
      }
    },
    setAttribute(k, v) {
      attrs.set(k, String(v));
    },
    getAttribute(k) {
      return attrs.get(k) ?? null;
    },
    removeAttribute(k) {
      attrs.delete(k);
    },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    async dispatchEvent(ev) {
      ev.target = ev.target || el;
      ev.preventDefault = ev.preventDefault || (() => {});
      for (const fn of listeners.get(ev.type) || []) {
        await fn(ev);
      }
    },
    closest(selector) {
      return this._matches.has(selector) ? this : null;
    },
    querySelector(selector) {
      if (selector === "b") {
        if (!this._b) this._b = createElement("b");
        return this._b;
      }
      if (selector === "small") {
        if (!this._small) this._small = createElement("small");
        return this._small;
      }
      return (opts.queryMap && opts.queryMap[selector]) || null;
    },
    querySelectorAll(selector) {
      return (opts.queryAllMap && opts.queryAllMap[selector]) || [];
    },
    requestSubmit() {
      this.submitted = true;
    },
  };
  return el;
}

function loadAppJs({
  selectors = {},
  selectorAll = {},
  fetchImpl,
  sessionData = {},
  localData = {},
  bodyDataset = {},
  navigatorExtras = {},
  notificationApi,
} = {}) {
  const docListeners = new Map();
  const body = createElement("body", { dataset: bodyDataset });
  const ids = {};
  for (const [sel, el] of Object.entries(selectors)) {
    if (sel.startsWith("#")) ids[sel.slice(1)] = el;
  }

  const document = {
    body,
    createElement: (tag) => createElement(tag),
    getElementById: (id) => ids[id] || null,
    querySelector: (sel) => selectors[sel] || null,
    querySelectorAll: (sel) => selectorAll[sel] || [],
    addEventListener: (type, fn) => {
      if (!docListeners.has(type)) docListeners.set(type, []);
      docListeners.get(type).push(fn);
    },
  };

  const sessionMap = new Map(Object.entries(sessionData));
  const sessionStorage = {
    getItem: (k) => (sessionMap.has(k) ? sessionMap.get(k) : null),
    setItem: (k, v) => sessionMap.set(k, String(v)),
    removeItem: (k) => sessionMap.delete(k),
  };

  const localMap = new Map(Object.entries(localData));
  const localStorage = {
    getItem: (k) => (localMap.has(k) ? localMap.get(k) : null),
    setItem: (k, v) => localMap.set(k, String(v)),
    removeItem: (k) => localMap.delete(k),
  };

  const locationState = { href: "/", reloaded: false, reload: () => (locationState.reloaded = true) };
  const timeouts = [];

  const context = {
    document,
    sessionStorage,
    localStorage,
    location: locationState,
    navigator: { ...navigatorExtras },
    Notification: notificationApi,
    L: globalThis.__mockLeaflet,
    atob: (s) => Buffer.from(s, "base64").toString("binary"),
    File: class {
      constructor(parts, name, opts = {}) {
        this.parts = parts;
        this.name = name;
        this.type = opts.type || "";
        this.size = parts.reduce((acc, p) => acc + (p.length || 0), 0);
      }
    },
    DataTransfer: class {
      constructor() {
        this.files = [];
        this.items = { add: (f) => this.files.push(f) };
      }
    },
    FormData: class {
      constructor() {
        this.entries = [];
      }
      append(k, v) {
        this.entries.push([k, v]);
      }
    },
    Event: class {
      constructor(type) {
        this.type = type;
      }
    },
    fetch: fetchImpl || (async () => ({ ok: true, json: async () => ({}) })),
    setTimeout: (fn, ms) => {
      timeouts.push({ fn, ms });
      return timeouts.length;
    },
    setInterval: () => 1,
    URL: { createObjectURL: () => "blob:mock", revokeObjectURL: () => {} },
  };
  context.window = context;

  vm.runInNewContext(APP_JS_SOURCE, context);

  return {
    window: context,
    body,
    sessionMap,
    localMap,
    locationState,
    timeouts,
    async emitDoc(type, event) {
      event.preventDefault = event.preventDefault || (() => {});
      for (const fn of docListeners.get(type) || []) {
        await fn(event);
      }
    },
  };
}

test("initToasts exibe flash messages, consome sessionStorage e cria toast com auto-remocao", () => {
  const flashEl = createElement("span", { dataset: { msg: "Bem-vindo", tone: "error" } });
  const env = loadAppJs({
    selectorAll: { ".flash": [flashEl] },
    sessionData: { toast: "Salvo com sucesso" },
  });

  const toastBox = env.body.children[0];
  assert.equal(toastBox.classList.contains("toasts"), true);
  assert.equal(toastBox.children.length, 2);
  assert.equal(toastBox.children[0].classList.contains("bad"), true);
  assert.equal(toastBox.children[0].querySelector("b").textContent, "Bem-vindo");
  assert.equal(toastBox.children[1].querySelector("b").textContent, "Salvo com sucesso");
  assert.equal(env.sessionMap.has("toast"), false);

  env.window.toast("Erro", "Falha na rede", true);
  assert.equal(toastBox.children.length, 3);
  assert.equal(toastBox.children[2].querySelector("small").textContent, "Falha na rede");

  env.timeouts[2].fn();
  assert.equal(toastBox.children.length, 2);
});

test("initApiActions envia fetch com JSON, salva toast e redireciona no sucesso", async () => {
  const calls = [];
  const env = loadAppJs({
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return { ok: true, json: async () => ({ ok: true }) };
    },
  });

  const btn = createElement("button", {
    matches: ["[data-api]"],
    dataset: {
      api: "/api/items/1",
      method: "PATCH",
      body: '{"status":"ARCHIVED"}',
      success: "Item arquivado",
      redirect: "/painel/itens",
    },
  });

  await env.emitDoc("click", { target: btn });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/items/1");
  assert.equal(calls[0].init.method, "PATCH");
  assert.equal(calls[0].init.body, '{"status":"ARCHIVED"}');
  assert.equal(env.sessionMap.get("toast"), "Item arquivado");
  assert.equal(env.locationState.href, "/painel/itens");
});

test("initDynamicFormFields sincroniza grupos de categoria e campo secreto", async () => {
  const catSelect = createElement("select", { value: "ELECTRONIC" });
  const electronicInput = createElement("input");
  const docInput = createElement("input");
  const electronicGroup = createElement("div", {
    dataset: { categoryGroup: "ELECTRONIC" },
    queryAllMap: { input: [electronicInput] },
  });
  const docGroup = createElement("div", {
    dataset: { categoryGroup: "DOCUMENT" },
    queryAllMap: { input: [docInput] },
  });

  const foundRadio = createElement("input", { checked: true });
  const secretInput = createElement("input");
  const secretBox = createElement("div", {
    queryAllMap: { "input, textarea": [secretInput] },
  });

  loadAppJs({
    selectors: {
      "[data-category-select]": catSelect,
      "[data-secret-box]": secretBox,
      "[data-record-type][value='FOUND']": foundRadio,
    },
    selectorAll: {
      "[data-category-group]": [electronicGroup, docGroup],
      "[data-record-type]": [foundRadio],
    },
  });

  assert.equal(electronicGroup.hidden, false);
  assert.equal(electronicInput.disabled, false);
  assert.equal(docGroup.hidden, true);
  assert.equal(docInput.disabled, true);
  assert.equal(secretBox.hidden, false);
  assert.equal(secretInput.disabled, false);

  catSelect.value = "DOCUMENT";
  await catSelect.dispatchEvent({ type: "change" });
  assert.equal(electronicGroup.hidden, true);
  assert.equal(docGroup.hidden, false);

  foundRadio.checked = false;
  await foundRadio.dispatchEvent({ type: "change" });
  assert.equal(secretBox.hidden, true);
  assert.equal(secretInput.disabled, true);
});

test("initMobileDrawers abre, fecha no clique e fecha com Escape", async () => {
  const drawer = createElement("aside", { attrs: { "aria-hidden": "true" } });
  const backdrop = createElement("div");
  const toggleBtn = createElement("button", { matches: ["[data-drawer-toggle]"] });

  const env = loadAppJs({
    selectors: {
      "[data-drawer]": drawer,
      "[data-drawer-backdrop]": backdrop,
    },
    selectorAll: {
      "[data-drawer-toggle]": [toggleBtn],
    },
  });

  await env.emitDoc("click", { target: toggleBtn });
  assert.equal(drawer.classList.contains("open"), true);
  assert.equal(drawer.getAttribute("aria-hidden"), "false");
  assert.equal(backdrop.classList.contains("open"), true);
  assert.equal(toggleBtn.getAttribute("aria-expanded"), "true");

  await env.emitDoc("keydown", { key: "Escape" });
  assert.equal(drawer.classList.contains("open"), false);
  assert.equal(drawer.getAttribute("aria-hidden"), "true");
  assert.equal(toggleBtn.getAttribute("aria-expanded"), "false");
});

test("initVisionAnalyze envia imagem e preenche apenas campos vazios", async () => {
  const visionBtn = createElement("button");
  const statusEl = createElement("span");
  const fileInput = createElement("input", { files: [{ name: "fone.jpg", size: 2048 }] });
  const catSelect = createElement("select", { value: "ACCESSORY" });
  const titleInput = createElement("input", { value: "Título já preenchido" });
  const descInput = createElement("textarea", { value: "" });
  const colorSelect = createElement("select", { value: "" });
  const brandInput = createElement("input", { value: "" });
  const modelInput = createElement("input", { value: "" });

  loadAppJs({
    selectors: {
      "[data-vision-analyze]": visionBtn,
      "[data-vision-status]": statusEl,
      "input[name=image]": fileInput,
      "[data-category-select]": catSelect,
      "input[name=title]": titleInput,
      "textarea[name=description]": descInput,
      "select[name=color]": colorSelect,
      "input[name=brand]": brandInput,
      "input[name=model]": modelInput,
    },
    fetchImpl: async (url) => {
      assert.equal(url, "/api/vision/analyze");
      return {
        ok: true,
        json: async () => ({
          analysis: {
            category: "ELECTRONIC",
            title: "Fone Bluetooth",
            description: "Fone intra-auricular preto",
            color: "Preto",
            brand: "JBL",
            model: "Tune 510",
            visualSummary: "Fone JBL preto",
          },
        }),
      };
    },
  });

  await visionBtn.dispatchEvent({ type: "click" });

  assert.equal(catSelect.value, "ELECTRONIC");
  assert.equal(titleInput.value, "Título já preenchido");
  assert.equal(descInput.value, "Fone intra-auricular preto");
  assert.equal(colorSelect.value, "Preto");
  assert.equal(brandInput.value, "JBL");
  assert.equal(modelInput.value, "Tune 510");
  assert.equal(statusEl.textContent, "IA: Fone JBL preto");
  assert.equal(visionBtn.disabled, false);
});

test("initBrowserPush registra service worker, solicita permissao e exibe notificacao sem duplicar", async () => {
  const pushBtn = createElement("button");
  const pushStatus = createElement("p");
  const shown = [];
  let swRegistered = null;

  const notificationApi = {
    permission: "default",
    requestPermission: async () => {
      notificationApi.permission = "granted";
      return "granted";
    },
  };

  const env = loadAppJs({
    selectors: {
      "[data-push-enable]": pushBtn,
      "[data-push-status]": pushStatus,
    },
    bodyDataset: { userAuthed: "1" },
    notificationApi,
    navigatorExtras: {
      serviceWorker: {
        register: async (url) => {
          swRegistered = url;
          return {
            showNotification: async (title, opts) => {
              shown.push({ title, opts });
            },
          };
        },
      },
    },
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({
        notifications: [
          { id: 10, isRead: false, title: "Novo match", body: "Possível correspondência", link: "/painel/matches" },
          { id: 11, isRead: true, title: "Já lida", body: "Ignorar" },
        ],
      }),
    }),
  });

  await Promise.resolve();
  assert.equal(swRegistered, "/sw.js");
  assert.equal(pushStatus.textContent, "Ative para receber alertas no navegador ou celular.");

  await pushBtn.dispatchEvent({ type: "click" });
  assert.equal(shown.length, 1);
  assert.equal(shown[0].title, "Novo match");
  assert.equal(shown[0].opts.data.url, "/painel/matches");
  assert.equal(pushBtn.textContent, "🔔 Notificações ativadas");
  assert.equal(JSON.parse(env.localMap.get("esqueceram_seen_notifs")).includes(10), true);
});

test("mapa interativo abre ao clicar no botao e preenche latitude/longitude ao clicar no mapa", async () => {
  const latInput = createElement("input", { value: "" });
  const lngInput = createElement("input", { value: "" });
  const locateBtn = createElement("button", { dataset: { geoLatName: "latitude", geoLngName: "longitude" } });
  const form = createElement("form", {
    elements: { latitude: latInput, longitude: lngInput },
    queryMap: { "[data-geo-locate]": locateBtn },
  });
  const statusEl = createElement("span");
  const geoBox = createElement("div", { queryMap: { "[data-geo-status]": statusEl } });
  const mapToggle = createElement("button", { attrs: { "aria-expanded": "false" } });
  mapToggle.closest = (sel) => (sel === "[data-geo-box]" ? geoBox : sel === "form" ? form : null);
  const mapBox = createElement("div", { hidden: true });
  const mapContainer = createElement("div");

  let clickHandler = null;
  const marker = { setLatLng: () => {}, addTo: () => marker };
  globalThis.__mockLeaflet = {
    map: () => ({
      setView: function () { return this; },
      on: (ev, fn) => { if (ev === "click") clickHandler = fn; },
      invalidateSize: () => {},
    }),
    tileLayer: () => ({ addTo: () => {} }),
    marker: () => marker,
  };

  loadAppJs({
    selectors: {
      "[data-geo-map-toggle]": mapToggle,
      "#item-geo-map-box": mapBox,
      "#item-geo-map": mapContainer,
    },
  });
  delete globalThis.__mockLeaflet;

  assert.equal(mapBox.hidden, true);
  await mapToggle.dispatchEvent({ type: "click" });
  assert.equal(mapBox.hidden, false);
  assert.equal(mapToggle.getAttribute("aria-expanded"), "true");

  clickHandler({ latlng: { lat: -5.057123, lng: -42.791456 } });
  assert.equal(latInput.value, "-5.057123");
  assert.equal(lngInput.value, "-42.791456");
});

test("initPhotoCapture restaura foto do sessionStorage quando formulario recarrega com erro", () => {
  const form = createElement("form", { dataset: { hasError: "1" } });
  const imgInput = createElement("input", { files: [] });
  const previewBox = createElement("div", { hidden: true });
  const previewImg = createElement("img");
  const metaEl = createElement("span");

  loadAppJs({
    selectors: {
      "[data-item-form]": form,
      "#item-image-input": imgInput,
      "#item-photo-preview-box": previewBox,
      "#item-photo-preview": previewImg,
      "#item-photo-meta": metaEl,
    },
    sessionData: {
      esqueceram_pending_photo: JSON.stringify({
        name: "mochila.jpg",
        type: "image/jpeg",
        dataUrl: "data:image/jpeg;base64,ZmFrZS1pbWc=",
      }),
    },
  });

  assert.equal(imgInput.files.length, 1);
  assert.equal(imgInput.files[0].name, "mochila.jpg");
  assert.equal(previewBox.hidden, false);
});

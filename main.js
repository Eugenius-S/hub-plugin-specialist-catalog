// The specialists catalog on the hub page: the view #/x/specialists (in the ☰ menu; a hub that has the slot sidebar.group
// also gets a "+" in the header of the "Specialists" group that opens it): packages from specialists.json (name, what it does, version) and the hub's built-in agents
// (system agents every hub has out of the box; the core names them: session.system in the snapshot). Installed means
// an agent with that name exists in the hub; otherwise "Install" asks the hub to run `specialists install <name>` (only
// the hub or the owner installs, never the page).
// The trash on an installed card is also a request to the hub (`specialists remove <name>` and closing the session),
// after a confirmation on the card. Built-in agents have neither "Install" nor trash: the core does not let them go.
// "Not in the catalog": an agent is in the hub (role agent, not built in), but specialists.json has no package for it.
// Its card has "Share" (asks the hub to pack it as a package) and the trash (only closes the session: `specialists
// remove` does not remove such an agent).
// "Check for updates" on top asks the plugin process (main.py): it compares the installed version of every package
// with the latest one in its repo and writes status.json; a newer one turns "✓ Installed" into "Update" (a request to
// the hub: `specialists update <name>`, like "Install"), but only after the owner confirms on the card what changes in the
// profile (CLAUDE.md of the package, tools, plugins): the plugin process works that out and puts it in status.json.
const ID = "specialists";
const ASK_TTL = 30 * 60 * 1000;   // "asked the hub to install" lasts this long, then "Install" again
const DROP_TTL = 10 * 60 * 1000;  // "asked the hub to remove": the agent still there after this long, the card says it failed
const STORE = "specialists:asked";
const STORE_DROP = "specialists:removing";
const STORE_UPD = "specialists:updating";   // "name@version asked from" -> when; the version changed: the request is done
const UPD_TTL = 10 * 60 * 1000;
const CHECK_WAIT = 200 * 1000;   // the plugin process silent longer: the check "did not answer"
const SHARE_TTL = 6 * 60 * 60 * 1000;   // "share" sent: the button rests this long, then it can be pressed again
const STORE_SHARE = "specialists:sharing";
const GROUP_SLOT = "sidebar.group";   // not in every hub: the "+" is drawn only where the page has this slot
const POLL = 2000;

// plugin strings: the language is the page's (hub.lang); a missing language falls back to English
const STR = {
  en: {
    title: "Specialists catalog", subtitle: "ready-made agents in one command", plus: "Specialists catalog",
    sub: "Ready-made agents as a package: profile, CLAUDE.md, tools, test cases. “Install” sends a request to the hub, which creates the agent.",
    loading: "Loading the catalog…", load_failed: "The catalog failed to load: {err}", empty: "The catalog is empty for now.",
    have: "✓ Installed", install: "Install", asked: "Asked the hub…",
    install_title: "To the hub: specialists install {name}", wait_title: "The hub is installing it; it will appear in “Specialists”",
    install_refused: "The hub did not take the request: {err}",
    remove_title: "Remove {name}",
    sure: "Remove {name}?", sure_yes: "Remove", sure_no: "Cancel",
    sure_note: "The hub unhooks the agent and its plugins. It leaves your list; its files and past chats stay on disk.",
    sure_note_local: "This agent is not in the catalog, so the hub has no package to bring it back from. It leaves your list; its profile and past chats stay on disk.",
    removing: "Removing…", removing_title: "The hub is removing it; the card goes back to “Install”",
    remove_refused: "The hub did not take the request: {err}",
    stuck: "The hub has not removed it in {min} min. Check its reply in the hub chat (an agent that was not installed from this catalog, or one busy in a turn, is not removed).",
    stuck_local: "The hub has not removed it in {min} min. Check its reply in the hub chat (an agent busy in a turn is not removed).",
    unlisted: "Not in the catalog", unlisted_title: "Installed in your hub, but the catalog has no package for it. “Share” sends it there.",
    share: "Share", share_title: "Send {name} to the catalog: the hub packs it",
    shared: "Sent to the hub", shared_title: "The hub has the request. Once {name} is packed, it appears here as a regular card.",
    share_sure: "Share {name}?", share_yes: "Send", share_refused: "The hub did not take the request: {err}",
    share_note: "The hub will pack {name} (profile, CLAUDE.md, tools) as a package and add it to the catalog, so everyone who uses the catalog can install it. Check first that the profile holds no keys or personal data.",
    builtin: "Built in", builtin_title: "Part of every hub: always there, cannot be removed",
    check: "Check for updates", checking: "Checking…", check_title: "Looks up the latest version of every installed package",
    all_latest: "Everything is up to date", found: "Updates available: {n}", none: "No specialists from the catalog are installed",
    check_failed: "The check failed: {err}", check_partial: "Could not check: {n}.",
    check_silent: "The plugin process did not answer in {min} min. Restart the plugin and try again.",
    update: "Update", update_title: "To the hub: specialists update {name}", update_wait_title: "The hub is updating it; the card goes back to “Installed”",
    update_refused: "The hub did not take the request: {err}", row_failed: "Could not check the version: {err}",
    upd_sure: "Update {name} to {to}?", upd_yes: "Update",
    upd_note: "The hub will replace the profile with the new package version. Nothing changes before you confirm.",
    upd_unknown: "The plugin could not work out what changes in the profile. It is the package version {to}.",
    upd_profile: "CLAUDE.md: {added} lines added, {removed} removed", upd_profile_new: "CLAUDE.md: a new profile in the package",
    upd_profile_same: "CLAUDE.md: no changes",
    upd_more: "…and {n} more lines", upd_tools_add: "Tools added: {list}", upd_tools_del: "Tools removed: {list}",
    upd_plugins_add: "Plugins added: {list}", upd_plugins_del: "Plugins removed: {list}",
  },
  ru: {
    title: "Каталог специалистов", subtitle: "готовые агенты одной командой", plus: "Каталог специалистов",
    sub: "Готовые агенты пакетом: профиль, CLAUDE.md, инструменты, проверочные кейсы. «Поставить» передаёт просьбу хабу, и он заводит агента.",
    loading: "Загружаю каталог…", load_failed: "Каталог не загрузился: {err}", empty: "В каталоге пока пусто.",
    have: "✓ Поставлен", install: "Поставить", asked: "Попросили хаб…",
    install_title: "Хабу: specialists install {name}", wait_title: "Хаб ставит; появится в «Специалистах»",
    install_refused: "Хаб не принял просьбу: {err}",
    remove_title: "Удалить {name}",
    sure: "Удалить {name}?", sure_yes: "Удалить", sure_no: "Отмена",
    sure_note: "Хаб снимет агента и его плагины. Он пропадёт из твоего списка; файлы и прошлые чаты останутся на диске.",
    sure_note_local: "Этого агента нет в каталоге, у хаба нет пакета, из которого его вернуть. Он пропадёт из твоего списка; профиль и прошлые чаты останутся на диске.",
    removing: "Удаляю…", removing_title: "Хаб убирает; карточка вернётся к «Поставить»",
    remove_refused: "Хаб не принял просьбу: {err}",
    stuck: "Хаб не снял за {min} мин. Посмотри его ответ в чате хаба (агента, поставленного не из этого каталога, или занятого ходом он не снимет).",
    stuck_local: "Хаб не снял за {min} мин. Посмотри его ответ в чате хаба (занятого ходом агента он не снимет).",
    unlisted: "Не в каталоге", unlisted_title: "Стоит в твоём хабе, а пакета в каталоге нет. «Поделиться» отправит его туда.",
    share: "Поделиться", share_title: "Отправить {name} в каталог: хаб упакует его",
    shared: "Отправлено хабу", shared_title: "Хаб получил просьбу. Когда {name} упакуют, он появится здесь обычной карточкой.",
    share_sure: "Поделиться {name}?", share_yes: "Отправить", share_refused: "Хаб не принял просьбу: {err}",
    share_note: "Хаб упакует {name} (профиль, CLAUDE.md, инструменты) в пакет и добавит в каталог, чтобы его мог поставить каждый, кто пользуется каталогом. Сначала проверь, что в профиле нет ключей и личного.",
    builtin: "Встроен", builtin_title: "Есть у каждого хаба: всегда на месте, удалить нельзя",
    check: "Проверить обновления", checking: "Проверяю…", check_title: "Узнаёт последнюю версию каждого поставленного пакета",
    all_latest: "Всё последнее", found: "Есть обновления: {n}", none: "Из каталога пока никто не поставлен",
    check_failed: "Проверка не удалась: {err}", check_partial: "Не удалось проверить: {n}.",
    check_silent: "Процесс плагина не ответил за {min} мин. Перезапусти плагин и повтори.",
    update: "Обновить", update_title: "Хабу: specialists update {name}", update_wait_title: "Хаб обновляет; карточка вернётся к «Поставлен»",
    update_refused: "Хаб не принял просьбу: {err}", row_failed: "Не удалось узнать версию: {err}",
    upd_sure: "Обновить {name} до {to}?", upd_yes: "Обновить",
    upd_note: "Хаб заменит профиль на новую версию пакета. Пока не подтвердишь, ничего не меняется.",
    upd_unknown: "Плагин не смог выяснить, что меняется в профиле. Это версия пакета {to}.",
    upd_profile: "CLAUDE.md: добавлено строк {added}, убрано {removed}", upd_profile_new: "CLAUDE.md: в пакете новый профиль",
    upd_profile_same: "CLAUDE.md: без изменений",
    upd_more: "…и ещё строк: {n}", upd_tools_add: "Инструменты добавлены: {list}", upd_tools_del: "Инструменты убраны: {list}",
    upd_plugins_add: "Плагины добавлены: {list}", upd_plugins_del: "Плагины убраны: {list}",
  },
};
export function tr(key, vars = {}, lang = hub && hub.lang) {
  const base = String(lang || "en").split("-")[0].toLowerCase();
  const s = (Object.hasOwn(STR, base) ? STR[base] : STR.en)[key] ?? STR.en[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => (Object.hasOwn(vars, k) ? String(vars[k]) : ""));
}

let hub = null;
let list = null;      // catalog packages; null: not loaded yet
let failed = "";      // why loading failed, not a ready string: translated when shown
let ui = null;        // view nodes, kept between snapshots
let sig = "";
let shown = null;   // view root: hub.redraw redraws the list, not the view; after loading and button clicks we draw ourselves
let sure = "";      // which card shows "Remove?"
let sureShare = ""; // which card shows "Share?"
let sureUpdate = ""; // which card shows "Update?" with what changes
const errors = {};  // name -> a ready string about the hub's refusal on the card
let status = null;  // the process's status.json: {checked_at, req, rows: {agent: {installed, latest, update, error}}}
let checking = "";  // token of the running check; empty: none running
let result = null;  // result of the last check: {key, vars}, translated when shown
let timer = 0;
const repaint = () => { if (shown) render(shown, hub.snapshot()); };

const hubName = (sessions) => ((sessions || []).find((s) => s.kind === "hub") || {}).name || "hub";
const keep = (key) => { try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch { return {}; } };
const asked = () => keep(STORE);
const dropped = () => keep(STORE_DROP);
const updating = () => keep(STORE_UPD);
const sharing = () => keep(STORE_SHARE);
const mark = (key, name, on) => {
  const m = keep(key);
  if (on) m[name] = Date.now(); else delete m[name];
  try { localStorage.setItem(key, JSON.stringify(m)); } catch { /* private mode: just do not keep it */ }
};
export const installText = (name) => `Install the specialist from the catalog: specialists install ${name}`;
// A removal request is the owner's word (the button and the confirmation on the card). An agent is retired by the
// owner or by the hub on the owner's word (--for mN): the mN of this request is that word. Without closing the session,
// "Install" would later hit a taken name.
// local: the agent is not in the catalog; `specialists remove` refuses it, only retiring and closing the session remain.
export const removeText = (name, local = false) =>
  `The owner pressed "Remove" for the specialist ${name} in the catalog and confirmed it: this is the owner's word. ` +
  `Remove it completely: ` + (local ? "" : `specialists remove ${name}; then `) +
  `retire the agent (hub session role ${name} worker --for <the mN of this request>), ` +
  `hub session close ${name} and hub session remove ${name}. If it fails, say why.`;
// "Share" is the owner's word; the hub decides who packs the agent.
export const shareText = (name) =>
  `The owner pressed "Share" for the specialist ${name} in the catalog: this is the owner's word. ` +
  `Pack ${name} as a specialist package (profile, CLAUDE.md, tools, test cases) and add it to the catalog ` +
  `specialists.json; leave out keys and personal data.`;

export const updateText = (name) => `Update the specialist from the catalog: specialists update ${name}`;

// Built-in (system) agents of the hub: the ones the core always names (core/system.py -> session.system in the snapshot)
export const builtins = (sessions) => (sessions || []).filter((s) => s.system && s.kind !== "hub")
  .map((s) => ({ name: s.name, icon: s.icon || s.own_icon || "", about: s.about || "", state: "builtin" }));

// Agents in the hub without a package in the catalog: permanent (role agent), not built in, not the hub
export const unlisted = (sessions, names) => {
  const known = new Set(names || []);
  return (sessions || []).filter((s) => s.role === "agent" && !s.system && s.kind !== "hub" && !known.has(s.name))
    .map((s) => ({ name: s.name, icon: s.icon || s.own_icon || "", about: s.about || "" }))
    .sort((a, b) => a.name.localeCompare(b.name));
};

// row state: builtin: built in; have: the agent is in the hub; drop: removal asked recently; stuck: removal asked
// long ago and the agent is still there; wait: install asked recently; ask: can be asked
export function stateOf(name, sessions, ask = {}, now = Date.now(), drop = {}) {
  const here = (sessions || []).find((s) => s.name === name && s.kind !== "hub");
  if (here && here.system) return "builtin";
  if (here) {
    if (!drop[name]) return "have";
    return now - drop[name] < DROP_TTL ? "drop" : "stuck";
  }
  return ask[name] && now - ask[name] < ASK_TTL ? "wait" : "ask";
}

// update of an installed one: null: no data or already the latest; wait: asked recently and the version is unchanged
export function updateOf(name, st, upd = {}, now = Date.now()) {
  const r = st && st.rows && Object.hasOwn(st.rows, name) ? st.rows[name] : null;
  if (!r || !r.update) return null;
  const at = upd[`${name}@${r.installed}`];
  return { from: r.installed, to: r.latest, wait: !!at && now - at < UPD_TTL, changes: r.changes || null };
}

// what the owner confirms before "Update": a list of ready lines (a diff of CLAUDE.md goes apart, in `diff`);
// no data from the process: one line saying so, the update is still the owner's decision
export function changeLines(changes, to = "") {
  const c = changes && typeof changes === "object" ? changes : null;
  if (!c || !c.profile) return { lines: [tr("upd_unknown", { to })], diff: [] };
  const p = c.profile, lines = [];
  if (!p.known) lines.push(tr("upd_profile_new"));
  else if (!p.added && !p.removed) lines.push(tr("upd_profile_same"));
  else lines.push(tr("upd_profile", { added: p.added, removed: p.removed }));
  const list = (o, add, del) => {
    if (o && o.added && o.added.length) lines.push(tr(add, { list: o.added.join(", ") }));
    if (o && o.removed && o.removed.length) lines.push(tr(del, { list: o.removed.join(", ") }));
  };
  list(c.tools, "upd_tools_add", "upd_tools_del");
  list(c.plugins, "upd_plugins_add", "upd_plugins_del");
  const diff = Array.isArray(p.lines) ? p.lines.map(String) : [];
  if (p.more) diff.push(tr("upd_more", { n: p.more }));
  return { lines, diff };
}

// the check result from status.json: what to show next to the button
export function verdict(st) {
  const rows = Object.values((st && st.rows) || {});
  if (!rows.length) return { key: "none", vars: {} };
  const n = rows.filter((r) => r.update).length, bad = rows.filter((r) => !r.latest && r.error);
  if (bad.length === rows.length) return { key: "check_failed", vars: { err: bad[0].error }, bad: true };
  return { key: n ? "found" : "all_latest", vars: { n }, extra: bad.length ? { key: "check_partial", vars: { n: bad.length } } : null };
}

// icons in the theme's style: an outline in the text color (currentColor), 24x24
const PATHS = {
  trash: ["M4 7h16", "M10 11v6", "M14 11v6", "M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12", "M9 7V4h6v3"],
  lock: ["M8 11V8a4 4 0 0 1 8 0v3"],
};
function glyph(name) {
  const ns = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(ns, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("class", "sp-glyph");
  s.setAttribute("aria-hidden", "true");
  const mk = (tag, attrs) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    s.append(n);
  };
  if (name === "lock") mk("rect", { x: 5, y: 11, width: 14, height: 9, rx: 2 });
  for (const d of PATHS[name]) mk("path", { d });
  return s;
}

export default function register(h) {
  hub = h;
  hub.addStyle("style.css");
  hub.addView({ id: ID, title: tr("title"), subtitle: tr("subtitle"), icon: "icon.svg", render, show: show });
  plus(hub, SLOTS);
}

// the "+" in the header of the "Specialists" group: the slot is a hub addition, a hub without it would show a plugin
// error for an unknown slot, so the slot is taken only when the page lists it; none: the view in the ☰ menu is enough
export function plus(h, slots) {
  if (!Array.isArray(slots) || !slots.includes(GROUP_SLOT)) return false;
  h.addSlot(GROUP_SLOT, {
    id: "catalog",
    render(root, snap, ctx) {
      if (ctx.group !== "agents") return root.replaceChildren();
      if (root.firstChild) return;
      const b = h.el("button", "sp-plus", "+");
      b.type = "button";
      b.title = tr("plus");
      b.setAttribute("aria-label", tr("plus"));
      b.addEventListener("click", (e) => { e.stopPropagation(); h.go(ID); });
      root.append(b);
    },
  });
  return true;
}

// the slots the page knows: its own list (ext.js exports it); no list (another page, a test): none
export async function slotNames(load = () => import("/static/js/ext.js")) {
  try {
    const m = await load();
    return m && m.SLOTS && typeof m.SLOTS === "object" ? Object.keys(m.SLOTS) : [];
  } catch { return []; }
}
const SLOTS = await slotNames();

function show() {
  load();
  readStatus().then(() => { sig = ""; repaint(); keepPolling(); });
}

async function readStatus() {
  try {
    const r = await fetch(hub.url("status.json"), { cache: "no-store" });
    if (!r.ok) return null;
    status = await r.json();
  } catch { /* no process yet or the file is being written: the previous status stays */ }
  return status;
}

// while a check runs or an update was asked, read status.json every POLL: the page does not learn the answer or the new version by itself
function keepPolling() {
  clearTimeout(timer);
  const upd = updating(), now = Date.now();
  const waiting = Object.values(upd).some((at) => now - at < UPD_TTL);
  if (!checking && !waiting) return;
  timer = setTimeout(async () => {
    await readStatus();
    if (checking && status && status.req === checking) finish();
    else if (checking && Date.now() - Number(checking.split("-")[1]) > CHECK_WAIT) { checking = ""; result = { key: "check_silent", vars: { min: Math.round(CHECK_WAIT / 60000) } }; }
    sig = "";
    repaint();
    keepPolling();
  }, POLL);
}

function finish() {
  checking = "";
  result = verdict(status);
}

async function check() {
  if (checking) return;
  checking = `c-${Date.now()}`;
  result = null;
  sig = "";
  repaint();
  const res = await hub.postFeed(`check ${checking}`);
  if (res && res.error) {
    checking = "";
    result = { key: "check_failed", vars: { err: res.error }, bad: true };
    sig = "";
    repaint();
    return;
  }
  keepPolling();
}

let loading = false;
async function load() {
  if (list || loading) return;
  loading = true;
  try {
    const r = await fetch(hub.url("specialists.json"), { cache: "no-cache" });
    if (!r.ok) throw new Error(String(r.status));
    list = (await r.json()).filter((x) => x && x.name);
    failed = "";
  } catch (e) {
    failed = String(e.message || e);
  }
  loading = false;
  sig = "";
  repaint();
}

function render(root, snap) {
  shown = root;
  if (!ui) {
    ui = { page: hub.el("div", "sp-page"), title: hub.el("h1", "sp-title"), sub: hub.el("p", "sp-sub"),
      bar: hub.el("div", "sp-bar"), rows: hub.el("div", "sp-rows"), note: hub.el("p", "sp-note") };
    ui.page.append(ui.title, ui.sub, ui.bar, ui.rows, ui.note);
    ui.title.textContent = tr("title");
    ui.sub.textContent = tr("sub");
  }
  if (root.firstChild !== ui.page) root.replaceChildren(ui.page);
  if (!list && !failed) { load(); ui.note.textContent = tr("loading"); return; }
  ui.note.textContent = failed ? tr("load_failed", { err: failed }) : "";
  const sessions = (snap || {}).sessions || [], ask = asked(), drop = dropped(), upd = updating(), shared = sharing(), now = Date.now();
  if (sessions.length) for (const name of Object.keys(drop)) if (!sessions.some((s) => s.name === name)) mark(STORE_DROP, name, false);   // removed: the request is done
  const mine = builtins(sessions);
  const system = new Set(mine.map((b) => b.name));
  // a built-in agent with the name of a catalog package is shown once, as built in
  const rows = (list || []).filter((p) => !system.has(p.name))
    .map((p) => {
      const state = stateOf(p.name, sessions, ask, now, drop);
      const sr = status && status.rows && Object.hasOwn(status.rows, p.name) ? status.rows[p.name] : null;
      return { ...p, state, upd: state === "have" ? updateOf(p.name, status, upd, now) : null,
        verr: state === "have" && sr && !sr.latest && sr.error ? sr.error : "",
        have_ver: state === "have" && sr ? sr.installed : "" };
    });
  // "not in the catalog": in the hub without a package; they get "Share" and the trash (a built-in one with a package name is shown above as built in)
  const local = unlisted(sessions, (list || []).map((p) => p.name)).map((p) => ({ ...p, local: true,
    state: stateOf(p.name, sessions, {}, now, drop), shared: !!shared[p.name] && now - shared[p.name] < SHARE_TTL }));
  rows.push(...local, ...mine);
  const next = JSON.stringify([sure, sureShare, sureUpdate, errors, rows, checking, result]);
  if (next === sig) return;
  sig = next;
  bar();
  ui.rows.replaceChildren(...rows.map(row));
  if (list && !rows.length) ui.note.textContent = tr("empty");
}

// on top: the check button and its result next to it
function bar() {
  const b = hub.el("button", "btn small sp-check", checking ? tr("checking") : tr("check"));
  b.type = "button";
  b.disabled = !!checking;
  b.title = tr("check_title");
  b.addEventListener("click", check);
  const out = [b];
  if (result) {
    const text = tr(result.key, result.vars) + (result.extra ? " " + tr(result.extra.key, result.extra.vars) : "");
    out.push(hub.el("span", result.bad || result.key === "check_silent" ? "sp-checked sp-err" : "sp-checked", text));
  }
  ui.bar.replaceChildren(...out);
}

function row(p) {
  const r = hub.el("div", "sp-row");
  r.dataset.name = p.name;
  r.dataset.state = p.state;
  if (p.local) r.dataset.local = "1";
  const ic = hub.el("div", "sp-icon", p.icon || "🧩");
  const body = hub.el("div", "sp-body");
  const top = hub.el("div", "sp-top");
  top.append(hub.el("span", "sp-name", p.name),
    hub.el("span", "sp-ver", p.upd ? `v${p.upd.from} → v${p.upd.to}` : p.have_ver ? "v" + p.have_ver : p.version ? "v" + p.version : ""));
  if (p.local) {
    const badge = hub.el("span", "sp-badge", tr("unlisted"));
    badge.title = tr("unlisted_title");
    top.append(badge);
  }
  body.append(top, hub.el("div", "sp-about", p.about || ""));
  if (p.state === "stuck") body.append(hub.el("div", "sp-err", tr(p.local ? "stuck_local" : "stuck", { min: DROP_TTL / 60000 })));
  if (p.verr) body.append(hub.el("div", "sp-err", tr("row_failed", { err: p.verr })));
  if (errors[p.name]) body.append(hub.el("div", "sp-err", errors[p.name]));
  const act = hub.el("div", "sp-act");
  let confirm = null;
  if (p.state === "builtin") {
    const b = hub.el("span", "sp-builtin");
    b.title = tr("builtin_title");
    b.append(glyph("lock"), hub.el("span", null, tr("builtin")));
    act.append(b);
  } else if (p.state === "have" || p.state === "stuck") {
    if (sure === p.name) {
      confirm = ask(tr("sure", { name: p.name }), tr(p.local ? "sure_note_local" : "sure_note"), "danger sp-yes", tr("sure_yes"),
        (yes) => remove(p.name, yes, p.local), () => { sure = ""; sig = ""; repaint(); });
    } else if (sureShare === p.name) {
      confirm = ask(tr("share_sure", { name: p.name }), tr("share_note", { name: p.name }), "primary sp-yes sp-share-yes", tr("share_yes"),
        (yes) => share(p.name, yes), () => { sureShare = ""; sig = ""; repaint(); });
    } else if (sureUpdate === p.name && p.upd && !p.upd.wait) {
      const ch = changeLines(p.upd.changes, p.upd.to);
      confirm = ask(tr("upd_sure", { name: p.name, to: p.upd.to }), tr("upd_note"), "primary sp-yes sp-upd-yes", tr("upd_yes"),
        (yes) => update(p.name, p.upd.from, yes), () => { sureUpdate = ""; sig = ""; repaint(); }, ch);
    } else {
      if (p.upd) {
        const u = hub.el("button", "btn small" + (p.upd.wait ? "" : " primary") + " sp-upd", p.upd.wait ? tr("asked") : tr("update"));
        u.type = "button";
        u.disabled = p.upd.wait;
        u.title = p.upd.wait ? tr("update_wait_title") : tr("update_title", { name: p.name });
        u.addEventListener("click", () => { sureUpdate = p.name; sure = sureShare = ""; delete errors[p.name]; sig = ""; repaint(); });
        act.append(u);
      } else if (p.state === "have" && !p.local) act.append(hub.el("span", "sp-have", tr("have")));
      if (p.local) {
        const sh = hub.el("button", "btn small sp-share" + (p.shared ? "" : " primary"), p.shared ? tr("shared") : tr("share"));
        sh.type = "button";
        sh.disabled = p.shared;
        sh.title = p.shared ? tr("shared_title", { name: p.name }) : tr("share_title", { name: p.name });
        sh.addEventListener("click", () => { sureShare = p.name; sure = sureUpdate = ""; delete errors[p.name]; sig = ""; repaint(); });
        act.append(sh);
      }
      act.append(trash(p.name));
    }
  } else if (p.state === "drop") {
    const b = hub.el("button", "btn small", tr("removing"));
    b.type = "button";
    b.disabled = true;
    b.title = tr("removing_title");
    act.append(b);
  } else {
    const b = hub.el("button", "btn small" + (p.state === "ask" ? " primary" : ""), p.state === "wait" ? tr("asked") : tr("install"));
    b.type = "button";
    b.disabled = p.state === "wait";
    b.title = p.state === "wait" ? tr("wait_title") : tr("install_title", { name: p.name });
    b.addEventListener("click", () => install(p.name, b));
    act.append(b);
  }
  r.append(ic, body, act);
  if (confirm) r.append(confirm);
  return r;
}

// the trash: only the icon, a 44x44 button around it (see style.css), the name in the tooltip and for screen readers
function trash(name) {
  const del = hub.el("button", "sp-del");
  del.type = "button";
  del.title = tr("remove_title", { name });
  del.setAttribute("aria-label", tr("remove_title", { name }));
  del.append(glyph("trash"));
  del.addEventListener("click", () => { sure = name; sureShare = sureUpdate = ""; delete errors[name]; sig = ""; repaint(); });
  return del;
}

// a confirmation across the card: the question, what exactly happens, two buttons
function ask(question, note, yesClass, yesText, onYes, onNo, extra = null) {
  const box = hub.el("div", "sp-confirm");
  const text = hub.el("div", "sp-confirm-text");
  text.append(hub.el("div", "sp-sure", question), hub.el("div", "sp-confirm-note", note));
  if (extra) {
    for (const l of extra.lines) text.append(hub.el("div", "sp-confirm-note", l));
    if (extra.diff.length) text.append(hub.el("pre", "sp-diff", extra.diff.join("\n")));
  }
  const yes = hub.el("button", "btn small " + yesClass, yesText);
  const no = hub.el("button", "btn small sp-no", tr("sure_no"));
  yes.type = no.type = "button";
  yes.addEventListener("click", () => onYes(yes));
  no.addEventListener("click", onNo);
  const btns = hub.el("div", "sp-confirm-btns");
  btns.append(yes, no);
  box.append(text, btns);
  return box;
}

async function install(name, b) {
  b.disabled = true;
  delete errors[name];
  const res = await hub.post("/api/send", { session: hubName((hub.snapshot() || {}).sessions), text: installText(name), action: true });
  if (res && res.error) {
    b.disabled = false;
    errors[name] = tr("install_refused", { err: res.error });
  } else {
    mark(STORE_DROP, name, false);
    mark(STORE, name, true);
  }
  sig = "";
  repaint();
}

async function remove(name, b, local = false) {
  b.disabled = true;
  const res = await hub.post("/api/send", { session: hubName((hub.snapshot() || {}).sessions), text: removeText(name, local), action: true });
  sure = "";
  if (res && res.error) {
    errors[name] = tr("remove_refused", { err: res.error });
  } else {
    delete errors[name];
    mark(STORE, name, false);
    mark(STORE_DROP, name, true);
  }
  sig = "";
  repaint();
}

async function share(name, b) {
  b.disabled = true;
  const res = await hub.post("/api/send", { session: hubName((hub.snapshot() || {}).sessions), text: shareText(name), action: true });
  sureShare = "";
  if (res && res.error) errors[name] = tr("share_refused", { err: res.error });
  else {
    delete errors[name];
    mark(STORE_SHARE, name, true);
  }
  sig = "";
  repaint();
}

async function update(name, from, b) {
  b.disabled = true;
  sureUpdate = "";
  delete errors[name];
  const res = await hub.post("/api/send", { session: hubName((hub.snapshot() || {}).sessions), text: updateText(name), action: true });
  if (res && res.error) {
    b.disabled = false;
    errors[name] = tr("update_refused", { err: res.error });
  } else {
    mark(STORE_UPD, `${name}@${from}`, true);
  }
  sig = "";
  repaint();
  keepPolling();
}

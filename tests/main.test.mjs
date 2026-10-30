// Catalog page: card states, built-in agents, trash with confirmation, "Share" for agents not in the catalog. Run: node --test tests/main.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

// tiny DOM: enough to build the cards and press buttons
class Node {
  constructor(tag, cls) { this.tag = tag; this.className = cls || ""; this.children = []; this.dataset = {}; this.attrs = {}; this.handlers = {}; this.textContent = ""; }
  append(...n) { this.children.push(...n); }
  replaceChildren(...n) { this.children = n; }
  get firstChild() { return this.children[0] || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(ev, fn) { this.handlers[ev] = fn; }
  click() { return this.handlers.click && this.handlers.click({ stopPropagation() {} }); }
  walk(f) { f(this); this.children.forEach((c) => c.walk(f)); }
  find(pred) { const out = []; this.walk((n) => pred(n) && out.push(n)); return out; }
  text() { return [this.textContent, ...this.children.map((c) => c.text())].join(" ").replace(/\s+/g, " ").trim(); }
}
globalThis.document = { createElementNS: (_, tag) => new Node(tag) };
const store = {};
globalThis.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } };
let STATUS = null;   // what is in the process status.json; null means no file
globalThis.fetch = async (url) => (String(url) === "status.json"
  ? { ok: !!STATUS, json: async () => STATUS } : { ok: true, json: async () => CATALOG });
const CATALOG = [
  { name: "analyst", version: "0.1.2", icon: "📊", about: "Analyst" },
  { name: "writer", version: "0.1.0", icon: "✍️", about: "Writer" },
];

const mod = await import("../main.js");

const sent = [];
const feed = [];
let snap = { sessions: [] };
const hub = {
  lang: "ru",
  el: (tag, cls, text) => { const n = new Node(tag, cls); if (text != null) n.textContent = text; return n; },
  addStyle() {}, addView(v) { hub.view = v; }, addSlot() {}, go() {},
  postFeed: async (text) => { feed.push(text); return hub.feedReply; }, feedReply: { ok: true },
  url: (f) => f, snapshot: () => snap, post: async (path, body) => { sent.push([path, body]); return hub.reply; },
  reply: { ok: true },
};
mod.default(hub);
const root = new Node("div");
const draw = async () => { hub.view.render(root, snap); await new Promise((r) => setImmediate(r)); hub.view.render(root, snap); };
const cards = () => Object.fromEntries(root.find((n) => n.className === "sp-row").map((r) => [r.dataset.name, r]));
const button = (card, cls) => card.find((n) => n.tag === "button" && n.className.split(" ").includes(cls))[0];
const hubSess = { name: "hub", kind: "hub" };

test("stateOf: built-in, installed, being removed, failed, waiting, can ask", () => {
  const now = 1e9;
  const ss = [hubSess, { name: "a" }, { name: "dev", system: true }];
  assert.equal(mod.stateOf("dev", ss, {}, now), "builtin");
  assert.equal(mod.stateOf("a", ss, {}, now), "have");
  assert.equal(mod.stateOf("a", ss, {}, now, { a: now - 60e3 }), "drop");
  assert.equal(mod.stateOf("a", ss, {}, now, { a: now - 11 * 60e3 }), "stuck");
  assert.equal(mod.stateOf("b", ss, { b: now - 60e3 }, now), "wait");
  assert.equal(mod.stateOf("b", ss, { b: now - 31 * 60e3 }, now), "ask");
  assert.equal(mod.stateOf("hub", ss, {}, now), "ask", "the hub is not a specialist");
});

test("builtins: only system agents, no hub; description and icon from the snapshot", () => {
  const got = mod.builtins([hubSess, { name: "hub-dev", system: true, about: "Hub Developer", icon: "🛠️" }, { name: "x" },
    { name: "agent-dev", system: true, own_icon: "🧬", about: "Agent Developer" }]);
  assert.deepEqual(got.map((b) => [b.name, b.icon, b.about, b.state]),
    [["hub-dev", "🛠️", "Hub Developer", "builtin"], ["agent-dev", "🧬", "Agent Developer", "builtin"]]);
});

test("tr: page language, English fallback, substitutions", () => {
  assert.equal(mod.tr("remove_title", { name: "x" }, "ru"), "Удалить x");
  assert.equal(mod.tr("remove_title", { name: "x" }, "en"), "Remove x");
  assert.equal(mod.tr("remove_title", { name: "x" }, "de-AT"), "Remove x");
  assert.equal(mod.tr("remove_title", { name: "x" }, "__proto__"), "Remove x");
  assert.equal(mod.tr("sure", { name: "x" }, "ru"), "Удалить x?");
});

test("view: catalog + built-in; built-in ones have neither Install nor a trash button", async () => {
  snap = { sessions: [hubSess, { name: "hub-dev", system: true, about: "Hub Developer: hub code", icon: "🛠️" },
    { name: "agent-dev", system: true, about: "Agent Developer" }, { name: "analyst" }] };
  await draw();
  const c = cards();
  assert.deepEqual(Object.keys(c), ["analyst", "writer", "hub-dev", "agent-dev"]);
  assert.equal(c["hub-dev"].dataset.state, "builtin");
  assert.match(c["hub-dev"].text(), /Hub Developer: hub code/);
  assert.match(c["hub-dev"].text(), /Встроен/);
  assert.equal(c["hub-dev"].find((n) => n.tag === "button").length, 0);
  assert.equal(c["writer"].dataset.state, "ask");
  assert.ok(button(c["writer"], "primary"), "\"Install\" on a not installed one");
  assert.ok(button(c["analyst"], "sp-del"), "trash on an installed one");
});

test("a catalog package matching a built-in by name gives one card, the built-in one", async () => {
  snap = { sessions: [hubSess, { name: "analyst", system: true, about: "x" }] };
  await draw();
  const rows = root.find((n) => n.className === "sp-row" && n.dataset.name === "analyst");
  assert.equal(rows.length, 1);
  assert.equal(rows[0].dataset.state, "builtin");
});

test("trash: icon only, no Delete word; name in the tooltip and aria-label", async () => {
  snap = { sessions: [hubSess, { name: "analyst" }] };
  await draw();
  const del = button(cards().analyst, "sp-del");
  assert.equal(del.text(), "", "no text on the button");
  assert.ok(del.find((n) => n.tag === "svg").length, "an icon instead");
  assert.equal(del.title, "Удалить analyst");
  assert.equal(del.attrs["aria-label"], "Удалить analyst");
  assert.doesNotMatch(cards().analyst.text(), /Удалить/);
});

test("trash: confirmation, then a request to the hub from the owner; cancel sends nothing", async () => {
  sent.length = 0;
  snap = { sessions: [hubSess, { name: "analyst" }] };
  await draw();
  button(cards().analyst, "sp-del").click();
  assert.equal(sent.length, 0, "the first press only asks");
  assert.match(cards().analyst.text(), /Удалить analyst\?/);
  assert.match(cards().analyst.text(), /файлы и прошлые чаты останутся на диске/, "the warning says what goes away and what stays");
  button(cards().analyst, "sp-no").click();
  assert.ok(button(cards().analyst, "sp-del"), "cancel brought the button back");
  assert.equal(sent.length, 0);
  button(cards().analyst, "sp-del").click();
  await button(cards().analyst, "sp-yes").click();
  assert.equal(sent.length, 1);
  const [path, body] = sent[0];
  assert.equal(path, "/api/send");
  assert.equal(body.session, "hub");
  assert.equal(body.action, true, "the page button is the owner's word, not a reply to a card");
  assert.equal(body.text, mod.removeText("analyst"));
  assert.match(body.text, /specialists remove analyst/);
  assert.match(body.text, /hub session remove analyst/);
  // the agent is still in the hub: shows Removing, no button
  assert.equal(cards().analyst.dataset.state, "drop");
  assert.match(cards().analyst.text(), /Удаляю/);
  // the agent is gone: Install again, not the Asked-the-hub line left from the earlier install request
  snap = { sessions: [hubSess] };
  await draw();
  assert.equal(cards().analyst.dataset.state, "ask");
  assert.ok(button(cards().analyst, "primary"));
});

test("hub refusal shows on the card, not silently", async () => {
  hub.reply = { error: "hub busy" };
  snap = { sessions: [hubSess, { name: "writer" }] };
  await draw();
  button(cards().writer, "sp-del").click();
  await button(cards().writer, "sp-yes").click();
  hub.reply = { ok: true };
  assert.match(cards().writer.text(), /Хаб не принял просьбу: hub busy/);
  assert.equal(cards().writer.dataset.state, "have", "nothing was requested, all in place");
});

test("removal requested long ago, agent still there: the card says it failed and offers a retry", async () => {
  store["specialists:removing"] = JSON.stringify({ analyst: Date.now() - 11 * 60e3 });
  snap = { sessions: [hubSess, { name: "analyst" }] };
  await draw();
  assert.equal(cards().analyst.dataset.state, "stuck");
  assert.match(cards().analyst.text(), /не снял за 10 мин/);
  assert.ok(button(cards().analyst, "sp-del"));
});

test("English page: strings from the en table", async () => {
  hub.lang = "en";
  store["specialists:removing"] = "{}";
  snap = { sessions: [hubSess, { name: "hub-dev", system: true, about: "Hub Developer" }, { name: "analyst" }] };
  root.children = [];
  await draw();
  const c = cards();
  assert.match(c["hub-dev"].text(), /Built in/);
  assert.match(c["analyst"].text(), /✓ Installed/);
  assert.doesNotMatch(c["analyst"].text(), /Remove/);
  assert.equal(button(c["analyst"], "sp-del").title, "Remove analyst");
  assert.match(c["writer"].text(), /Install/);
  hub.lang = "ru";
});

test("menu icon is the outline icon.svg in the theme color (the market cover icon.png stays)", async () => {
  const { readFileSync, existsSync } = await import("node:fs");
  assert.equal(hub.view.icon, "icon.svg");
  assert.match(readFileSync(new URL("../icon.svg", import.meta.url), "utf8"), /fill="currentColor"/);
  assert.ok(existsSync(new URL("../icon.png", import.meta.url)));
});

// ---- "Check for updates" ----
const POLL_WAIT = 2600;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const checkBtn = () => root.find((n) => n.tag === "button" && n.className.split(" ").includes("sp-check"))[0];
const barText = () => root.find((n) => n.className === "sp-bar")[0].text();
const row = (installed, latest, extra = {}) => ({ package: "x", installed, latest, update: latest !== installed, error: "", ...extra });

test("updateOf: only for a lagging version; a recent request means wait, a changed version means clean again", () => {
  const st = { rows: { analyst: row("0.1.2", "0.2.0"), writer: row("0.1.0", "0.1.0") } };
  assert.deepEqual(mod.updateOf("analyst", st, {}, 1e9), { from: "0.1.2", to: "0.2.0", wait: false, changes: null });
  assert.equal(mod.updateOf("writer", st, {}, 1e9), null);
  assert.equal(mod.updateOf("nobody", st, {}, 1e9), null);
  assert.equal(mod.updateOf("analyst", null, {}, 1e9), null);
  assert.equal(mod.updateOf("analyst", st, { "analyst@0.1.2": 1e9 - 60e3 }, 1e9).wait, true);
  assert.equal(mod.updateOf("analyst", st, { "analyst@0.1.2": 1e9 - 11 * 60e3 }, 1e9).wait, false, "the request expired");
  assert.equal(mod.updateOf("analyst", st, { "analyst@0.0.9": 1e9 }, 1e9).wait, false, "requested from another version");
  assert.equal(mod.updateOf("__proto__", st, {}, 1e9), null);
});

test("verdict: updates, all latest, nobody installed, whole check failed, part not checked", () => {
  assert.equal(mod.verdict({ rows: {} }).key, "none");
  assert.equal(mod.verdict(null).key, "none");
  assert.deepEqual(mod.verdict({ rows: { a: row("1", "2"), b: row("1", "1") } }), { key: "found", vars: { n: 1 }, extra: null });
  assert.equal(mod.verdict({ rows: { a: row("1", "1") } }).key, "all_latest");
  const bad = row("1", "", { update: false, error: "Could not resolve host" });
  const all = mod.verdict({ rows: { a: bad, b: bad } });
  assert.equal(all.key, "check_failed");
  assert.equal(all.vars.err, "Could not resolve host");
  const some = mod.verdict({ rows: { a: bad, b: row("1", "1") } });
  assert.equal(some.key, "all_latest");
  assert.deepEqual(some.extra, { key: "check_partial", vars: { n: 1 } });
});

test("top button: the check sends a request to the process, finds a newer one, Update replaces Installed, request to the hub, then Installed again", async () => {
  sent.length = 0; feed.length = 0; hub.reply = { ok: true };
  snap = { sessions: [hubSess, { name: "analyst" }, { name: "writer" }] };
  STATUS = null;
  await draw();
  assert.ok(checkBtn(), "the button is there while nothing was checked");
  assert.match(checkBtn().text(), /Проверить обновления/);
  assert.match(cards().analyst.text(), /✓ Поставлен/);
  assert.equal(cards().analyst.find((n) => n.className.includes("sp-upd")).length, 0);
  await checkBtn().click();
  assert.equal(feed.length, 1);
  const token = feed[0].match(/^check (c-\d+)$/)[1];
  assert.match(checkBtn().text(), /Проверяю/);
  assert.equal(checkBtn().disabled, true, "while it runs, it cannot be pressed twice");
  // the process replied: analyst has a newer version, writer does not
  STATUS = { checked_at: 1, req: token, rows: { analyst: row("0.1.2", "0.2.0"), writer: row("0.1.0", "0.1.0") } };
  await wait(2300);
  assert.match(barText(), /Есть обновления: 1/);
  assert.equal(checkBtn().disabled, false);
  const c = cards();
  const upd = button(c.analyst, "sp-upd");
  assert.equal(upd.text(), "Обновить");
  assert.doesNotMatch(c.analyst.text(), /✓ Поставлен/, "Update replaces Installed");
  assert.ok(button(c.analyst, "sp-del"), "trash stays");
  assert.match(c.analyst.text(), /v0\.1\.2 → v0\.2\.0/);
  assert.match(c.writer.text(), /✓ Поставлен/);
  assert.equal(button(c.writer, "sp-upd"), undefined);
  // Update asks the owner first and only then goes to the hub as a request, like Install
  sent.length = 0;
  await upd.click();
  assert.equal(sent.length, 0, "the first press only asks");
  assert.ok(button(cards().analyst, "sp-upd-yes"), "the card asks to confirm");
  await button(cards().analyst, "sp-upd-yes").click();
  assert.deepEqual(sent.at(-1), ["/api/send", { session: "hub", text: mod.updateText("analyst"), action: true }]);
  assert.match(mod.updateText("analyst"), /specialists update analyst/);
  const asked = button(cards().analyst, "sp-upd");
  assert.equal(asked.text(), "Попросили хаб…");
  assert.equal(asked.disabled, true);
  // the hub updated: the process sees the new installed version, Installed again
  STATUS = { checked_at: 1, req: token, rows: { analyst: row("0.2.0", "0.2.0"), writer: row("0.1.0", "0.1.0") } };
  await wait(2300);
  assert.match(cards().analyst.text(), /✓ Поставлен/);
  assert.equal(button(cards().analyst, "sp-upd"), undefined);
  assert.match(cards().analyst.text(), /v0\.2\.0/);
});

test("nothing new gives All latest; hub refusal on Update shows as a line on the card", async () => {
  feed.length = 0;
  snap = { sessions: [hubSess, { name: "analyst" }] };
  await draw();
  await checkBtn().click();
  const token = feed[0].split(" ")[1];
  STATUS = { checked_at: 2, req: token, rows: { analyst: row("0.2.0", "0.2.0") } };
  await wait(2300);
  assert.equal(barText().replace(/Проверить обновления/, "").trim(), "Всё последнее");
  // refusal on Update
  STATUS = { checked_at: 3, req: token, rows: { analyst: row("0.2.0", "0.3.0") } };
  hub.view.show();   // page reopened: reads status.json
  await wait(50);
  await draw();
  hub.reply = { error: "hub busy" };
  await button(cards().analyst, "sp-upd").click();
  await button(cards().analyst, "sp-upd-yes").click();
  assert.match(cards().analyst.text(), /Хаб не принял просьбу: hub busy/);
  assert.equal(button(cards().analyst, "sp-upd").disabled, false, "can be pressed again");
  hub.reply = { ok: true };
  STATUS = null;
});

test("failure: the page does not crash, the cause is a line; the post did not go out and the package network failed", async () => {
  feed.length = 0;
  snap = { sessions: [hubSess, { name: "analyst" }, { name: "writer" }] };
  await draw();
  hub.feedReply = { error: "no link" };
  await checkBtn().click();
  assert.match(barText(), /Проверка не удалась: no link/);
  assert.equal(checkBtn().disabled, false);
  hub.feedReply = { ok: true };
  await checkBtn().click();
  const token = feed.at(-1).split(" ")[1];
  const down = (n) => row(n, "", { update: false, error: "Could not resolve host: github.com" });
  STATUS = { checked_at: 4, req: token, rows: { analyst: down("0.2.0"), writer: down("0.1.0") } };
  await wait(2300);
  assert.match(barText(), /Проверка не удалась: Could not resolve host/);
  assert.match(cards().analyst.text(), /Не удалось узнать версию: Could not resolve host/);
  assert.match(cards().analyst.text(), /✓ Поставлен/, "the card is alive: version unknown, but the agent is in place");
  STATUS = null;
});

test("English page: check strings from the en table", () => {
  assert.equal(mod.tr("check", {}, "en"), "Check for updates");
  assert.equal(mod.tr("update", {}, "en"), "Update");
  assert.equal(mod.tr("all_latest", {}, "en"), "Everything is up to date");
  assert.equal(mod.tr("found", { n: 2 }, "ru"), "Есть обновления: 2");
});

// page polling lives while there is a fresh update request: after the tests we clear it and let the timer finish, otherwise node does not exit
test.after(async () => {
  for (const k of Object.keys(store)) delete store[k];
  await wait(POLL_WAIT);
});

// ---- Not in the catalog: share and delete ----
const mine = { name: "my-agent", role: "agent", icon: "🦊", about: "My agent" };

test("unlisted: permanent agents not from the catalog; built-in ones, the hub, executors and catalog packages are not", () => {
  const got = mod.unlisted([hubSess, mine, { name: "zed", role: "agent", own_icon: "🧿" }, { name: "analyst", role: "agent" },
    { name: "hub-dev", role: "agent", system: true }, { name: "w1", role: "worker" }, { name: "plain" }], ["analyst", "writer"]);
  assert.deepEqual(got.map((x) => [x.name, x.icon, x.about]), [["my-agent", "🦊", "My agent"], ["zed", "🧿", ""]]);
});

test("shareText: the owner's word, what to pack, what to leave out", () => {
  const t = mod.shareText("my-agent");
  assert.match(t, /The owner pressed "Share" for the specialist my-agent in the catalog: this is the owner's word/);
  assert.match(t, /Pack my-agent as a specialist package/);
  assert.match(t, /add it to the catalog specialists\.json; leave out keys and personal data/);
  assert.doesNotMatch(t, /Eugenius|agent-dev/, "no private repo or agent names");
});

test("removeText for an agent not in the catalog: no specialists remove, only retiring and closing the session", () => {
  const t = mod.removeText("my-agent", true);
  assert.doesNotMatch(t, /specialists remove/);
  assert.match(t, /hub session role my-agent worker --for/);
  assert.match(t, /hub session close my-agent and hub session remove my-agent/);
  assert.match(mod.removeText("analyst"), /specialists remove analyst; then retire the agent/);
});

test("Not-in-the-catalog card: label, Share and trash; catalog and built-in cards have none of these", async () => {
  snap = { sessions: [hubSess, mine, { name: "analyst", role: "agent" }, { name: "hub-dev", system: true, role: "agent" }] };
  root.children = [];
  await draw();
  const c = cards();
  assert.deepEqual(Object.keys(c), ["analyst", "writer", "my-agent", "hub-dev"]);
  assert.equal(c["my-agent"].dataset.local, "1");
  assert.match(c["my-agent"].text(), /Не в каталоге/);
  assert.match(c["my-agent"].text(), /My agent/);
  assert.ok(button(c["my-agent"], "sp-share"), "\"Share\"");
  assert.ok(button(c["my-agent"], "sp-del"), "trash");
  assert.doesNotMatch(c["my-agent"].text(), /Поставлен/, "the Installed mark is not needed for such a card");
  assert.equal(button(c["analyst"], "sp-share"), undefined);
  assert.doesNotMatch(c["analyst"].text(), /Не в каталоге/);
  assert.equal(c["hub-dev"].find((n) => n.tag === "button").length, 0);
});

test("Share: warning, then a request to the hub from the owner; cancel sends nothing; then the Sent-to-hub mark", async () => {
  sent.length = 0;
  snap = { sessions: [hubSess, mine] };
  await draw();
  button(cards()["my-agent"], "sp-share").click();
  assert.equal(sent.length, 0, "the first press only asks");
  const ask = cards()["my-agent"].text();
  assert.match(ask, /Поделиться my-agent\?/);
  assert.match(ask, /упакует my-agent .* в пакет и добавит в каталог/, "where it goes");
  assert.match(ask, /нет ключей и личного/, "what to check");
  button(cards()["my-agent"], "sp-no").click();
  assert.ok(button(cards()["my-agent"], "sp-share"), "cancel brought the button back");
  assert.equal(sent.length, 0);
  button(cards()["my-agent"], "sp-share").click();
  await button(cards()["my-agent"], "sp-share-yes").click();
  assert.equal(sent.length, 1);
  const [path, body] = sent[0];
  assert.equal(path, "/api/send");
  assert.equal(body.session, "hub");
  assert.equal(body.action, true);
  assert.equal(body.text, mod.shareText("my-agent"));
  const after = button(cards()["my-agent"], "sp-share");
  assert.equal(after.text(), "Отправлено хабу");
  assert.equal(after.disabled, true);
  assert.ok(button(cards()["my-agent"], "sp-del"), "trash stayed");
  // came back after the deadline: allowed again
  store["specialists:sharing"] = JSON.stringify({ "my-agent": Date.now() - 7 * 3600e3 });
  await draw();
  assert.equal(button(cards()["my-agent"], "sp-share").text(), "Поделиться");
  store["specialists:sharing"] = "{}";
});

test("Share: hub refusal shows on the card, the sent label is not set", async () => {
  hub.reply = { error: "hub busy" };
  snap = { sessions: [hubSess, mine] };
  await draw();
  button(cards()["my-agent"], "sp-share").click();
  await button(cards()["my-agent"], "sp-share-yes").click();
  hub.reply = { ok: true };
  assert.match(cards()["my-agent"].text(), /Хаб не принял просьбу: hub busy/);
  assert.equal(button(cards()["my-agent"], "sp-share").text(), "Поделиться");
});

test("deleting an agent not in the catalog: warning without restore-from-catalog text, request without specialists remove", async () => {
  sent.length = 0;
  snap = { sessions: [hubSess, mine] };
  await draw();
  button(cards()["my-agent"], "sp-del").click();
  assert.match(cards()["my-agent"].text(), /Удалить my-agent\?/);
  assert.match(cards()["my-agent"].text(), /Этого агента нет в каталоге/);
  await button(cards()["my-agent"], "sp-yes").click();
  assert.equal(sent.length, 1);
  assert.equal(sent[0][1].text, mod.removeText("my-agent", true));
  assert.doesNotMatch(sent[0][1].text, /specialists remove/);
  assert.equal(cards()["my-agent"].dataset.state, "drop");
  // the session is gone, the card vanished (no package, nothing to install)
  snap = { sessions: [hubSess] };
  await draw();
  assert.equal(cards()["my-agent"], undefined);
});

test("not in the catalog, removal requested long ago, agent still there: its own explanation", async () => {
  store["specialists:removing"] = JSON.stringify({ "my-agent": Date.now() - 11 * 60e3 });
  snap = { sessions: [hubSess, mine] };
  await draw();
  assert.equal(cards()["my-agent"].dataset.state, "stuck");
  assert.match(cards()["my-agent"].text(), /не снял за 10 мин/);
  assert.doesNotMatch(cards()["my-agent"].text(), /поставленного не из этого каталога/);
  store["specialists:removing"] = "{}";
});

test("English page: Not-in-the-catalog and Share", async () => {
  hub.lang = "en";
  snap = { sessions: [hubSess, mine] };
  root.children = [];
  await draw();
  assert.match(cards()["my-agent"].text(), /Not in the catalog/);
  assert.equal(button(cards()["my-agent"], "sp-share").text(), "Share");
  assert.equal(button(cards()["my-agent"], "sp-del").title, "Remove my-agent");
  hub.lang = "ru";
});

test("no group slot in the page: plus() does nothing and does not throw; with the slot it is taken once", () => {
  const calls = [];
  const bare = { ...hub, addSlot: () => { throw new Error("no such slot"); } };
  assert.equal(mod.plus(bare, []), false);
  assert.equal(mod.plus(bare, undefined), false);
  assert.equal(mod.plus(bare, ["composer.tools"]), false);
  const withSlot = { ...hub, addSlot: (name, spec) => calls.push([name, spec.id]) };
  assert.equal(mod.plus(withSlot, ["sidebar.group", "composer.tools"]), true);
  assert.deepEqual(calls, [["sidebar.group", "catalog"]]);
});

test("slotNames: the page slots by name; an import that fails gives an empty list instead of an exception", async () => {
  assert.deepEqual(await mod.slotNames(async () => ({ SLOTS: { "composer.tools": {}, "sidebar.group": {} } })), ["composer.tools", "sidebar.group"]);
  assert.deepEqual(await mod.slotNames(async () => ({ SLOTS: { "composer.tools": {} } })), ["composer.tools"]);
  assert.deepEqual(await mod.slotNames(async () => { throw new Error("no ext.js"); }), []);
  assert.deepEqual(await mod.slotNames(async () => ({})), []);
  assert.deepEqual(await mod.slotNames(async () => null), []);
});

test("changeLines: no data from the process; new profile; no changes; added and removed lines, tools, plugins, the cut tail", () => {
  hub.lang = "ru";
  const none = mod.changeLines(null, "0.2.0");
  assert.equal(none.lines.length, 1);
  assert.match(none.lines[0], /не смог выяснить/);
  assert.deepEqual(none.diff, []);
  assert.match(mod.changeLines({}, "0.2.0").lines[0], /не смог выяснить/);
  assert.match(mod.changeLines({ profile: { known: false } }).lines[0], /новый профиль/);
  assert.match(mod.changeLines({ profile: { known: true, added: 0, removed: 0 } }).lines[0], /без изменений/);
  const full = mod.changeLines({
    profile: { known: true, added: 3, removed: 1, lines: ["+ new rule", "- old rule"], more: 5 },
    tools: { added: ["figma"], removed: ["jira", "teams"] },
    plugins: { added: ["a@pkg"], removed: [] },
  });
  assert.equal(full.lines[0], "CLAUDE.md: добавлено строк 3, убрано 1");
  assert.ok(full.lines.includes("Инструменты добавлены: figma"));
  assert.ok(full.lines.includes("Инструменты убраны: jira, teams"));
  assert.ok(full.lines.includes("Плагины добавлены: a@pkg"));
  assert.equal(full.lines.some((l) => /Плагины убраны/.test(l)), false, "an empty list gives no line");
  assert.deepEqual(full.diff, ["+ new rule", "- old rule", "…и ещё строк: 5"]);
});

test("Update: the card shows what changes in the profile, nothing goes to the hub until the owner confirms, cancel sends nothing", async () => {
  hub.lang = "ru"; hub.reply = { ok: true };
  store["specialists:updating"] = "{}";
  const changes = {
    base: "a1", to: "b2",
    profile: { known: true, added: 2, removed: 1, lines: ["+ trust the owner", "- old rule"], more: 0 },
    tools: { added: ["figma"], removed: [] }, plugins: { added: [], removed: [] },
  };
  STATUS = { checked_at: 10, req: "c-1", rows: { analyst: row("0.1.2", "0.2.0", { changes }) } };
  snap = { sessions: [hubSess, { name: "analyst" }] };
  hub.view.show();
  await wait(50);
  await draw();
  sent.length = 0;
  await button(cards().analyst, "sp-upd").click();
  assert.equal(sent.length, 0, "the first press only asks");
  const text = cards().analyst.text();
  assert.match(text, /Обновить analyst до 0\.2\.0\?/);
  assert.match(text, /CLAUDE\.md: добавлено строк 2, убрано 1/);
  assert.match(text, /Инструменты добавлены: figma/);
  assert.match(text, /\+ trust the owner/, "the diff of the profile is on the card");
  button(cards().analyst, "sp-no").click();
  assert.equal(sent.length, 0, "cancel sends nothing");
  assert.ok(button(cards().analyst, "sp-upd"), "cancel brought the button back");
  await button(cards().analyst, "sp-upd").click();
  await button(cards().analyst, "sp-upd-yes").click();
  assert.equal(sent.length, 1);
  assert.equal(sent[0][1].text, mod.updateText("analyst"));
  assert.equal(sent[0][1].action, true);
  STATUS = null;
});

test("Update without data about the change: the card says so and the owner still decides", async () => {
  hub.lang = "ru";
  store["specialists:updating"] = "{}";
  STATUS = { checked_at: 11, req: "c-2", rows: { analyst: row("0.1.2", "0.2.0") } };
  snap = { sessions: [hubSess, { name: "analyst" }] };
  hub.view.show();
  await wait(50);
  await draw();
  sent.length = 0;
  await button(cards().analyst, "sp-upd").click();
  assert.match(cards().analyst.text(), /не смог выяснить, что меняется/);
  assert.equal(sent.length, 0);
  button(cards().analyst, "sp-no").click();
  STATUS = null;
});

test("the page registers without the group slot and without ext.js (as in a hub that has no such slot)", async () => {
  const added = [];
  const bare = { ...hub, addView: (v) => added.push(["view", v.id]), addSlot: () => { throw new Error("unknown slot"); } };
  assert.doesNotThrow(() => mod.default(bare));
  assert.equal(added.length, 1, "the plugin view is there");
});

// Browser-free drag/drop event tests, executed with Node on Win+Linux.
"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const app = fs.readFileSync("mobile/app.js", "utf8");
const markup = fs.readFileSync("mobile/index.html", "utf8");
const css = fs.readFileSync("mobile/styles.css", "utf8");
const start = app.indexOf("// XEMAI_DROP_SUPPORT_BEGIN");
const end = app.indexOf("// XEMAI_DROP_SUPPORT_END", start);
assert.ok(start >= 0 && end > start, "drag-drop code must exist");
assert.match(markup, /id="fileDropOverlay"/);
assert.match(markup, /aria-live="polite"/);
assert.match(css, /file-drop-overlay\s*\{/);
assert.match(app, /void uploadSelectedFiles\(files\)/);

const handlers = {};
const events = [];
const attrs = {};
const state = {
  chatId: 1, busy: false, remoteActivity: false, chatMutation: false,
  loadingChat: false, uploadingAttachments: 0,
};
const classes = new Set(["hidden"]);
const element = {
  classList: {toggle(name, enabled) {
    if (enabled) classes.add(name);
    else classes.delete(name);
  }},
  setAttribute(k, v) { attrs[k] = v; },
};
const sandbox = {
  document: { addEventListener(name, handler) { handlers[name] = handler; } },
  window: { addEventListener(name, handler) { handlers["window:" + name] = handler; } },
  state,
  els: {fileDropOverlay: element},
  uploadSelectedFiles(files) { events.push(files.map(f => f.name)); },
  showModal(title, body) { events.push(["modal", title, body]); },
};
vm.createContext(sandbox);
vm.runInContext(app.slice(start, end), sandbox);
function drag(types, files) {
  let prevented = false;
  const e = {
    dataTransfer: {types, files: files || [], dropEffect: ""},
    relatedTarget: null,
    preventDefault() { prevented = true; },
  };
  return {e, get prevented() {return prevented;}};
}
const withoutFiles = drag(["text/plain"], []);
handlers.dragenter(withoutFiles.e);
assert.equal(withoutFiles.prevented, false, "don't interfere with text drag");
assert.ok(classes.has("hidden"));
const file = {name:"Skyrim_Stage1_Trace.txt"};
const enters = drag(["Files"], [file]);
handlers.dragenter(enters.e);
assert.equal(enters.prevented, true);
assert.ok(!classes.has("hidden"), "drop overlay should appear");
assert.equal(attrs["aria-hidden"], "false");
const over = drag(["Files"], [file]);
handlers.dragover(over.e);
assert.equal(over.e.dataTransfer.dropEffect, "copy");
const dropped = drag(["Files"], [file]);
handlers.drop(dropped.e);
assert.equal(dropped.prevented, true, "files must never navigate browser");
assert.ok(classes.has("hidden"));
assert.deepEqual(events, [["Skyrim_Stage1_Trace.txt"]]);
state.busy = true;
handlers.dragenter(drag(["Files"], [file]).e);
assert.ok(classes.has("hidden"), "not shown during active assistant reply");
const blockedDrop = drag(["Files"], [file]);
handlers.drop(blockedDrop.e);
assert.equal(blockedDrop.prevented, true);
assert.equal(events.at(-1)[0], "modal");
state.busy = false;
state.chatId = null;
handlers.dragenter(drag(["Files"], [file]).e);
assert.ok(classes.has("hidden"), "requires a selected conversation");
handlers["window:blur"]();
assert.ok(classes.has("hidden"));
console.log("Desktop chat drag-and-drop integration checks passed.");

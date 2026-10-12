"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const code = fs.readFileSync("mobile/app.js", "utf8");
const css = fs.readFileSync("mobile/styles.css", "utf8");
const ctx = {
  Number, String,
  document: {createElement: () => ({innerHTML:"", querySelector: () => null})},
  state: {bootstrap: {user:{name:"Tester"},assistant_name:"XemAi"}},
  els: {messages:{appendChild(node){ctx.captured.push(node);}}},
  captured: [],
  REPLY_ERROR_PREFIX: "retry-error",
  renderBody: s => s,
  extractAttachmentDisplay: s => ({attachments:[],text:s}),
  formatMessageTime: () => "11:45",
  escapeHtml: s => String(s).replaceAll("&","&amp;").replaceAll("<","&lt;"),
  replyInferenceLabel: () => "",
  retryLastMessage: () => {},
};
vm.createContext(ctx);
for (const name of ["supportedSpecialistRoles","specialistHelpLabel","conversationTestResult","appendMessage","messageSignature"]) {
  const match = code.match(new RegExp("function " + name + "\\([^]*?\\n\\}"));
  assert(match, "Function " + name + " missing");
  vm.runInContext(match[0],ctx);
}
vm.runInContext('const SPECIALIST_LABELS = Object.freeze({research:"Research",skyrim:"Skyrim",reviewer:"Reviewer"});',ctx);
ctx.appendMessage("assistant", "Worker response", null,null,
  {id:19,rating_score:0,rating_aspect:"understanding"});
assert(ctx.captured.pop().innerHTML.includes("★ 0/10 · Edit rating"),"0 score must be shown, not treated as missing");
ctx.appendMessage("assistant", "Worker response", null,null,{id:19});
assert(ctx.captured.pop().innerHTML.includes("☆ Rate reply"));
ctx.appendMessage("assistant", "[GitHub collaborator — GitHub bridge, untrusted external text]\nHello",null,null,
  {id:20,inference_compute:"application"});
assert(!ctx.captured.pop().innerHTML.includes("message-rating-trigger"),"GitHub mirrors are not direct XemAi replies");
ctx.appendMessage("assistant", "Synthetic greeting");
assert(!ctx.captured.pop().innerHTML.includes("message-rating-trigger"),"Do not score unsaved placeholder");
const first = ctx.messageSignature([{id:19,role:"assistant",rating_score:null}]);
const second = ctx.messageSignature([{id:19,role:"assistant",rating_score:0,rating_aspect:"understanding"}]);
assert.notStrictEqual(first,second,"Remote rating changes must invalidate message render");
assert(code.includes("function showMessageRating(messageId"));
assert(code.includes("aspect: aspectSelect.value"));
assert(code.includes("message_id: messageId"));
assert(css.includes(".message-rating-trigger"));
console.log("Per-message rating rendering and synchronization checks passed.");

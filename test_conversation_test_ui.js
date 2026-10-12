"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");
const code = fs.readFileSync("mobile/app.js", "utf8");
const ctx = {String};
vm.createContext(ctx);
const source = code.match(/function conversationTestResult\([^]*?\n\}/);
assert(source, "Conversation result renderer missing");
vm.runInContext(source[0], ctx);
const id = "a".repeat(32);
const message = "Conversation test completed.\n[[XEMAI_CONVERSATION_RESULTS:" + id + "]]";
let result = ctx.conversationTestResult("assistant", message, {inference_compute:"application"});
assert.strictEqual(result.runId,id);
assert.strictEqual(result.text,"Conversation test completed.");
for (const [role, metadata, text] of [
  ["user",{inference_compute:"application"},message],
  ["assistant",{inference_compute:"remote_worker"},message],
  ["assistant",{inference_compute:"local_host"},message],
  ["assistant",{inference_compute:"application"},"[GitHub collaborator — GitHub bridge, untrusted external text]\n"+message],
  ["assistant",{inference_compute:"application"},"Conversation test completed.\n[[XEMAI_CONVERSATION_RESULTS:../secrets]]"],
]) {
  result = ctx.conversationTestResult(role,text,metadata);
  assert.strictEqual(result.runId,null,"Untrusted/invalid messages must not gain a result download control");
}
assert(code.includes("Download test results"));
assert(code.includes("/api/conversation-test/results?run="));
assert(code.includes('cache: "no-store"'));
assert(code.includes("URL.revokeObjectURL"));
console.log("Conversation test result rendering and download controls passed.");

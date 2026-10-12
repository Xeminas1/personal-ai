# Conversation tests in XemAi

Type **conversation test** in the normal XemAi chat on the always-on host.
You can do this from the laptop, desktop app, or phone connected to that host.
The test uses the existing paired PC when available, otherwise the host model.

- **conversation test status** shows progress and the model actually selected.
- **conversation test stop** stops after the current model request.
- **conversation test results** shows the latest outcome and its download button.
- **conversation test laptop** explicitly tests the existing host model.
- **conversation test pc** requires the already-enabled paired PC route; it does not silently substitute the laptop.

One run evaluates six fictional multi-turn situations. It compares a minimal
prompt, the installed app prompt, that prompt with conversation guidance, and
guidance plus relevant owner-approved lessons. If no approved lesson is
retrieved, that condition is skipped rather than reported as learning.

The request returns immediately. A completion message is saved in the same
chat. Click **Download test results** to obtain the answers, blinded grading
CSV, condition key and provenance. Grade the CSV before revealing the key.

The selected inference client is fixed throughout a run. A failed PC request
is not repeated on the laptop. Reported model identity, route, source hashes
and available model digests are recorded; incompatible or incomplete answers
are unscorable. There is no automatic quality score or improvement claim.

These exposed pilot cases isolate prompt/lesson effects. The harness bypasses
the complete UI, tools, research, retries and specialist-review pipeline.
Fresh independent wording, repeated scoring and tests after a new session or
restart are still needed to assess durable learning and ordinary-app quality.

Tests use a fictional profile and no existing chat history or personal-memory
database. Approved lesson text is not copied into reports; its presence/hash
is recorded, though generated answers can reflect it. Results stay local
unless the owner deliberately downloads and shares them.

Only new test records are written under **data/conversation_tests**. The test
does not approve lessons, replace chats or memories, alter pairing/configuration,
install models, run tools, create agents, or train weights. The normal chat
contains only its requested start/status/completion messages. Automatic host
update installation waits until an active test completes or is stopped.

A server restart interrupts an active test; it does not claim that a lost
background job is still running or resume inference without a new request.
Starting a new run preserves earlier test records.

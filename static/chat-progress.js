/* Reply timing and the optional progress stream. No artificial API delay. */
(function (root) {
  "use strict";
  const MIN_REPLY_MS = 1000;
  const SHOW_PROGRESS_MS = 4000;

  function createIdleDeadline(onTimeout, timeoutMs, clock = {}) {
    const schedule = clock.setTimeout || setTimeout;
    const cancel = clock.clearTimeout || clearTimeout;
    let timer, stopped = false;
    function touch() {
      if (stopped) return;
      cancel(timer);
      timer = schedule(() => { stopped = true; onTimeout(); }, timeoutMs);
    }
    touch();
    return { touch, stop() { stopped = true; cancel(timer); } };
  }

  function replyError(message, payload) {
    const error = new Error(message);
    if (payload && typeof payload.reply === "string") error.userMessage = payload.reply;
    return error;
  }

  function createWaitState(onStatus, clock = {}) {
    const now = clock.now || (() => performance.now());
    const schedule = clock.setTimeout || setTimeout;
    const cancel = clock.clearTimeout || clearTimeout;
    const started = now();
    let latest = "preparing";
    let slow = false;
    let settled = false;
    const timer = schedule(() => {
      if (settled) return;
      slow = true;
      onStatus(latest);
    }, SHOW_PROGRESS_MS);

    return {
      update(stage) {
        if (settled || !["understanding", "checking", "writing"].includes(stage)) return;
        latest = stage;
        if (slow) onStatus(latest);
      },
      async finish() {
        settled = true;
        cancel(timer);
        const remaining = MIN_REPLY_MS - (now() - started);
        if (remaining > 0) await new Promise(resolve => schedule(resolve, remaining));
      },
    };
  }

  async function readReply(response, onStatus) {
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw replyError("HTTP " + response.status, payload);
    }
    if (!(response.headers.get("Content-Type") || "").includes("text/event-stream")) {
      return response.json(); // Older servers and non-streaming clients stay compatible.
    }
    if (!response.body) throw new Error("Missing response stream");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
        let boundary;
        while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
          const frame = buffer.slice(0, boundary.index);
          buffer = buffer.slice(boundary.index + boundary[0].length);
          let event = "message";
          const data = [];
          for (const line of frame.split(/\r?\n/)) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
          }
          if (!data.length) continue;
          const payload = JSON.parse(data.join("\n"));
          if (event === "status") onStatus(payload.stage);
          else if (event === "reply") return payload;
          else if (event === "error") throw replyError("Reply could not be completed", payload);
        }
        if (done) throw new Error("Response ended before a reply arrived");
      }
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  root.ChatProgress = { createWaitState, createIdleDeadline, readReply };
  if (typeof module !== "undefined") module.exports = root.ChatProgress;
})(globalThis);

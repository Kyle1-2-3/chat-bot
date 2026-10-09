const test = require('node:test');
const assert = require('node:assert/strict');
const { createWaitState, createIdleDeadline, readReply } = require('../static/chat-progress.js');

function clock() {
  let ms = 0, id = 0;
  const timers = new Map();
  return {
    now: () => ms,
    setTimeout(fn, delay) { timers.set(++id, { at: ms + delay, fn }); return id; },
    clearTimeout(id) { timers.delete(id); },
    advance(delta) {
      const until = ms + delta;
      while (true) {
        const next = [...timers].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        ms = next[1].at; timers.delete(next[0]); next[1].fn();
      }
      ms = until;
    },
    pending: () => timers.size,
  };
}

test('a 100 ms answer waits until 1 second, without showing a late status', async () => {
  const time = clock(), statuses = [];
  const state = createWaitState(s => statuses.push(s), time);
  time.advance(100);
  let displayed = false;
  const done = state.finish().then(() => { displayed = true; });
  time.advance(899); await Promise.resolve();
  assert.equal(displayed, false);
  time.advance(1); await done;
  assert.equal(time.now(), 1000);
  assert.equal(displayed, true);
  time.advance(5000);
  assert.deepEqual(statuses, []);
  assert.equal(time.pending(), 0);
});

test('a 2 second answer gets no additional delay and no status label', async () => {
  const time = clock(), statuses = [];
  const state = createWaitState(s => statuses.push(s), time);
  time.advance(2000); await state.finish();
  assert.equal(time.now(), 2000);
  time.advance(3000);
  assert.deepEqual(statuses, []);
  assert.equal(time.pending(), 0);
});

test('4 seconds reveals the latest actual stage, then follows server updates', async () => {
  const time = clock(), statuses = [];
  const state = createWaitState(s => statuses.push(s), time);
  state.update('understanding');
  time.advance(1500); state.update('checking');
  time.advance(2499);
  assert.deepEqual(statuses, []);
  time.advance(1);
  assert.deepEqual(statuses, ['checking']);
  state.update('writing');
  assert.deepEqual(statuses, ['checking', 'writing']);
  await state.finish();
  state.update('checking'); time.advance(10000);
  assert.deepEqual(statuses, ['checking', 'writing']);
  assert.equal(time.pending(), 0);
});

test('no stage received uses an honest generic status; a retry has its own clock', async () => {
  const time = clock(), statuses = [];
  const first = createWaitState(s => statuses.push(s), time);
  first.update('<unknown stage>');
  time.advance(4000);
  assert.deepEqual(statuses, ['preparing']);
  await first.finish();
  const second = createWaitState(s => statuses.push(s), time);
  time.advance(3999);
  assert.deepEqual(statuses, ['preparing']);
  time.advance(1);
  assert.deepEqual(statuses, ['preparing', 'preparing']);
  await second.finish();
});

function stream(text, bytesPerChunk = 1) {
  const bytes = new TextEncoder().encode(text);
  let offset = 0;
  return new Response(new ReadableStream({ pull(controller) {
    if (offset >= bytes.length) { controller.close(); return; }
    controller.enqueue(bytes.slice(offset, offset += bytesPerChunk));
  } }), { headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } });
}

test('stream decoder handles split UTF-8, CRLF and event boundaries', async () => {
  const statuses = [];
  const text = 'event: status\r\ndata: {"stage":"writing"}\r\n\r\nevent: reply\ndata: {"reply":"오늘 점심입니다.\\nEnjoy!"}\n\n';
  const result = await readReply(stream(text), s => statuses.push(s));
  assert.deepEqual(statuses, ['writing']);
  assert.equal(result.reply, '오늘 점심입니다.\nEnjoy!');
});

test('legacy JSON replies still work', async () => {
  assert.deepEqual(await readReply(Response.json({ reply: 'Hello' }), () => {}), { reply: 'Hello' });
});

test('an error, truncated stream or HTTP failure reaches the retry flow', async () => {
  await assert.rejects(readReply(stream('event: error\ndata: {"reply":"failed"}\n\n'), () => {}));
  await assert.rejects(readReply(stream('event: status\ndata: {"stage":"writing"}\n\n'), () => {}), /before a reply/);
  await assert.rejects(readReply(new Response('limited', { status: 429 }), () => {}), /HTTP 429/);
});

test('a body read failure after headers is not mistaken for a completed answer', async () => {
  const response = new Response(new ReadableStream({ start(controller) {
    controller.error(new DOMException('Timed out', 'AbortError'));
  } }), { headers: { 'Content-Type': 'text/event-stream' } });
  await assert.rejects(readReply(response, () => {}), { name: 'AbortError' });
});

test('two slow model stages can finish after 18 seconds while a stalled stage times out', () => {
  const time = clock();
  let aborted = false;
  const deadline = createIdleDeadline(() => { aborted = true; }, 18000, time);
  time.advance(14000); deadline.touch();
  time.advance(14000);
  assert.equal(aborted, false);
  time.advance(3999);
  assert.equal(aborted, false);
  time.advance(1);
  assert.equal(aborted, true);
  assert.equal(time.pending(), 0);
});

test('a finished request cancels its idle deadline and cannot restart it', () => {
  const time = clock();
  let aborted = false;
  const deadline = createIdleDeadline(() => { aborted = true; }, 18000, time);
  time.advance(100); deadline.stop(); deadline.touch();
  time.advance(40000);
  assert.equal(aborted, false);
  assert.equal(time.pending(), 0);
});

test('server usage-limit messages survive both HTTP and streaming error paths', async () => {
  const message = "We've reached today's AI usage limit.";
  const matches = err => err.userMessage === message;
  await assert.rejects(readReply(Response.json({ reply: message }, { status: 429 }), () => {}), matches);
  await assert.rejects(readReply(stream('event: error\ndata: ' + JSON.stringify({ reply: message }) + '\n\n'), () => {}), matches);
});

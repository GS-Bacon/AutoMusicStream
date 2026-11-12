import { createVisualizer } from "./visualizer.js";

const elements = Object.fromEntries(
  ["visualizer", "status", "title", "details", "mode", "progress", "timer", "play",
    "composer-status", "playhead", "patterns"]
    .map((id) => [id, document.getElementById(id)])
);
const isObs = new URLSearchParams(location.search).get("obs") === "1";
const audio = new AudioContext();
const analyser = audio.createAnalyser();
analyser.fftSize = 2048;
analyser.smoothingTimeConstant = 0.60;
analyser.minDecibels = -88;
analyser.maxDecibels = -16;
const output = audio.createGain();
output.gain.value = 0.84;
output.connect(analyser).connect(audio.destination);
const visualizer = createVisualizer(elements.visualizer, analyser);
let current;
let scheduled;
let ready;
let fetching = false;
let retryAt = 0;
let shownScore;
let patternTokens = {};
let nextCue = 0;
let editedUntil = 0;
const activeTokens = new Map();
const composerLabels = {
  waiting: "CODEX · PLAYING",
  composing: "CODEX · REVISING SCORE",
  rendering: "CODEX · RENDERING AUDIO",
  ready: "CODEX · REVISION QUEUED",
  retry: "CODEX · AUTO PLAY / WILL RETRY",
};

function setStatus(text, playing) {
  elements.status.textContent = text;
  document.body.dataset.playing = String(playing);
}

function formatSlot(slot) {
  if (slot === null) return "None";
  return Array.isArray(slot) ? `(${slot.join(", ")})` : JSON.stringify(slot);
}

function showPatterns(score) {
  if (score === shownScore) return;
  const previous = shownScore;
  shownScore = score;
  patternTokens = {};
  elements.patterns.replaceChildren();
  for (const field of ["lead", "chords", "melody", "bridge", "counter", "bass", "kick", "hat"]) {
    if (!(field in score)) continue;
    const line = document.createElement("span");
    line.className = "pattern-line";
    const name = document.createElement("span");
    name.className = "pattern-name";
    name.textContent = field;
    const value = score[field];
    const old = previous?.[field];
    const array = Array.isArray(value);
    if (previous && array && old?.length !== value.length) name.dataset.edited = "";
    line.append(name, array ? (["kick", "hat"].includes(field) ? " = [" : " = P[") : " = ");
    const slots = array ? value : [value];
    patternTokens[field] = slots.map((slot, i) => {
      if (i) line.append(["melody", "bridge", "counter"].includes(field) && i === 8 ? ",\n           " : ", ");
      const token = document.createElement("span");
      token.className = "pattern-value";
      token.textContent = formatSlot(slot);
      if (slot === null) token.dataset.rest = "";
      if (previous && token.textContent !== formatSlot(array ? old?.[i] : old)) token.dataset.edited = "";
      line.append(token);
      return token;
    });
    if (array) line.append("]");
    elements.patterns.append(line);
  }
  editedUntil = audio.currentTime + 3;
}

function paintPatterns(elapsed, meta) {
  let bar = meta.barInfo.length - 1;
  while (bar > 0 && meta.barInfo[bar].start > elapsed) bar--;
  const { start, bpm, genre, section } = meta.barInfo[bar];
  const step = Math.floor((elapsed - start - 0.03) * bpm / 15);
  const position = [section, `BAR ${bar + 1}/${meta.bars}`,
    `STEP ${Math.min(15, Math.max(0, step)) + 1}/16`].filter(Boolean).join(" · ");
  if (elements.playhead.textContent !== position) elements.playhead.textContent = position;
  const details = `${Math.round(bpm)} BPM  /  ${meta.key}  /  ${genre}`;
  if (elements.details.textContent !== details) elements.details.textContent = details;
  while (nextCue < meta.cues.length && meta.cues[nextCue][0] <= elapsed) {
    const [time, field, slot, length] = meta.cues[nextCue++];
    if (time + length > elapsed) {
      const token = patternTokens[field]?.[slot];
      if (!token) continue;
      token.dataset.active = "";
      activeTokens.set(token, time + length);
    }
  }
  for (const [token, until] of activeTokens) {
    if (elapsed >= until) {
      delete token.dataset.active;
      activeTokens.delete(token);
    }
  }
  if (editedUntil && audio.currentTime >= editedUntil) {
    for (const token of elements.patterns.querySelectorAll("[data-edited]")) delete token.dataset.edited;
    editedUntil = 0;
  }
}

function show(track) {
  const { id, title, mode } = track.meta;
  elements.title.textContent = title;
  elements.mode.textContent = `${mode} · FOXDOT`;
  document.body.dataset.track = String(id);
  visualizer.setTrack(id);
  for (const token of activeTokens.keys()) delete token.dataset.active;
  activeTokens.clear();
  nextCue = 0;
  showPatterns(track.meta.score);
  setStatus("ON AIR", true);
}

async function fetchNext(after) {
  fetching = true;
  try {
    const signal = AbortSignal.timeout(5000);
    const playing = current && audio.currentTime >= current.start ? current.meta.id : 0;
    const response = await fetch(`/api/next?after=${after}&playing=${playing}`, { signal });
    if (!response.ok) throw new Error("Track queue unavailable");
    const phase = composerLabels[response.headers.get("X-FoxDot-Codex")] ?? "FOXDOT PATTERNS";
    if (elements["composer-status"].textContent !== phase) elements["composer-status"].textContent = phase;
    const meta = await response.json();
    if (!meta) return;
    const file = await fetch(meta.url, { signal: AbortSignal.timeout(15000) });
    if (!file.ok) throw new Error("Audio unavailable");
    ready = { meta, buffer: await audio.decodeAudioData(await file.arrayBuffer()) };
  } catch (error) {
    if (!current) {
      elements.details.textContent = "Waiting for the audio generator";
      console.warn(error);
    }
  } finally {
    fetching = false;
    retryAt = performance.now() + 850;
  }
}

function startTrack(track, start, reprise = false) {
  const source = audio.createBufferSource();
  const envelope = audio.createGain();
  const offset = reprise ? track.meta.barInfo[track.meta.repriseBar].start : 0;
  const end = start + track.buffer.duration - offset;
  const transition = start + track.meta.musicSeconds - offset;
  source.buffer = track.buffer;
  source.connect(envelope).connect(output);
  envelope.gain.setValueAtTime(0, start);
  envelope.gain.linearRampToValueAtTime(1, start + 0.035);
  envelope.gain.setValueAtTime(1, transition);
  envelope.gain.linearRampToValueAtTime(0, end);
  source.start(start, offset);
  source.addEventListener("ended", () => {
    source.disconnect();
    envelope.disconnect();
  }, { once: true });
  return { ...track, start, offset, transition };
}

function pump() {
  if (audio.state !== "running") return;
  const now = audio.currentTime;
  if (scheduled && now >= scheduled.start) {
    current = scheduled;
    scheduled = undefined;
    show(current);
  }
  if (!current && ready) {
    current = startTrack(ready, now + 0.06);
    ready = undefined;
    show(current);
  }
  if (current && !scheduled) {
    const { transition } = current;
    const upcoming = transition - now;
    if ((ready && upcoming < 2.25) || upcoming < 0.65) {
      scheduled = startTrack(ready ?? current, Math.max(now + 0.04, transition), !ready);
      ready = undefined;
    }
  }
  if (!ready && !scheduled && !fetching && (!current || now >= current.start) && performance.now() >= retryAt) {
    void fetchNext(current?.meta.id ?? 0);
  }
}

async function play() {
  await audio.resume();
  elements.play.hidden = true;
  pump();
}

elements.play.addEventListener("click", () => void play().catch(console.error));
elements.play.hidden = isObs;
if (isObs) {
  void play().catch(console.error);
  setTimeout(() => {
    if (audio.state !== "running") {
      elements.play.textContent = "Start audio";
      elements.play.hidden = false;
      setStatus("AUDIO PAUSED", false);
    }
  }, 1500);
}
setInterval(pump, 140);

function paint(time) {
  visualizer.paint(time);

  if (current) {
    const elapsed = Math.max(0, audio.currentTime - current.start);
    paintPatterns(elapsed + current.offset, current.meta);
    const length = current.meta.musicSeconds - current.offset;
    elements.progress.style.transform = `scaleX(${Math.min(1, elapsed / length)})`;
    const seconds = Math.floor(elapsed);
    const pad = (value) => String(value).padStart(2, "0");
    const timer = `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}`;
    if (elements.timer.textContent !== timer) elements.timer.textContent = timer;
  }
  requestAnimationFrame(paint);
}

requestAnimationFrame(paint);

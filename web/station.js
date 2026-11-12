import { createVisualizer } from "./visualizer.js";

const elements = Object.fromEntries(
  ["visualizer", "status", "title", "details", "mode", "progress", "timer", "play"]
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
const fade = 1.35;
let current;
let scheduled;
let ready;
let fetching = false;
let retryAt = 0;

function setStatus(text, playing) {
  elements.status.textContent = text;
  document.body.dataset.playing = String(playing);
}

function show(track) {
  const { id, title, bpm, key, mode } = track.meta;
  elements.title.textContent = title;
  elements.details.textContent = `${bpm} BPM  /  ${key}`;
  elements.mode.textContent = `${mode} · FOXDOT`;
  document.body.dataset.track = String(id);
  visualizer.setTrack(id);
  setStatus("ON AIR", true);
}

async function fetchNext(after) {
  fetching = true;
  try {
    const signal = AbortSignal.timeout(5000);
    const response = await fetch(`/api/next?after=${after}`, { signal });
    if (!response.ok) throw new Error("Track queue unavailable");
    const meta = await response.json();
    if (!meta) return;
    const file = await fetch(meta.url, { signal });
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

function startTrack(track, start) {
  const source = audio.createBufferSource();
  const envelope = audio.createGain();
  const end = start + track.buffer.duration;
  source.buffer = track.buffer;
  source.connect(envelope).connect(output);
  envelope.gain.setValueAtTime(0, start);
  envelope.gain.linearRampToValueAtTime(1, start + fade);
  envelope.gain.setValueAtTime(1, end - fade);
  envelope.gain.linearRampToValueAtTime(0, end);
  source.start(start);
  source.addEventListener("ended", () => {
    source.disconnect();
    envelope.disconnect();
  }, { once: true });
  return { ...track, start, end };
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
    const transition = current.end - fade;
    const upcoming = transition - now;
    if ((ready && upcoming < 2.25) || upcoming < 0.65) {
      scheduled = startTrack(ready ?? current, Math.max(now + 0.04, transition));
      ready = undefined;
    }
  }
  if (!ready && !fetching && performance.now() >= retryAt) {
    void fetchNext(scheduled?.meta.id ?? current?.meta.id ?? 0);
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
    elements.progress.style.transform = `scaleX(${Math.min(1, elapsed / current.buffer.duration)})`;
    const seconds = Math.floor(elapsed);
    const pad = (value) => String(value).padStart(2, "0");
    const timer = `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}`;
    if (elements.timer.textContent !== timer) elements.timer.textContent = timer;
  }
  requestAnimationFrame(paint);
}

requestAnimationFrame(paint);

"""Generate FoxDot patterns, render them in SuperCollider, and serve an OBS source."""

import argparse
from array import array
import io
import json
import logging
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
from threading import Condition, Event, Thread
from time import monotonic
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from FoxDot import P, Scale


ROOT = Path(__file__).resolve().parent
RATE = 48000
BARS = 8
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SCALES = ("minor", "dorian", "major", "mixolydian")
LEADS = ("fm", "pulse", "triangle")


def sequence_schema(length, values):
    return {"type": "array", "minItems": length, "maxItems": length, "items": values}


def integer_schema(low, high):
    return {"type": "integer", "minimum": low, "maximum": high}


def note_schema(high):
    return {"anyOf": [integer_schema(0, high), {"type": "null"}]}


def rhythm_schema(minimum):
    return {
        "type": "array", "minItems": minimum, "maxItems": 8,
        "items": integer_schema(0, 15),
    }


FIELDS = {
    "title": {"type": "string", "minLength": 1, "maxLength": 40},
    "bpm": integer_schema(78, 114),
    "root": {"type": "string", "enum": NOTES},
    "scale": {"type": "string", "enum": SCALES},
    "lead": {"type": "string", "enum": LEADS},
    "chords": sequence_schema(4, integer_schema(0, 6)),
    "melody": sequence_schema(16, note_schema(12)),
    "bass": sequence_schema(8, note_schema(7)),
    "kick": rhythm_schema(1),
    "hat": rhythm_schema(2),
}
SCORE_SCHEMA = {
    "type": "object", "properties": FIELDS, "required": list(FIELDS),
    "additionalProperties": False,
}


def matches(value, schema):
    if "anyOf" in schema:
        return any(matches(value, item) for item in schema["anyOf"])
    if "enum" in schema:
        return value in schema["enum"]
    if schema["type"] == "integer":
        return type(value) is int and schema["minimum"] <= value <= schema["maximum"]
    if schema["type"] == "null":
        return value is None
    if schema["type"] == "string":
        return isinstance(value, str) and schema["minLength"] <= len(value) <= schema["maxLength"]
    return (
        isinstance(value, list)
        and schema["minItems"] <= len(value) <= schema["maxItems"]
        and all(matches(item, schema["items"]) for item in value)
    )


def validate(score):
    if not isinstance(score, dict) or score.keys() != FIELDS.keys():
        raise ValueError("The score has missing or unexpected fields")
    for field, schema in FIELDS.items():
        if not matches(score[field], schema):
            raise ValueError(f"Invalid score field: {field}")
    if not score["title"].strip() or not any(note is not None for note in score["melody"]):
        raise ValueError("The score needs a title and a melody")
    return score


PATTERN_GUIDE = (
    "chords are zero-based scale degrees, one for every two bars. "
    "melody has 16 eighth-note slots across two bars, relative to the chord root. "
    "bass has 8 eighth-note slots per bar, relative to the chord root. "
    "Null is a rest. kick and hat are distinct positions on a single 16-step bar. "
)


def compose_with_ollama(model, url, previous):
    instruction = (
        "Compose a mellow electronic track in the supplied JSON schema. " + PATTERN_GUIDE +
        "Aim for a clear motif, a sparse syncopated rhythm and playable harmony. "
        "Use a new short title. Give only the JSON object. "
        f"Previous track: {json.dumps(previous, ensure_ascii=False)}"
    )
    request = Request(url.rstrip("/") + "/api/chat", method="POST",
                      headers={"Content-Type": "application/json"},
                      data=json.dumps({
                          "model": model, "stream": False, "format": SCORE_SCHEMA,
                          "messages": [{"role": "user", "content": instruction}],
                          "options": {"temperature": 0.8, "num_predict": 500},
                      }).encode())
    with urlopen(request, timeout=18) as response:
        content = json.load(response)["message"]["content"]
    return validate(json.loads(content))


class CodexComposer:
    def __init__(self, command, work, interval):
        self.interval = interval
        self.work = work
        self.work.mkdir()
        schema = work / "score-schema.json"
        schema.write_text(json.dumps(SCORE_SCHEMA), encoding="utf-8")
        self.command = [
            command, "-a", "never", "exec", "--sandbox", "read-only",
            "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
            "--color", "never", "--output-schema", str(schema), "-",
        ]

    def revise(self, previous, stopped):
        prompt = (
            "You are live-coding an eight-bar mellow electronic loop. "
            "Use the supplied score as data. Return one complete revised score as JSON. "
            "Keep the tempo, root and scale. Change one or two parts audibly while "
            "preserving the groove. Keep unedited parts as-is. Use no tools. "
            + PATTERN_GUIDE
            + f"Score constraints: {json.dumps(SCORE_SCHEMA, ensure_ascii=False)}\n"
            + f"Currently playing: {json.dumps(previous, ensure_ascii=False)}\n"
        )
        with subprocess.Popen(
            self.command, cwd=self.work, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ) as process:
            deadline = monotonic() + 75
            pending = prompt
            while True:
                try:
                    output, diagnostics = process.communicate(pending, timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    pending = None
                    if stopped.is_set() or monotonic() >= deadline:
                        process.kill()
                        process.communicate()
                        if stopped.is_set():
                            return None
                        raise TimeoutError("Codex did not return a score within 75 seconds")
            if process.returncode:
                tail = diagnostics.strip().splitlines()
                detail = tail[-1][:300] if tail else "no CLI diagnostics"
                raise RuntimeError(f"Codex exited with {process.returncode}: {detail}")

        score = validate(json.loads(output))
        if any(score[name] != previous[name] for name in ("bpm", "root", "scale")):
            raise ValueError("Codex changed the tempo or key")
        if all(score[name] == previous[name] for name in ("lead", "chords", "melody", "bass", "kick", "hat")):
            raise ValueError("Codex returned the same patterns")
        return score


def find_codex():
    command = shutil.which("codex")
    if command or os.name != "nt":
        return command
    try:
        package = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-AppxPackage -Name OpenAI.Codex).InstallLocation"],
            capture_output=True, text=True, check=True, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if package:
        return shutil.which("codex.exe", path=str(Path(package) / "app" / "resources"))
    return None


def vary(seed, index):
    rng = random.Random(index)
    motif = list(seed["melody"])
    step = rng.choice([i for i, note in enumerate(motif) if note is not None])
    motif[step] = rng.choice([2, 4, 6, 7, 9])
    return {
        **seed, "title": f"{seed['title']} / {index:02d}",
        "bpm": seed["bpm"] + rng.randint(-4, 4),
        "chords": [seed["chords"][0], seed["chords"][1], rng.choice([2, 3, 5, 6]), seed["chords"][3]],
        "melody": motif, "hat": sorted(set(seed["hat"]) | {rng.choice([3, 9, 15])}),
    }


def events_for(score, index):
    beat = 60 / score["bpm"]
    scale = getattr(Scale, score["scale"])
    root = NOTES.index(score["root"])
    rng = random.Random(index)
    melody, bass, chords = (P[score[name]] for name in ("melody", "bass", "chords"))
    events = []
    cues = []

    def add(time, synth, cue=None, **params):
        onset = time + 0.03
        events.append((onset, synth, params))
        if cue:
            field, slot, duration = cue
            cues.append((round(onset, 4), field, slot, round(duration, 4)))

    for bar in range(BARS):
        start = bar * beat * 4
        degree = chords[bar // 2]
        if bar % 2 == 0:
            for interval, pan in zip([0, 2, 4, 8], [-0.68, 0.49, -0.26, 0.64]):
                freq = scale.get_freq(degree + interval, octave=4, root=root)
                cue = ("chords", bar // 2, beat * 7) if interval == 0 else None
                add(start, "radioPad", cue, freq=freq, amp=0.10, pan=pan, hold=beat * 7)

        for step in range(16):
            time = start + (step + 0.16 * (step % 2)) * beat / 4
            if step in score["kick"] and (bar > 0 or step % 4 == 0):
                add(time, "radioKick", ("kick", score["kick"].index(step), 0.15),
                    amp=0.36 if step == 0 else 0.25)
            if step in (4, 12) and bar > 0:
                add(time, "radioSnare", amp=0.22 if step == 4 else 0.18)
            if step in score["hat"]:
                add(time, "radioHat", ("hat", score["hat"].index(step), 0.11),
                    amp=rng.uniform(0.058, 0.12), pan=rng.uniform(-0.52, 0.52),
                    hold=0.15 if step % 4 == 2 else 0.065)
            if step % 2 == 1:
                continue
            bass_note = bass[step // 2]
            if isinstance(bass_note, int):
                freq = scale.get_freq(degree + bass_note, octave=2, root=root)
                add(time, "radioBass", ("bass", step // 2, beat * 0.39),
                    freq=freq, amp=0.24, hold=beat * 0.39)
            melody_slot = (bar % 2) * 8 + step // 2
            lead_note = melody[melody_slot]
            if isinstance(lead_note, int) and (bar not in (0, 6) or step % 4 == 0):
                freq = scale.get_freq(degree + lead_note, octave=5, root=root)
                shape = LEADS.index(score["lead"])
                cue = ("melody", melody_slot, beat * 0.38)
                add(time + 0.015, "radioLead", cue, freq=freq, amp=0.13, pan=rng.uniform(-0.38, 0.38),
                    hold=beat * 1.1, shape=shape)
                if bar in (3, 5, 7) and step < 12:
                    add(time + beat * 0.75, "radioLead", cue, freq=freq, amp=0.036, pan=0.54,
                        hold=beat * 0.66, shape=shape)
    return sorted(events, key=lambda event: event[0]), BARS * 4 * beat + 0.4, sorted(cues)


def osc_string(value):
    encoded = value.encode() + b"\0"
    return encoded + b"\0" * (-len(encoded) % 4)


def osc_message(address, *args):
    formats = {str: "s", int: "i", float: "f", bytes: "b"}
    header = osc_string(address) + osc_string("," + "".join(formats[type(arg)] for arg in args))
    parts = [header]
    for arg in args:
        if isinstance(arg, str):
            parts.append(osc_string(arg))
        elif isinstance(arg, bytes):
            parts.append(struct.pack(">I", len(arg)) + arg + b"\0" * (-len(arg) % 4))
        else:
            parts.append(struct.pack(">i" if isinstance(arg, int) else ">f", arg))
    return b"".join(parts)


def write_bundle(handle, time, *messages):
    packet = b"#bundle\0" + struct.pack(">Q", round(time * 2**32))
    packet += b"".join(struct.pack(">I", len(message)) + message for message in messages)
    handle.write(struct.pack(">I", len(packet)) + packet)


def find_supercollider(directory):
    candidates = [directory] if directory else [None]
    if not directory and os.name == "nt":
        candidates.extend(sorted(Path(os.environ.get("ProgramFiles", "C:/Program Files")).glob("SuperCollider*"),
                                 reverse=True))
    for candidate in candidates:
        suffix = ".exe" if os.name == "nt" else ""
        paths = [shutil.which(str(candidate / (name + suffix))) if candidate else shutil.which(name)
                 for name in ("sclang", "scsynth")]
        if all(paths):
            return paths
    raise ValueError("SuperCollider is missing. Install it or pass --supercollider-dir.")


def run_sc(command, timeout, allowed_exit_codes=(0,)):
    env = os.environ.copy()
    if os.name != "nt":
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace",
                                timeout=timeout, env=env, cwd=Path(command[0]).parent)
    except subprocess.TimeoutExpired as error:
        parts = [part.decode(errors="replace") if isinstance(part, bytes) else part
                 for part in (error.stdout, error.stderr) if part]
        log = "\n".join(parts)
        raise RuntimeError(f"SuperCollider timed out.\n{log[-3000:]}") from error
    if result.returncode not in allowed_exit_codes:
        lines = (result.stderr + "\n" + result.stdout).splitlines()
        details = "\n".join(dict.fromkeys(line for line in lines if not line.startswith("nextOSCPacket")))
        raise RuntimeError(f"{Path(command[0]).name} exited with {result.returncode}.\n{details[:3000]}")
    return result.stdout


class Renderer:
    def __init__(self, directory, work):
        sclang, self.scsynth = find_supercollider(directory)
        self.work = work
        script = work / "synths.scd"
        shutil.copyfile(ROOT / script.name, script)
        run_sc([sclang, "-D", "-u", "0", str(script), str(work)], timeout=25)
        self.definitions = [path.read_bytes() for path in sorted(work.glob("*.scsyndef"))]
        if len(self.definitions) != 7:
            raise RuntimeError("SuperCollider failed to compile all instruments.")

    def render(self, score, index):
        events, duration, cues = events_for(score, index)
        osc_path = self.work / "score.osc"
        wav_path = self.work / "track.wav"
        wav_path.unlink(missing_ok=True)
        with osc_path.open("wb") as output:
            write_bundle(output, 0, *(osc_message("/d_recv", data) for data in self.definitions),
                         osc_message("/g_new", 1, 0, 0),
                         osc_message("/s_new", "radioMix", 900, 1, 1))
            for node, (time, synth, params) in enumerate(events, start=1000):
                args = [value for item in params.items() for value in item]
                write_bundle(output, time, osc_message("/s_new", synth, node, 0, 1, *args))
            write_bundle(output, duration, osc_message("/c_set", 0, 0))
        # Windows scsynth 3.14.0 can fault after writing the WAV. Validate the result below.
        exit_codes = (0, 0xC0000005) if os.name == "nt" else (0,)
        log = run_sc([self.scsynth, "-o", "2", "-i", "0", "-m", "32768", "-N",
                      str(osc_path), "_", str(wav_path), str(RATE), "WAV", "int16"],
                     timeout=20, allowed_exit_codes=exit_codes)
        failures = [line for line in log.splitlines() if "FAILURE" in line or "not found" in line]
        if failures:
            raise RuntimeError("\n".join(dict.fromkeys(failures))[:2000])
        data = wav_path.read_bytes()
        with wave.open(io.BytesIO(data)) as wav:
            if wav.getnchannels() != 2 or wav.getframerate() != RATE or wav.getsampwidth() != 2:
                raise RuntimeError("Unexpected SuperCollider audio format.")
            samples = array("h", wav.readframes(wav.getnframes()))
        if abs(len(samples) / (RATE * 2) - duration) > 0.025:
            raise RuntimeError(f"Incomplete SuperCollider render ({len(samples)} samples).")
        if not samples or max(samples) < 400:
            raise RuntimeError("SuperCollider returned silent audio.")
        return data, cues


class Station:
    def __init__(self, renderer, seeds, model, url, codex=None):
        self.renderer, self.seeds, self.model, self.url = renderer, seeds, model, url
        self.codex = codex
        self.codex_status = "waiting" if codex else ""
        self.condition = Condition()
        self.tracks = {}
        self.target = 2
        self.stopped = Event()
        self.playing = 0
        self.last_played = 0
        self.worker = Thread(target=self.generate, name="composition", daemon=True)
        self.worker.start()

    def close(self):
        with self.condition:
            self.stopped.set()
            self.condition.notify_all()
        self.worker.join()

    def can_generate(self, index, next_attempt):
        if not self.codex:
            return index <= self.target
        now = monotonic()
        return index == 1 or (self.playing == index - 1 and now - self.last_played < 5 and now >= next_attempt)

    def generate(self):
        index = 1
        previous = self.seeds[0]
        next_attempt = 0
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped.is_set() or self.can_generate(index, next_attempt))
                if self.stopped.is_set():
                    return
            seed = self.seeds[(index - 1) % len(self.seeds)]
            score = seed if index <= len(self.seeds) else vary(seed, index)
            mode = "Codex score" if index <= len(self.seeds) else "Pattern variation"
            if self.codex and index > 1:
                self.codex_status = "composing"
                next_attempt = monotonic() + self.codex.interval
                logging.info("Codex is revising %s", previous["title"])
                try:
                    score = self.codex.revise(previous, self.stopped)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                    self.codex_status = "retry"
                    next_attempt = max(next_attempt, monotonic() + self.codex.interval)
                    logging.warning("Keeping the current loop: %s", error)
                    continue
                if self.stopped.is_set():
                    return
                self.codex_status = "rendering"
                mode = "Codex live"
            elif self.model and index > 2:
                try:
                    score = compose_with_ollama(self.model, self.url, previous)
                    mode = "Ollama"
                except (OSError, URLError, ValueError, KeyError, TypeError) as error:
                    logging.warning("Ollama unavailable, using a local score: %s", error)
            try:
                data, cues = self.renderer.render(score, index)
            except (OSError, EOFError, wave.Error, RuntimeError, subprocess.SubprocessError) as error:
                logging.error("Render failed for track %s: %s", index, error)
                if self.codex and index > 1:
                    self.codex_status = "retry"
                    next_attempt = max(next_attempt, monotonic() + self.codex.interval)
                with self.condition:
                    self.condition.wait_for(self.stopped.is_set, timeout=3)
                continue
            metadata = {
                "id": index, "title": score["title"], "bpm": score["bpm"],
                "key": f"{score['root']} {score['scale']}", "mode": mode, "url": f"/audio/{index}.wav",
                "score": score, "cues": cues, "bars": BARS,
            }
            if self.codex:
                metadata["loopSeconds"] = BARS * 4 * 60 / score["bpm"]
            with self.condition:
                self.tracks[index] = metadata, data
                while len(self.tracks) > 6:
                    del self.tracks[next(iter(self.tracks))]
                if self.codex and index > 1:
                    self.codex_status = "ready"
            logging.info("Rendered %02d · %s · %s", index, score["title"], mode)
            previous = score
            index += 1

    def next_track(self, after, playing=0):
        with self.condition:
            latest = next(reversed(self.tracks), 0)
            if self.codex:
                if latest and playing == latest:
                    if self.playing != latest:
                        self.codex_status = "waiting"
                    self.playing = latest
                    self.last_played = monotonic()
                    self.condition.notify()
                return self.tracks[latest][0] if latest and after != latest else None
            if after > latest:
                after = 0
            self.target = max(self.target, after + 2)
            self.condition.notify()
            return next((metadata for index, (metadata, _) in self.tracks.items() if index > after), None)

    def audio(self, index):
        with self.condition:
            track = self.tracks.get(index)
            return track[1] if track else None


FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/station.js": ("station.js", "application/javascript; charset=utf-8"),
    "/visualizer.js": ("visualizer.js", "application/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path in FILES:
            name, mime = FILES[url.path]
            self.respond(200, mime, (ROOT / "web" / name).read_bytes())
        elif url.path == "/api/next":
            try:
                query = parse_qs(url.query)
                after = max(0, int(query.get("after", ["0"])[0]))
                playing = max(0, int(query.get("playing", ["0"])[0]))
            except ValueError:
                self.send_error(400)
                return
            station = self.server.station
            track = station.next_track(after, playing)
            headers = {"X-FoxDot-Codex": station.codex_status} if station.codex_status else None
            self.respond(200, "application/json", json.dumps(track).encode(), headers)
        elif url.path.startswith("/audio/") and url.path.endswith(".wav"):
            name = url.path.removeprefix("/audio/").removesuffix(".wav")
            data = self.server.station.audio(int(name)) if name.isascii() and name.isdigit() and len(name) <= 12 else None
            if data is None:
                self.send_error(404)
                return
            self.respond(200, "audio/wav", data)
        else:
            self.send_error(404)

    def respond(self, status, mime, data, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_request(self, code="-", size="-"):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--supercollider-dir", type=Path)
    parser.add_argument("--ollama-model", default=os.getenv("OLLAMA_MODEL"))
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--codex", action="store_true", help="revise the playing loop with Codex CLI")
    parser.add_argument("--codex-interval", type=int, default=45, metavar="SECONDS",
                        help="minimum seconds between Codex requests (default: 45)")
    parser.add_argument("--render", type=Path, metavar="WAV", help="render the first track and exit")
    args = parser.parse_args()
    if args.codex_interval < 1:
        parser.error("--codex-interval must be at least 1 second")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", force=True)
    seeds = [validate(score) for score in json.loads((ROOT / "scores.json").read_text(encoding="utf-8"))]
    try:
        with tempfile.TemporaryDirectory(prefix="foxdot-radio-") as work:
            renderer = Renderer(args.supercollider_dir, Path(work))
            if args.render:
                data, _ = renderer.render(seeds[0], 1)
                args.render.write_bytes(data)
                return
            codex = None
            if args.codex:
                command = find_codex()
                if not command:
                    raise ValueError("Codex CLI was not found. Install it, add it to PATH and run codex login.")
                codex = CodexComposer(command, Path(work) / "codex", args.codex_interval)
            with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
                server.station = Station(renderer, seeds, args.ollama_model, args.ollama_url, codex)
                logging.info("OBS source: http://127.0.0.1:%s/?obs=1", args.port)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
                finally:
                    server.station.close()
    except (OSError, EOFError, wave.Error, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()

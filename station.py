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
from threading import Condition, Thread
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


def compose_with_ollama(model, url, previous):
    instruction = (
        "Compose a mellow electronic track in the supplied JSON schema. "
        "chords are zero-based scale degrees, one for every two bars. "
        "melody has 16 eighth-note slots across two bars, relative to the chord root. "
        "bass has 8 eighth-note slots per bar, relative to the chord root. "
        "Null is a rest. kick and hat are distinct positions on a single 16-step bar. "
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

    def add(time, synth, **params):
        events.append((time + 0.03, synth, params))

    for bar in range(BARS):
        start = bar * beat * 4
        degree = chords[bar // 2]
        if bar % 2 == 0:
            for interval, pan in zip([0, 2, 4, 8], [-0.68, 0.49, -0.26, 0.64]):
                freq = scale.get_freq(degree + interval, octave=4, root=root)
                add(start, "radioPad", freq=freq, amp=0.10, pan=pan, hold=beat * 7)

        for step in range(16):
            time = start + (step + 0.16 * (step % 2)) * beat / 4
            if step in score["kick"] and (bar > 0 or step % 4 == 0):
                add(time, "radioKick", amp=0.36 if step == 0 else 0.25)
            if step in (4, 12) and bar > 0:
                add(time, "radioSnare", amp=0.22 if step == 4 else 0.18)
            if step in score["hat"]:
                add(time, "radioHat", amp=rng.uniform(0.058, 0.12), pan=rng.uniform(-0.52, 0.52),
                    hold=0.15 if step % 4 == 2 else 0.065)
            if step % 2 == 1:
                continue
            bass_note = bass[step // 2]
            if isinstance(bass_note, int):
                freq = scale.get_freq(degree + bass_note, octave=2, root=root)
                add(time, "radioBass", freq=freq, amp=0.24, hold=beat * 0.39)
            lead_note = melody[(bar % 2) * 8 + step // 2]
            if isinstance(lead_note, int) and (bar not in (0, 6) or step % 4 == 0):
                freq = scale.get_freq(degree + lead_note, octave=5, root=root)
                shape = LEADS.index(score["lead"])
                add(time + 0.015, "radioLead", freq=freq, amp=0.13, pan=rng.uniform(-0.38, 0.38),
                    hold=beat * 1.1, shape=shape)
                if bar in (3, 5, 7) and step < 12:
                    add(time + beat * 0.75, "radioLead", freq=freq, amp=0.036, pan=0.54,
                        hold=beat * 0.66, shape=shape)
    return sorted(events, key=lambda event: event[0]), BARS * 4 * beat + 0.4


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
        events, duration = events_for(score, index)
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
        return data


class Station:
    def __init__(self, renderer, seeds, model, url):
        self.renderer, self.seeds, self.model, self.url = renderer, seeds, model, url
        self.condition = Condition()
        self.tracks = {}
        self.target = 2
        self.closed = False
        self.worker = Thread(target=self.generate, name="composition", daemon=True)
        self.worker.start()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.worker.join()

    def generate(self):
        index = 1
        previous = self.seeds[0]
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or index <= self.target)
                if self.closed:
                    return
            seed = self.seeds[(index - 1) % len(self.seeds)]
            score = seed if index <= len(self.seeds) else vary(seed, index)
            mode = "Codex score" if index <= len(self.seeds) else "Pattern variation"
            if self.model and index > 2:
                try:
                    score = compose_with_ollama(self.model, self.url, previous)
                    mode = "Ollama"
                except (OSError, URLError, ValueError, KeyError, TypeError) as error:
                    logging.warning("Ollama unavailable, using a local score: %s", error)
            try:
                data = self.renderer.render(score, index)
            except (OSError, EOFError, wave.Error, RuntimeError, subprocess.SubprocessError) as error:
                logging.error("Render failed for track %s: %s", index, error)
                with self.condition:
                    self.condition.wait_for(lambda: self.closed, timeout=3)
                continue
            metadata = {"id": index, "title": score["title"], "bpm": score["bpm"],
                        "key": f"{score['root']} {score['scale']}", "mode": mode, "url": f"/audio/{index}.wav"}
            with self.condition:
                self.tracks[index] = metadata, data
                while len(self.tracks) > 6:
                    del self.tracks[next(iter(self.tracks))]
            logging.info("Rendered %02d · %s · %s", index, score["title"], mode)
            previous = score
            index += 1

    def next_track(self, after):
        with self.condition:
            latest = next(reversed(self.tracks), 0)
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
                after = max(0, int(parse_qs(url.query).get("after", ["0"])[0]))
            except ValueError:
                self.send_error(400)
                return
            track = self.server.station.next_track(after)
            self.respond(200, "application/json", json.dumps(track).encode())
        elif url.path.startswith("/audio/") and url.path.endswith(".wav"):
            name = url.path.removeprefix("/audio/").removesuffix(".wav")
            data = self.server.station.audio(int(name)) if name.isascii() and name.isdigit() and len(name) <= 12 else None
            if data is None:
                self.send_error(404)
                return
            self.respond(200, "audio/wav", data)
        else:
            self.send_error(404)

    def respond(self, status, mime, data):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
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
    parser.add_argument("--render", type=Path, metavar="WAV", help="render the first track and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", force=True)
    seeds = [validate(score) for score in json.loads((ROOT / "scores.json").read_text(encoding="utf-8"))]
    try:
        with tempfile.TemporaryDirectory(prefix="foxdot-radio-") as work:
            renderer = Renderer(args.supercollider_dir, Path(work))
            if args.render:
                args.render.write_bytes(renderer.render(seeds[0], 1))
                return
            with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
                server.station = Station(renderer, seeds, args.ollama_model, args.ollama_url)
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

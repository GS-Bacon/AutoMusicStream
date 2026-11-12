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

from FoxDot import P, PGroup, Scale

from arrangement import (
    CYCLE_LENGTH, LEADS, PRESETS, STYLES, arrangement, ensemble_for, genre_pair,
    melody_variation, mix,
)
from song_form import BARS, REPRISE_BAR, bridge_from_theme, close_voicing, phrase_bars


ROOT = Path(__file__).resolve().parent
RATE = 48000
TAIL = 0.65
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SCALES = ("minor", "dorian", "major", "mixolydian")
SYNTHS = ("radioMix", "radioKick", "radioSnare", "radioHat", "radioPerc",
          "radioBass", "radioPad", "radioLead")


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


MELODY_SLOT_SCHEMA = {
    "anyOf": [
        integer_schema(0, 12),
        {"type": "array", "minItems": 2, "maxItems": 4, "items": integer_schema(-3, 12)},
        {"type": "null"},
    ],
}
FIELDS = {
    "title": {"type": "string", "minLength": 1, "maxLength": 40},
    "bpm": integer_schema(78, 118),
    "root": {"type": "string", "enum": NOTES},
    "scale": {"type": "string", "enum": SCALES},
    "lead": {"type": "string", "enum": LEADS},
    "chords": sequence_schema(4, integer_schema(0, 6)),
    "melody": sequence_schema(16, MELODY_SLOT_SCHEMA),
    "bridge": sequence_schema(16, MELODY_SLOT_SCHEMA),
    "counter": sequence_schema(16, note_schema(7)),
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
    if not isinstance(score, dict):
        raise ValueError("The score must be an object")
    if "counter" not in score:
        score = {**score, "counter": list(STYLES[0].counter)}
    if "bridge" not in score and matches(score.get("melody"), FIELDS["melody"]):
        if any(note is not None for note in score["melody"]):
            score = {**score, "bridge": bridge_from_theme(score["melody"])}
    if score.keys() != FIELDS.keys():
        raise ValueError("The score has missing or unexpected fields")
    for field, schema in FIELDS.items():
        if not matches(score[field], schema):
            raise ValueError(f"Invalid score field: {field}")
    if not score["title"].strip() or not all(
        any(note is not None for note in score[field]) for field in ("melody", "bridge", "counter")
    ):
        raise ValueError("The score needs a title and notes in the theme, bridge and counter")
    if any(len(score[name]) != len(set(score[name])) for name in ("kick", "hat")):
        raise ValueError("Drum positions must be distinct")
    if score["melody"] == score["bridge"]:
        raise ValueError("The bridge must contrast with the theme")
    for field in ("melody", "bridge"):
        for slot in score[field]:
            if isinstance(slot, list) and (len(slot) != len(set(slot)) or max(slot) - min(slot) > 9):
                raise ValueError(f"A {field} chord needs distinct notes within nine scale steps")
    return score


PATTERN_GUIDE = (
    "lead is the main melody instrument for the whole song. "
    "chords are four zero-based scale degrees, one per two bars of the main eight-bar progression. "
    "melody, bridge and counter each have 16 eighth-note slots across two bars, relative to the current chord root. "
    "A melody slot can be a single degree or a chord of 2 to 4 distinct degrees within 9 steps, "
    "e.g. [2, 4, 6, 8] for a rootless ninth chord. Keep sax phrases monophonic and leave room for accompaniment. "
    "counter is an independent lower line played a sixteenth after each slot. "
    "Use chord tones for the counter when it overlaps a strong lead note and leave room for call and response. "
    "bass has 8 eighth-note slots per bar, relative to the chord root. "
    "Null is a rest. kick and hat are distinct positions on a single 16-step bar. "
)
COMPOSER_RULES = (
    ROOT / "skills" / "foxdot-dynamic-arrangement" / "references" / "composer-rules.md"
).read_text(encoding="utf-8")


def compose_with_ollama(model, url, previous, style):
    context = style[0] if style[0] == style[1] else f"{style[0]} to {style[1]}"
    instruction = (
        f"Revise the themes for a 32-bar arrangement in {context}. "
        + PATTERN_GUIDE + "\n" + COMPOSER_RULES + "\n"
        "The arranger handles tempo and drums independently. Keep bpm, root, scale and lead exactly as given. "
        "Develop the theme or bridge to suit the next style. Keep a short motif for continuity. "
        "Give only JSON. "
        f"Previous track: {json.dumps(previous, ensure_ascii=False)}"
    )
    request = Request(url.rstrip("/") + "/api/chat", method="POST",
                      headers={"Content-Type": "application/json"},
                      data=json.dumps({
                          "model": model, "stream": False, "format": SCORE_SCHEMA,
                          "messages": [{"role": "user", "content": instruction}],
                          "options": {"temperature": 0.8, "num_predict": 900},
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

    def revise(self, previous, stopped, style):
        context = style[0] if style[0] == style[1] else f"{style[0]} to {style[1]}"
        prompt = (
            f"You are live-coding themes for a 32-bar arrangement in {context}. "
            "Use the supplied score as data. Return one complete revised score as JSON. "
            "The arranger blends tempo, sound layers and drum grooves independently. "
            "Keep bpm, root, scale and lead exactly. Develop the theme or bridge to suit the next style. "
            "Keep a short motif for continuity. "
            "Keep unedited parts as-is. Use no tools. "
            + PATTERN_GUIDE
            + "\n" + COMPOSER_RULES + "\n"
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
        if any(score[name] != previous[name] for name in ("bpm", "root", "scale", "lead")):
            raise ValueError("Codex changed the tempo, key or lead instrument")
        if all(score[name] == previous[name] for name in FIELDS if name != "title"):
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


def vary(seed, index, fixed_style=None):
    rng = random.Random(index)
    score = dict(seed)
    if fixed_style is None:
        score.update(melody_variation(seed, index), lead=ensemble_for(index).lead)
        if seed.get("bridge") in (None, bridge_from_theme(seed["melody"])):
            score["bridge"] = bridge_from_theme(score["melody"])
    return {
        **score,
        "hat": sorted(set(seed["hat"]) | {rng.choice([3, 9, 15])}) if len(seed["hat"]) < 8 else seed["hat"],
    }


def events_for(score, index, fixed_style=None):
    bars, length = arrangement(index, score["bpm"], fixed_style)
    ensemble = ensemble_for(index, fixed_style)
    scale = getattr(Scale, score["scale"])
    root = NOTES.index(score["root"])
    rng = random.Random(index)
    if "bridge" not in score:
        score = {**score, "bridge": bridge_from_theme(score["melody"])}
    phrases = {field: P[[tuple(slot) if isinstance(slot, list) else slot for slot in score[field]]]
               for field in ("melody", "bridge")}
    counter, bass = (P[score[name]] for name in ("counter", "bass"))
    form = phrase_bars(score, ensemble.form)
    events = []
    cues = []
    previous_voicing = (2, 4, 6)

    def add(time, synth, cue=None, **params):
        onset = time + 0.03
        events.append((onset, synth, params))
        if cue:
            field, slot, duration = cue
            cues.append((round(onset, 4), field, slot, round(duration, 4)))

    def lead(time, freq, voice, amp, hold, pan, cue=None, color=1.0):
        if amp < 0.005:
            return False
        add(time, "radioLead", cue, freq=freq, amp=amp, pan=pan, hold=hold,
            shape=LEADS.index(voice), color=color)
        return True

    def play_group(time, frequencies, voice, amp, hold, pan, cue=None, color=1.0):
        if len(frequencies) == 1:
            lead(time, frequencies[0], voice, amp, hold, pan, cue, color)
            return
        roll = 0.014 if voice == "guitar" else 0
        inner_gain = 0.78 / (len(frequencies) - 1) ** 0.5
        for part, freq in enumerate(frequencies):
            top = part == len(frequencies) - 1
            spread = 0.14 * (2 * part / (len(frequencies) - 1) - 1)
            if lead(time + roll * part, freq, voice, amp * (0.78 if top else inner_gain),
                    hold, pan + spread, cue, color):
                cue = None

    for bar, (feel, part) in enumerate(zip(bars, form)):
        start, beat = feel.start, feel.beat
        swing, drums, shade, echo = (feel.blend(field) for field in ("swing", "drums", "shade", "echo"))
        section = part.section
        building = section.phrase == "build"
        breakdown = section.phrase == "bridge" and ensemble.form != "jazz"
        jazz_bridge_end = ensemble.form == "jazz" and section.phrase == "bridge" and part.position == 7
        brightness = min(1.0, 0.44 + part.position * 0.18) if building else 1.0
        drum_level = drums * section.drums * (1.0 + 0.18 * part.position if building else 1.0)
        first_slot = (bar % 2) * 8
        melody = phrases[part.field]
        has_chords = any(isinstance(melody[slot], PGroup) for slot in part.slots)
        pad_level = mix(0.115, 0.044, shade) * (0.56 if has_chords else 1.0)
        pad_level *= ensemble.pad_gain * section.pad
        changes = part.harmony[0] != part.harmony[1]
        comp = []
        for half, degree in enumerate(part.harmony if changes else part.harmony[:1]):
            chord_length = 2 if changes else 4
            chord_time = start + beat * (half * 2)
            for interval, pan in zip((0, 2, 4, 6), (-0.62, 0.42, -0.3, 0.58)):
                freq = scale.get_freq(degree + interval, octave=4, root=root)
                chord_slot = part.position // 2
                cue = None
                if interval == 0 and degree == score["chords"][chord_slot]:
                    cue = ("chords", chord_slot, beat * chord_length * 0.9)
                add(chord_time, "radioPad", cue, freq=freq, amp=pad_level,
                    pan=pan, hold=beat * (chord_length - 0.9), shade=shade)
            previous_voicing = close_voicing(degree, 4 if bar % 2 == 0 else 8, previous_voicing)
            comp.append([scale.get_freq(pitch, octave=4, root=root) for pitch in previous_voicing])
        if part.cadence:
            tonic = scale.get_freq(0, octave=5, root=root)
            lead(start + 0.012, tonic, score["lead"], 0.145, beat * 2.65, -0.14)

        for step in range(16):
            offset = swing if step % 4 != 0 else 0
            time = start + (step + offset) * beat / 4
            melody_slot = first_slot + step // 2
            half = step // 8 if changes else 0
            degree = part.harmony[half]
            has_lead = melody_slot in part.slots
            breath = (jazz_bridge_end or (building and part.position == section.bars - 1)) and step >= 12
            if breath:
                continue
            if step in ensemble.comp_steps and (not part.cadence or step < 8):
                level = (0.080 if has_lead else 0.115) * section.comp
                play_group(time + 0.012, comp[half], ensemble.comp, level,
                           beat * ensemble.comp_hold, 0.23, color=0.76)
            fill_steps = (8, 12, 14) if part.position <= 1 else (9, 11, 13, 14, 15)
            if part.fill and step in fill_steps:
                add(time, "radioSnare", amp=drum_level * (0.07 + step * 0.005), shade=shade)
            for field, synth, weight, amp, cue_length in (
                ("kick", "radioKick", 0.78, 0.42 if step == 0 else 0.35, 0.15),
                ("snare", "radioSnare", 1.0, 0.27 if step == 4 else 0.23, 0.12),
                ("hat", "radioHat", 0.72, rng.uniform(0.09, 0.17), 0.11),
            ):
                slots = score.get(field, ())
                if ((breakdown and field != "hat") or
                        (part.cadence and (field != "kick" or step != 0))):
                    continue
                level = (feel.hit(field, step) * weight + (step in slots) * (1 - weight)) * drum_level * amp
                if level < 0.012:
                    continue
                cue = (field, slots.index(step), cue_length) if step in slots else None
                params = {"shade": shade, "amp": level}
                if field == "hat":
                    params.update(pan=rng.uniform(-0.56, 0.56), hold=0.16 if step % 4 == 2 else 0.058)
                add(time, synth, cue, **params)

            perc_level = feel.hit("percussion", step) * drum_level if not part.cadence else 0
            if perc_level > 0.05:
                add(time, "radioPerc", amp=0.15 * perc_level, voice=ensemble.perc_voice,
                    pan=rng.uniform(-0.55, 0.55))

            bass_note = bass[step // 2] if step % 2 == 0 else None
            bass_hit = feel.hit("bass_steps", step)
            if (isinstance(bass_note, int) or bass_hit > 0.02) and (not part.cadence or step == 0):
                from_score = isinstance(bass_note, int)
                if not from_score:
                    bass_note = 4 if step in (6, 14) else 0
                freq = scale.get_freq(degree + bass_note, octave=ensemble.bass_octave, root=root)
                hold = beat * (2.0 if part.cadence else (ensemble.bass_hold or mix(0.43, 0.23, shade)))
                if part.cadence:
                    freq = scale.get_freq(0, octave=ensemble.bass_octave, root=root)
                level = mix(0.64, 1.0, drums) * (0.14 * from_score + 0.11 * bass_hit) * section.bass
                cue = ("bass", step // 2, hold) if from_score else None
                if level >= 0.005:
                    add(time, "radioBass", cue, freq=freq, amp=level, hold=hold, voice=ensemble.bass)

            if step % 2:
                note = counter[melody_slot]
                if isinstance(note, int) and not part.cadence:
                    freq = scale.get_freq(degree + note, octave=4, root=root)
                    hold = beat * mix(1.32, 0.64, shade)
                    level = (0.069 if has_lead else 0.127) * section.counter
                    pan = 0.43 if bar % 2 == 0 else 0.32
                    cue = ("counter", melody_slot, min(hold, beat * 0.6))
                    lead(time, freq, ensemble.counter_voice, level, hold, pan, cue)
                continue
            lead_note = melody[melody_slot]
            if has_lead and isinstance(lead_note, (int, PGroup)):
                pitches = sorted(lead_note) if isinstance(lead_note, PGroup) else [lead_note]
                is_chord = len(pitches) > 1
                base = degree
                # Move the whole voicing together so folding the register preserves its intervals.
                while base + pitches[-1] >= 11:
                    base -= 7
                register = part.register
                if register > 0 and base + pitches[-1] > 5:
                    register = 0
                frequencies = [scale.get_freq(base + pitch, octave=5 + register, root=root)
                               for pitch in pitches]
                pan = rng.uniform(-0.20, -0.08)
                accent = 1.0 if step % 4 == 0 else 0.77
                next_note = next((slot for slot in part.slots if slot > melody_slot), first_slot + 8)
                hold = beat * min((next_note - melody_slot) * 0.49 + 0.15, mix(1.60, 0.85, shade))
                if is_chord:
                    hold = beat * min(feel.blend("chord_hold"), (next_note - melody_slot) * 0.5 + 0.18)
                    accent = 1.0 if step % 4 == 2 else 0.93
                hold *= part.space
                melody_time = time + 0.012 + beat * part.delay
                voice = score["lead"]
                cue = (part.field, melody_slot, min(hold, beat * 0.6))
                amplitude = 0.171 * accent * section.melody
                play_group(melody_time, frequencies, voice, amplitude, hold, pan, cue, color=brightness)
                if is_chord and echo > 0.4:
                    for delay, gain, color, echo_pan in ((0.75, 0.49, 0.25, -pan * 2),
                                                        (1.50, 0.24, 0.10, pan * 2)):
                        repeat = melody_time + beat * delay
                        if repeat < length:
                            play_group(repeat, frequencies, voice, amplitude * gain * (echo - 0.4) / 0.6,
                                       min(hold, beat * 0.60), echo_pan, color=color)
                elif echo > 0.4 and step in (0, 6, 10):
                    lead(melody_time + beat * 0.75, frequencies[0], voice, 0.039 * echo,
                         beat * 0.68, -pan * 2, color=0.24)
    return sorted(events, key=lambda event: event[0]), length + TAIL, sorted(cues)


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
    def __init__(self, directory, work, fixed_style=None):
        sclang, self.scsynth = find_supercollider(directory)
        self.work = work
        self.fixed_style = fixed_style
        script = work / "synths.scd"
        shutil.copyfile(ROOT / script.name, script)
        run_sc([sclang, "-D", "-u", "0", str(script), str(work)], timeout=25)
        files = [work / f"{name}.scsyndef" for name in SYNTHS]
        missing = [file.stem for file in files if not file.is_file()]
        if missing:
            raise RuntimeError(f"SuperCollider could not compile: {', '.join(missing)}")
        self.definitions = [file.read_bytes() for file in files]

    def render(self, score, index):
        events, duration, cues = events_for(score, index, self.fixed_style)
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
                     timeout=40, allowed_exit_codes=exit_codes)
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
    def __init__(self, renderer, seeds, model, url, codex=None, fixed_style=None):
        self.renderer, self.model, self.url = renderer, model, url
        self.seeds = [validate(score) for score in seeds]
        self.codex = codex
        self.fixed_style = fixed_style
        self.codex_status = "waiting" if codex else ""
        self.condition = Condition()
        self.tracks = {}
        self.target = 2
        self.stopped = Event()
        self.playing = 0
        self.last_played = 0
        self.pending_revision = None
        self.worker = Thread(target=self.generate, name="arrangement", daemon=True)
        self.worker.start()
        self.composer_worker = None
        if self.codex or self.model:
            self.composer_worker = Thread(target=self.compose, name="composition", daemon=True)
            self.composer_worker.start()

    def close(self):
        with self.condition:
            self.stopped.set()
            self.condition.notify_all()
        self.worker.join()
        if self.composer_worker:
            self.composer_worker.join()

    def compose(self):
        # AI can take longer than a section. Render and play the genre cycle independently.
        requested = 0 if self.codex else 1
        next_attempt = 0
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped.is_set() or (
                    self.playing > requested and self.playing in self.tracks
                    and monotonic() >= next_attempt and monotonic() - self.last_played < 5
                ))
                if self.stopped.is_set():
                    return
                requested = self.playing
                previous = self.tracks[requested][0]["score"]
                left, right, _ = genre_pair(next(reversed(self.tracks)) + 1, self.fixed_style)
                if self.codex:
                    self.codex_status = "composing"
            style = left.name, right.name
            try:
                if self.codex:
                    next_attempt = monotonic() + self.codex.interval
                    logging.info("Codex is revising %s", previous["title"])
                    score = self.codex.revise(previous, self.stopped, style)
                    mode = "Codex live"
                else:
                    score = compose_with_ollama(self.model, self.url, previous, style)
                    score = {**score, **{field: previous[field] for field in ("bpm", "root", "scale", "lead")}}
                    mode = "Ollama"
            except (OSError, URLError, ValueError, KeyError, TypeError, RuntimeError,
                    subprocess.SubprocessError) as error:
                if self.codex:
                    self.codex_status = "retry"
                logging.warning("Using the available score: %s", error)
                continue
            if self.stopped.is_set():
                return
            with self.condition:
                self.pending_revision = score, mode
                if self.codex:
                    self.codex_status = "ready"

    def generate(self):
        index = 1
        revision = None
        revision_index = 0
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped.is_set() or index <= self.target)
                if self.stopped.is_set():
                    return
                if self.pending_revision:
                    revision = self.pending_revision
                    revision_index = index
                    self.pending_revision = None
                    if self.codex_status == "ready":
                        self.codex_status = "rendering"
            if revision:
                score, mode = revision
                if index != revision_index:
                    score = vary(score, index, self.fixed_style)
                elif self.fixed_style is None:
                    score = {**score, "lead": ensemble_for(index).lead}
            else:
                cycle = max(0, index - 2) // CYCLE_LENGTH
                seed = self.seeds[cycle % len(self.seeds)]
                score = seed if index == 1 else vary(seed, index, self.fixed_style)
                score = {**score, **{field: self.seeds[0][field] for field in ("bpm", "root", "scale")}}
                mode = "Codex score" if index == 1 else "Pattern variation"
            try:
                data, cues = self.renderer.render(score, index)
            except (OSError, EOFError, wave.Error, RuntimeError, subprocess.SubprocessError) as error:
                logging.error("Render failed for track %s: %s", index, error)
                with self.condition:
                    self.condition.wait_for(self.stopped.is_set, timeout=3)
                continue
            bars, length = arrangement(index, score["bpm"], self.fixed_style)
            form = phrase_bars(score, ensemble_for(index, self.fixed_style).form)
            metadata = {
                "id": index, "title": score["title"], "bpm": round(bars[0].bpm),
                "key": f"{score['root']} {score['scale']}", "mode": mode, "url": f"/audio/{index}.wav",
                "score": score, "cues": cues, "bars": BARS,
                "barInfo": [
                    {"start": bar.start, "bpm": bar.bpm, "genre": bar.label(), "section": part.section.name,
                     "harmony": part.harmony}
                    for bar, part in zip(bars, form)
                ],
                "musicSeconds": length, "repriseBar": REPRISE_BAR,
            }
            with self.condition:
                self.tracks[index] = metadata, data
                while len(self.tracks) > 6:
                    del self.tracks[next(iter(self.tracks))]
                if self.codex_status == "rendering":
                    self.codex_status = "waiting"
            logging.info("Rendered %02d · %s · %s", index, score["title"], mode)
            index += 1

    def next_track(self, after, playing=0):
        with self.condition:
            latest = next(reversed(self.tracks), 0)
            if playing in self.tracks and playing >= self.playing:
                self.playing = playing
                self.last_played = monotonic()
            if after > latest:
                after = 0
            self.target = max(self.target, after + 2)
            self.condition.notify_all()
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
    parser.add_argument("--style", choices=PRESETS, help="play a single genre instead of the radio rotation")
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
    fixed_style = None
    if args.style:
        fixed_style, score = PRESETS[args.style]
        seeds = [validate({
            **score, "bpm": fixed_style.bpm, "lead": fixed_style.lead,
            "melody": [list(note) if isinstance(note, tuple) else note for note in fixed_style.melody],
            "counter": list(fixed_style.counter), "kick": list(fixed_style.kick), "hat": list(fixed_style.hat),
        })]
    else:
        seeds = [validate(score) for score in json.loads((ROOT / "scores.json").read_text(encoding="utf-8"))]
    try:
        with tempfile.TemporaryDirectory(prefix="foxdot-radio-") as work:
            renderer = Renderer(args.supercollider_dir, Path(work), fixed_style)
            if args.render:
                data, _ = renderer.render(seeds[0], 1)
                args.render.write_bytes(data)
                return
            codex = None
            if args.codex:
                command = find_codex()
                if not command:
                    logging.warning("Codex CLI was not found; using automatic local scores.")
                else:
                    codex = CodexComposer(command, Path(work) / "codex", args.codex_interval)
            with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
                server.station = Station(renderer, seeds, args.ollama_model, args.ollama_url, codex, fixed_style)
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

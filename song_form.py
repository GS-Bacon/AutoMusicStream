"""Expand a two-bar theme and bridge into a 32-bar arrangement."""

from dataclasses import dataclass
from itertools import product


BARS = 32
REPRISE_BAR = 24


@dataclass(frozen=True)
class Section:
    name: str
    bars: int
    phrase: str
    drums: float
    bass: float
    melody: float
    counter: float
    comp: float
    pad: float


# Separate instrumental levels let the foreground change without changing instruments.
ELECTRONIC = (
    Section("Intro", 4, "fragment", 0.22, 0.27, 0.75, 0.34, 0.76, 0.95),
    Section("Theme", 8, "theme", 0.79, 0.82, 0.94, 0.73, 0.79, 0.75),
    Section("Breakdown", 4, "bridge", 0.15, 0.00, 0.62, 0.75, 0.94, 1.05),
    Section("Build", 4, "build", 0.49, 0.27, 0.77, 0.53, 0.74, 0.78),
    Section("Climax", 8, "return", 1.09, 1.15, 1.06, 0.96, 0.92, 0.73),
    Section("Outro", 4, "ending", 0.28, 0.53, 0.76, 0.30, 0.62, 0.85),
)

JAZZ = (
    Section("A · Head", 8, "theme", 0.71, 0.85, 0.89, 0.37, 0.77, 0.52),
    Section("A′ · Variation", 8, "variation", 0.92, 0.97, 0.98, 0.67, 0.91, 0.55),
    Section("B · Bridge", 8, "bridge", 0.56, 0.67, 0.76, 1.00, 1.00, 0.61),
    Section("A″ · Return", 8, "return", 1.02, 1.00, 1.03, 0.75, 0.91, 0.55),
)

AMBIENT = (
    Section("Intro", 4, "fragment", 0.0, 0.15, 0.55, 0.20, 0.54, 0.82),
    Section("Theme", 8, "theme", 0.45, 0.48, 0.82, 0.65, 0.74, 0.86),
    Section("Breakdown", 4, "bridge", 0.0, 0.0, 0.55, 0.75, 0.88, 1.04),
    Section("Build", 4, "build", 0.25, 0.26, 0.73, 0.61, 0.83, 0.98),
    Section("Climax", 8, "return", 0.72, 0.79, 0.98, 0.82, 0.91, 1.10),
    Section("Outro", 4, "ending", 0.0, 0.27, 0.65, 0.24, 0.60, 0.80),
)

FORMS = {"electronic": ELECTRONIC, "jazz": JAZZ, "ambient": AMBIENT}


@dataclass(frozen=True)
class PhraseBar:
    section: Section
    position: int
    harmony: tuple[int, int]
    field: str
    slots: tuple[int, ...]
    register: int
    space: float
    delay: float
    fill: bool
    cadence: bool


def bridge_from_theme(melody):
    """Place two pitches from the hook in a slower, delayed answer."""
    pitches = [max(note) if isinstance(note, (list, tuple)) else note
               for note in melody if note is not None]
    first, last = pitches[0] % 7, pitches[-1] % 7
    return [None, last, None, None, 4, None, None, 2,
            None, None, first, None, None, 4, None, None]


def phrase_bars(score, profile):
    jazz = profile == "jazz"
    result = []
    for section in FORMS[profile]:
        phrase = section.phrase
        for pos in range(section.bars):
            final = len(result) == BARS - 1
            penultimate = len(result) == BARS - 2
            root = score["chords"][pos // 2]
            harmony = (root, root)
            field = "bridge" if phrase == "bridge" or (phrase == "build" and pos < 2) else "melody"
            first = (pos % 2) * 8
            slots = tuple(slot for slot in range(first, first + 8) if score[field][slot] is not None)
            register = 0
            space = 1.0
            delay = 0.0
            if phrase in ("fragment", "ending"):
                slots = slots[:2]
                if phrase == "fragment":
                    root = score["chords"][0]
                    harmony = (root, root)
                    register = -1
                space = 1.25
            elif phrase == "bridge":
                if jazz:
                    harmony = ((3, 3), (3, 3), (5, 5), (5, 5),
                               (1, 1), (1, 4), (1, 4), (4, 4))[pos]
                    if pos < 2:
                        # Give the piano and vibes the first answer of the bridge.
                        slots = slots[:1]
                        register = -1
                else:
                    harmony = ((3, 3), (3, 3), (5, 5), (5, 6))[pos]
                space = 1.35
            elif phrase == "build":
                harmony = ((3, 3), (5, 5), (5, 6), (6, 6))[pos]
                if pos >= 2:
                    slots = slots[:2]
                space = 0.80
            elif phrase == "variation":
                # Restate the opening gesture, then shorten its answer.
                if pos in (3, 7):
                    slots = slots[:-1] or slots
                register = int(pos in (4, 5))
                if pos in (2, 6):
                    delay = 0.25
                    space = 0.82
            elif phrase == "return":
                if pos == 0 and not jazz:
                    harmony = (0, 0)
                register = int(2 <= pos <= 4)

            if penultimate:
                harmony = (1, 4) if jazz else (score["chords"][-1], 6)
            if final:
                harmony = (0, 0)
                slots = ()
            fill = profile != "ambient" and (
                (phrase == "build" and pos >= 1) or
                (phrase in ("theme", "variation", "bridge") and pos == section.bars - 1
                 and (jazz or phrase == "theme"))
            )
            result.append(PhraseBar(section, pos, harmony, field, slots, register, space, delay, fill, final))
    return result


def close_voicing(root, extension, previous):
    """Keep third and seventh and choose the closest octave for each upper voice."""
    pitch_classes = [(root + step) % 7 for step in (2, 6, extension)]
    candidates = product(*(tuple(pitch for pitch in range(-1, 13) if pitch % 7 == pc)
                           for pc in pitch_classes))
    voicings = [tuple(sorted(pitches)) for pitches in candidates if max(pitches) - min(pitches) <= 7]
    return min(voicings, key=lambda pitches: (
        sum(abs(note - old) for note, old in zip(pitches, previous)),
        abs(sum(pitches) - 12),
    ))

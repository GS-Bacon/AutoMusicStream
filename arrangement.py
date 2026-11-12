"""Genre voicings and the bar-by-bar progression shared by all radio modes."""

from dataclasses import dataclass

from song_form import BARS

SECTIONS_PER_BLEND = 2
MORPH_BARS = 8
REFERENCE_BPM = 96
LEADS = (
    "fm", "pulse", "triangle", "keys", "mallet", "pluck", "reed", "bell",
    "guitar", "vibes", "flute", "strings", "organ", "sax", "saw",
)


@dataclass(frozen=True)
class Style:
    name: str
    bpm: int
    lead: str
    comp: str
    counter_voice: str
    bass: int
    kick: tuple[int, ...]
    snare: tuple[int, ...]
    hat: tuple[int, ...]
    percussion: tuple[int, ...]
    perc_voice: int
    bass_steps: tuple[int, ...]
    swing: float
    drums: float
    shade: float
    echo: float
    chord_hold: float
    melody: tuple[int | tuple[int, ...] | None, ...]
    counter: tuple[int | None, ...]
    comp_steps: tuple[int, ...] = (2, 10)
    comp_hold: float = 0.65
    bass_octave: int = 2
    bass_hold: float | None = None
    pad_gain: float = 1.0
    form: str = "electronic"


# Shade moves from a soft kit and pad to a bright, tight kit and chord stabs.
STYLES = (
    Style("Lo-fi Hip Hop", 92, "keys", "guitar", "vibes", 0, (0, 7, 10), (4, 12), (2, 6, 9, 14),
          (3, 11, 15), 0, (0, 6), 0.29, 0.84, 0.16, 0.24, 1.05,
          ((2, 4, 6, 8), None, 4, None, 7, (2, 4, 6), None, 4,
           None, (2, 4, 6, 8), None, 4, None, (0, 2, 6), 2, None),
          (None, 2, None, 4, None, None, 6, None, None, 4, None, None, 2, None, None, 0),
          comp_steps=(0, 10)),
    Style("Deep House", 120, "organ", "pluck", "mallet", 1, (0, 4, 8, 12), (4, 12), (2, 6, 10, 14),
          (4, 12, 15), 1, (2, 6, 10, 14), 0.08, 1.05, 0.79, 0.25, 0.31,
          (None, (2, 4, 6), None, (2, 4, 6, 8), None, 7, None, (2, 6, 9),
           None, (2, 4, 6), None, 4, None, (2, 4, 6, 8), None, (0, 2, 6)),
          (0, None, 2, None, None, 4, None, 6, 2, None, 4, None, None, 6, None, 4)),
    Style("UK Garage", 132, "reed", "mallet", "guitar", 2, (0, 6, 10, 15), (4, 12), (1, 3, 7, 10, 13, 15),
          (4, 8, 12, 14), 1, (0, 6, 11, 14), 0.34, 1.0, 0.93, 0.18, 0.24,
          ((0, 2, 6), None, 6, (2, 6, 9), None, 7, (2, 4, 6), None,
           None, (2, 4, 6, 8), 6, None, (0, 2, 6), 7, None, 2),
          (None, 4, None, None, 2, None, 4, None, 6, None, None, 2, None, None, 4, None)),
    Style("Dub Techno", 118, "pluck", "keys", "strings", 3, (0, 4, 8, 12), (4, 12), (2, 6, 10, 14),
          (5, 9, 13), 2, (0, 8, 14), 0.12, 0.83, 0.57, 0.91, 0.35,
          ((0, 2, 4), None, None, None, None, (2, 4, 6), None, None,
           None, None, (0, 2, 4), None, None, (2, 4, 6, 8), None, None),
          (None, 0, None, None, 4, None, None, 2, None, 2, None, None, 4, None, None, 6)),
    Style("Ambient", 96, "strings", "flute", "bell", 0, (0,), (12,), (10, 15),
          (7, 14), 3, (0, 10), 0.02, 0.24, 0.06, 0.64, 1.85,
          ((2, 4, 8), None, None, None, None, None, 7, None,
           None, (2, 4, 6, 8), None, None, None, None, 4, None),
          (None, None, 0, None, None, 2, None, None, None, None, 4, None, None, None, None, 2),
          form="ambient"),
)
CYCLE_LENGTH = len(STYLES) * SECTIONS_PER_BLEND

PRESETS = {
    "jazz": (
        Style("Jazz", 118, "sax", "keys", "vibes", 4, (0, 8), (4, 12), (4, 12),
              (0, 4, 6, 8, 12, 14), 4, (0, 4, 8, 12), 0.64, 0.58, 0.12, 0.10, 0.65,
              (4, None, 6, 7, None, 6, 4, None,
               None, 2, 4, None, 6, 4, 2, None),
              (None, 2, None, None, 4, None, None, 6,
               4, None, None, 6, None, None, None, 4),
              comp_steps=(2, 7, 12), comp_hold=0.82, bass_octave=3, bass_hold=0.78,
              pad_gain=0.22, form="jazz"),
        {"title": "After Hours", "root": "C", "scale": "major",
         "chords": [1, 4, 0, 5], "bass": [0, None, 2, None, 4, None, 6, None],
         "bridge": [None, 2, None, 4, 6, None, 4, None,
                    2, None, None, 4, None, 2, 0, None]},
    ),
    "cyberpunk": (
        Style("Cyberpunk", 108, "saw", "strings", "pulse", 5, (0, 3, 6, 10, 15), (8,),
              (2, 4, 6, 10, 12, 14, 15), (3, 7, 11, 15), 1, (0, 3, 6, 10, 14),
              0.05, 1.06, 0.88, 0.65, 0.70,
              (4, None, None, 6, 7, None, (2, 4, 7), None,
               None, 7, None, 6, 4, None, 2, None),
              (0, 4, 7, None, 2, None, 4, 6,
               0, 4, 7, None, 2, 4, 7, None),
              comp_steps=(0, 8), comp_hold=1.72),
        {"title": "Neon Circuit", "root": "F", "scale": "minor",
         "chords": [0, 5, 2, 6], "bass": [0, 0, None, 0, None, 7, 4, 0],
         "bridge": [None, None, 2, None, 6, None, None, None,
                    None, 4, None, None, 2, None, None, None]},
    ),
}

# Each slot has a different entry point so the new phrase arrives a few notes at a time.
PHRASE_ENTRY = (0.32, 0.12, 0.66, 0.47, 0.84, 0.36, 0.19, 0.76,
                0.56, 0.22, 0.63, 0.16, 0.88, 0.38, 0.72, 0.43)
MOTIF_SLOTS = {"melody": (2, 11), "counter": (1, 6, 9, 14)}


def mix(left, right, amount):
    return left + (right - left) * amount


@dataclass(frozen=True)
class Bar:
    left: Style
    right: Style
    amount: float
    bpm: float
    start: float

    @property
    def beat(self):
        return 60 / self.bpm

    def blend(self, field):
        return mix(getattr(self.left, field), getattr(self.right, field), self.amount)

    def hit(self, field, step):
        return mix(step in getattr(self.left, field), step in getattr(self.right, field), self.amount)

    def label(self):
        if self.amount <= 0.001 or self.left == self.right:
            return self.left.name
        if self.amount >= 0.999:
            return self.right.name
        return f"{self.left.name} → {self.right.name} · {self.amount:.0%}"


def genre_pair(index, fixed_style=None):
    if fixed_style is not None:
        return fixed_style, fixed_style, 0
    if index == 1:
        return STYLES[0], STYLES[0], 0
    segment, section = divmod(index - 2, SECTIONS_PER_BLEND)
    return STYLES[segment % len(STYLES)], STYLES[(segment + 1) % len(STYLES)], section


def ensemble_for(index, fixed_style=None):
    left, right, section = genre_pair(index, fixed_style)
    return right if section else left


def melody_variation(score, index):
    left, right, section = genre_pair(index)
    progress = (section + 1) / SECTIONS_PER_BLEND
    lines = {}
    for field, motif_slots in MOTIF_SLOTS.items():
        previous, upcoming = getattr(left, field), getattr(right, field)
        shift = 0 if field == "melody" else 5
        line = list(previous)
        for slot in range(len(line)):
            if slot in motif_slots:
                line[slot] = score[field][slot]
            elif progress >= PHRASE_ENTRY[(slot + shift) % len(PHRASE_ENTRY)]:
                line[slot] = upcoming[slot]
        lines[field] = [list(note) if isinstance(note, tuple) else note for note in line]
    return lines


def arrangement(index, reference_bpm, fixed_style=None):
    left, right, section = genre_pair(index, fixed_style)
    start = 0.0
    bars = []
    for bar in range(BARS):
        # Put eight bars of the tempo transition on each side of the song boundary.
        offset = bar if section else bar - (BARS - MORPH_BARS)
        phase = (section + min(max(offset / (MORPH_BARS - 1), 0), 1)) / SECTIONS_PER_BLEND
        amount = phase * phase * (3 - 2 * phase)
        bpm = reference_bpm if fixed_style else mix(left.bpm, right.bpm, amount) + reference_bpm - REFERENCE_BPM
        timing = Bar(left, right, amount, bpm, start)
        bars.append(timing)
        start += timing.beat * 4
    return bars, start

import json
from threading import Event
from time import monotonic, sleep
import unittest

from FoxDot import Scale

from arrangement import CYCLE_LENGTH, LEADS, arrangement
from song_form import BARS, phrase_bars
from station import ROOT, Station, events_for, validate, vary


class TestRenderer:
    def render(self, score, index):
        return b"audio", []


class SlowComposer:
    interval = 60

    def __init__(self, fail=False):
        self.started = Event()
        self.release = Event()
        self.fail = fail

    def revise(self, previous, stopped, style):
        self.started.set()
        if not self.release.wait(3) or self.fail:
            raise RuntimeError("Composer unavailable")
        return {**previous, "melody": [11, *previous["melody"][1:]]}


class AutomaticPlaybackTest(unittest.TestCase):
    def start_station(self, composer):
        seeds = json.loads((ROOT / "scores.json").read_text(encoding="utf-8"))
        station = Station(TestRenderer(), seeds, None, "", composer)
        self.addCleanup(station.close)
        self.addCleanup(composer.release.set)
        return station

    def next_track(self, station, after):
        deadline = monotonic() + 2
        while monotonic() < deadline:
            track = station.next_track(after, after)
            if track:
                self.assertEqual(track["id"], after + 1)
                return track
            sleep(0.01)
        self.fail("Automatic playback did not queue the next section")

    def test_genre_advances_during_composition_and_revision_joins_queue(self):
        composer = SlowComposer()
        station = self.start_station(composer)
        self.next_track(station, 0)
        self.assertFalse(composer.started.is_set())
        self.next_track(station, 1)
        self.assertTrue(composer.started.wait(2))
        self.assertEqual(self.next_track(station, 2)["barInfo"][-1]["genre"], "Deep House")
        self.next_track(station, 3)
        self.assertEqual(self.next_track(station, 4)["barInfo"][-1]["genre"], "UK Garage")

        composer.release.set()
        after = 5
        deadline = monotonic() + 2
        while monotonic() < deadline:
            track = self.next_track(station, after)
            if track["mode"] == "Codex live":
                self.assertEqual(track["score"]["melody"][0], 11)
                break
            after = track["id"]
            sleep(0.01)
        else:
            self.fail("Completed AI revision never entered the automatic queue")

    def test_composer_error_does_not_stop_genre_cycle(self):
        composer = SlowComposer(fail=True)
        composer.release.set()
        station = self.start_station(composer)
        self.next_track(station, 0)
        self.next_track(station, 1)
        self.assertTrue(composer.started.wait(2))
        for after in range(2, 11):
            track = self.next_track(station, after)
        self.assertEqual(track["barInfo"][-1]["genre"], "Lo-fi Hip Hop")
        self.assertEqual(track["mode"], "Pattern variation")


class MelodyArrangementTest(unittest.TestCase):
    def setUp(self):
        self.score = json.loads((ROOT / "scores.json").read_text(encoding="utf-8"))[0]

    def test_both_phrases_change_through_the_genre_cycle(self):
        previous = self.score
        for index in range(2, CYCLE_LENGTH + 2):
            score = validate(vary(self.score, index))
            for field in ("melody", "counter"):
                self.assertNotEqual(score[field], previous[field], (index, field))
            previous = score

    def test_counter_uses_its_own_timing_pitch_and_instrument(self):
        del self.score["counter"]
        score = validate(self.score)
        score["counter"][0] = 2
        events, _, cues = events_for(score, 1)
        bars, _ = arrangement(1, score["bpm"])

        def first_note(field, voice):
            time = next(t for t, role, slot, _ in cues if role == field and slot == 0 and t >= bars[4].start)
            params = next(
                params for onset, synth, params in events
                if round(onset, 4) == time and synth == "radioLead" and params["shape"] == LEADS.index(voice)
            )
            return time, params["freq"]

        lead_time, lead_freq = first_note("melody", "keys")
        counter_time, counter_freq = first_note("counter", "vibes")
        self.assertGreater(counter_time, lead_time)
        self.assertLess(counter_freq, lead_freq)

    def test_melody_keeps_one_instrument_while_guitar_plays_underneath(self):
        score = validate(self.score)
        events, _, cues = events_for(score, 1)
        by_onset = {}
        for time, synth, params in events:
            if synth == "radioLead":
                by_onset.setdefault(round(time, 4), []).append(params)
        melody_times = [time for time, role, _, _ in cues if role == "melody"]
        for time in melody_times:
            main_voices = {LEADS[p["shape"]] for p in by_onset[time] if p["pan"] < 0}
            self.assertEqual(main_voices, {"keys"})
        first_voices = {LEADS[p["shape"]] for p in by_onset[melody_times[0]]}
        self.assertEqual(first_voices, {"keys", "guitar"})

    def test_chord_slot_plays_four_distinct_pitches_on_one_attack(self):
        self.score["melody"][0] = [2, 4, 6, 8]
        events, _, cues = events_for(validate(self.score), 1)
        first_attack = [time for time, role, slot, _ in cues if role == "melody" and slot == 0]
        pitches = [
            params["freq"] for onset, synth, params in events
            if synth == "radioLead" and params["shape"] == LEADS.index("keys")
            and round(onset, 4) == first_attack[0]
        ]
        self.assertEqual(first_attack.count(first_attack[0]), 1)
        self.assertCountEqual(pitches, [Scale.dorian.get_freq(n, octave=4, root=2) for n in (2, 4, 6, 8)])

    def test_invalid_chord_slots_are_rejected(self):
        for chord in ([2], [2, 2, 4], [0, 11], [0, 2, 4, 6, 8], [2, None]):
            with self.subTest(chord=chord), self.assertRaises(ValueError):
                validate({**self.score, "melody": [chord, *self.score["melody"][1:]]})

    def test_breakdown_releases_low_end_and_climax_restates_the_theme(self):
        score = validate(self.score)
        bars, _ = arrangement(1, score["bpm"])
        events, _, cues = events_for(score, 1)
        self.assertEqual(len(bars), BARS)
        self.assertFalse(any(
            synth in ("radioKick", "radioBass") and bars[12].start <= time < bars[16].start
            for time, synth, _ in events
        ))
        self.assertEqual({
            synth for time, synth, _ in events if synth in ("radioKick", "radioBass")
            and bars[20].start <= time < bars[21].start
        }, {"radioKick", "radioBass"})
        self.assertTrue(any(role == "bridge" and bars[12].start <= time < bars[16].start
                            for time, role, _, _ in cues))
        theme = [slot for time, role, slot, _ in cues if role == "melody"
                 and bars[4].start <= time < bars[6].start]
        return_motif = [slot for time, role, slot, _ in cues if role == "melody"
                        and bars[20].start <= time < bars[22].start]
        self.assertEqual(return_motif, theme)

    def test_jazz_bridge_contrasts_and_final_bars_complete_the_cadence(self):
        score = validate(self.score)
        parts = phrase_bars(score, "jazz")
        self.assertEqual([part.section.phrase for part in parts[::8]],
                         ["theme", "variation", "bridge", "return"])
        self.assertTrue(all(part.field == "bridge" for part in parts[16:24]))
        self.assertEqual([part.harmony for part in parts[-2:]], [(1, 4), (0, 0)])

---
name: foxdot-dynamic-arrangement
description: Compose, revise, or review FoxDot Radio arrangements when the user wants stronger musical development, a contrasting bridge or breakdown, or genre-appropriate automatic composition. Applies to the score, song form, and SuperCollider render.
---

# FoxDot dynamic arrangement

Start with the user’s target genre and an audible difference they want between two moments of the same song. Choose a short theme and a point of arrival. Preserve the instruments and their roles across the song when revising its form. Change what the parts play, when they enter, how long they hold, and which registers they occupy.

1. Read [composer-rules.md](references/composer-rules.md) before writing or revising themes. FoxDot Radio supplies the same rules to Codex and Ollama.
2. For this radio, check `song_form.py` for the section lengths, harmony, and part levels. The score’s `melody` and `bridge` each contain two bars of eighth-note slots relative to the current harmony. A number is one note, a list is a chord, and null is a rest. Keep the main theme recognizable at its return. Use the bridge for a separate contour or rhythm, and keep the counterline clear of the foreground.
3. Render a whole song using `python station.py --style jazz --render <output.wav>` or `--style cyberpunk`; omit the style for the default rotation. Check where the bass and drums leave and return, where the chord rhythm changes, and where the melody resolves. Compare the quietest section with the return in the WAV. A peak meter alone cannot confirm the arrangement sounds dynamic.

Use [theory.md](references/theory.md) when choosing a form or diagnosing why a revision still sounds repetitive. Keep the rendered form, score schema, and shared prompt in agreement when changing the generator.

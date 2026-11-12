(
var folder = thisProcess.argv[0];
[
    SynthDef(\radioMix, {
        var sound = In.ar(16, 2);
        var wet = FreeVerb2.ar(sound[0], sound[1], 0.18, 0.78, 0.52);
        Out.ar(0, Limiter.ar(LeakDC.ar(HPF.ar(wet, 27)) * 1.12, 0.87));
    }),
    SynthDef(\radioKick, { |amp = 0.3, shade = 0.5|
        var freq = EnvGen.kr(Env([100 + (shade * 64), 47 + (shade * 7), 42], [0.035, 0.19], \exp));
        var env = EnvGen.ar(Env.perc(0.003, 0.29 - (shade * 0.08), curve: -5), doneAction: 2);
        var tick = BPF.ar(WhiteNoise.ar, 2900, 0.7) * EnvGen.ar(Env.perc(0.001, 0.017));
        Out.ar(16, ((SinOsc.ar(freq) * env * 1.5).tanh + (tick * (0.035 + (shade * 0.16)))).dup * amp);
    }),
    SynthDef(\radioSnare, { |amp = 0.15, shade = 0.5|
        var env = EnvGen.ar(Env.perc(0.002, 0.22 - (shade * 0.06), curve: -5), doneAction: 2);
        var noise = BPF.ar(PinkNoise.ar + (WhiteNoise.ar * shade), 1100 + (shade * 1800), 0.9);
        var body = SinOsc.ar(XLine.kr(224, 120, 0.09)) * (0.52 - (shade * 0.29));
        Out.ar(16, Pan2.ar((noise * 1.5 + body) * env * amp, 0.05));
    }),
    SynthDef(\radioHat, { |amp = 0.1, pan = 0, hold = 0.09, shade = 0.5|
        var env = EnvGen.ar(Env.perc(0.002, hold, curve: -7), doneAction: 2);
        var metal = Pulse.ar([311, 421, 557, 699, 941, 1201], 0.3).sum * 0.22;
        var sound = HPF.ar(WhiteNoise.ar + (metal * shade), 5100 + (shade * 2400));
        Out.ar(16, Pan2.ar(sound * env * amp, pan));
    }),
    SynthDef(\radioPerc, { |amp = 0.12, pan = 0, voice = 0|
        var env = EnvGen.ar(Env.perc(0.002, Select.kr(voice, [0.07, 0.19, 0.11, 0.28, 0.38]), curve: -5),
            doneAction: 2);
        var noise = WhiteNoise.ar;
        var clap = BPF.ar(noise, 1630, 0.9) * EnvGen.ar(Env([1, 0.16, 0.9, 0.25, 1, 0.5],
            [0.009, 0.004, 0.009, 0.005, 0.13]));
        var wood = SinOsc.ar([533, 917, 1517]).sum * 0.28 * EnvGen.ar(Env.perc(0.001, 0.046));
        var ride = BPF.ar(noise, 6550, 0.76) * 0.66
            + (SinOsc.ar([1627, 2423, 4031, 5821]) * [0.13, 0.09, 0.05, 0.03]).sum;
        var sound = Select.ar(voice, [
            BPF.ar(noise, 7100, 0.75) * 0.95,
            clap * 1.8,
            wood,
            SinOsc.ar(XLine.kr(275, 112, 0.13)) * 0.65 + BPF.ar(noise, 470, 0.5) * 0.35,
            ride
        ]);
        Out.ar(16, Pan2.ar(sound * env * amp, pan));
    }),
    SynthDef(\radioBass, { |freq = 65, amp = 0.2, hold = 0.4, voice = 0|
        var env = EnvGen.ar(Env.linen(0.02, hold, 0.11, curve: -3), doneAction: 2);
        var sub = SinOsc.ar(freq);
        var upright = Pluck.ar(PinkNoise.ar, Impulse.kr(0), 0.08, freq.reciprocal, 1.20, 0.52);
        var drive = RLPF.ar(Saw.ar(freq * [0.997, 1.003]).sum * 0.72,
            XLine.kr(2200, 200, 0.22), 0.54);
        var tone = Select.ar(voice, [
            sub + (LFTri.ar(freq * 2) * 0.20),
            sub * 0.79 + RLPF.ar(Saw.ar(freq), XLine.kr(970, 130, 0.20), 0.62) * 0.47,
            SinOsc.ar(freq, SinOsc.ar(freq * 2) * XLine.kr(1.7, 0.06, 0.19)) * 0.88 + (sub * 0.2),
            sub * 0.84 + (LFTri.ar(freq * 1.004) * 0.16) + (SinOsc.ar(freq * 3) * 0.08),
            LPF.ar(upright, 2000) * 0.8 + (sub * XLine.kr(0.55, 0.09, 0.30)),
            (drive * 2.8).tanh * 0.78 + (sub * 0.48)
        ]);
        Out.ar(16, (tone * env * amp).dup);
    }),
    SynthDef(\radioPad, { |freq = 220, amp = 0.04, pan = 0, hold = 3, shade = 0.5|
        var env = EnvGen.ar(Env.linen(0.48 - (shade * 0.28), hold, 0.65, curve: \sin), doneAction: 2);
        var tone = LFTri.ar(freq * [0.997, 1.003]).sum * 0.31 + (SinOsc.ar(freq * 2.002) * 0.24);
        var cut = 760 + (shade * 650) + SinOsc.kr(0.16, freq, 160);
        Out.ar(16, Pan2.ar(LPF.ar(tone, cut), pan) * env * amp);
    }),
    SynthDef(\radioLead, { |freq = 440, amp = 0.11, pan = 0, hold = 0.5, shape = 0, color = 1|
        var attack = Select.kr(shape, [
            0.008, 0.01, 0.016, 0.009, 0.003, 0.004, 0.042, 0.015,
            0.006, 0.008, 0.08, 0.11, 0.018, 0.040, 0.020
        ]);
        var sustain = Select.kr(shape, [
            0.12, 0.19, 0.28, 0.14, 0.035, 0.08, 0.57, 0.12,
            0.32, 0.25, 0.66, 0.74, 0.59, 0.62, 0.54
        ]);
        var release = Select.kr(shape, [
            0.05, 0.05, 0.08, 0.075, 0.04, 0.045, 0.10, 0.13,
            0.075, 0.13, 0.16, 0.19, 0.07, 0.09, 0.13
        ]);
        var env = EnvGen.ar(Env([0, 1, sustain, 0], [attack, hold * 0.70, hold * 0.30 + release],
            [\sin, -3, -3]), doneAction: 2);
        var mod = SinOsc.ar(freq * 2.01) * EnvGen.kr(Env.perc(0.008, 0.26, 1.7));
        var hammer = XLine.kr(1.8, 0.08, 0.18) * SinOsc.ar(freq * 1.001);
        var keys = SinOsc.ar(freq, hammer) * 0.69 + SinOsc.ar(freq * 2.003) * XLine.kr(0.28, 0.035, 0.35);
        var mallet = SinOsc.ar(freq) * 0.73 + SinOsc.ar(freq * 3.99) * XLine.kr(0.40, 0.004, 0.09);
        var pluck = RLPF.ar(Saw.ar(freq * [0.999, 1.001]).sum * 0.48, XLine.kr(3900, 510, 0.18), 0.68);
        var reed = RLPF.ar(Pulse.ar(freq, SinOsc.kr(3.2, 0, 0.08, 0.43)), 2000, 0.85) * 0.55
            + SinOsc.ar(freq * 0.998) * 0.36;
        var bell = SinOsc.ar(freq * 0.999) * 0.56 + SinOsc.ar(freq * 2.76) * XLine.kr(0.31, 0.008, 0.42)
            + SinOsc.ar(freq * 5.4) * XLine.kr(0.15, 0.003, 0.16);
        var string = Pluck.ar(WhiteNoise.ar, Impulse.kr(0), 0.03, freq.reciprocal, 0.82, 0.39);
        var guitar = (BPF.ar(string, 340, 0.95) * 0.55 + LPF.ar(string, 4800) * 0.90)
            + (SinOsc.ar(freq) * 0.28 * XLine.kr(1, 0.11, 0.4));
        var vibes = (SinOsc.ar(freq) * 0.80 + SinOsc.ar(freq * 4) * XLine.kr(0.25, 0.012, 0.24)
            + SinOsc.ar(freq * 9.01) * XLine.kr(0.08, 0.002, 0.07))
            * SinOsc.kr(5.6, 0, 0.19, 0.81);
        var vibrato = freq * SinOsc.kr(5.1, 0, 0.0045, 1);
        var flute = SinOsc.ar(vibrato) * 0.77 + SinOsc.ar(vibrato * 2) * 0.13
            + BPF.ar(PinkNoise.ar, (freq * 3.3).clip(650, 5500), 0.52) * 0.27;
        var strings = LPF.ar(Saw.ar(vibrato * [0.994, 1.006]).sum, (freq * 4.5).clip(1000, 3900)) * 0.36
            + SinOsc.ar(freq) * 0.34;
        var organ = (SinOsc.ar(freq * [0.5, 1, 2, 3]) * [0.15, 0.50, 0.22, 0.095]).sum
            * SinOsc.kr(6.2, 0, 0.1, 0.90);
        var reedSource = Saw.ar(vibrato);
        var sax = (SinOsc.ar(vibrato) * 0.28 + LPF.ar(reedSource, 3000) * 0.48
            + BPF.ar(reedSource, 1050, 0.42) * 0.62
            + BPF.ar(PinkNoise.ar, 2400, 0.80) * 0.16).tanh;
        var saw = RLPF.ar(Saw.ar(freq * [0.993, 1.0, 1.007]).sum * 0.35,
            XLine.kr(3700, 1200, 0.38), 0.5).tanh;
        var tone = Select.ar(shape, [
            SinOsc.ar(freq, mod),
            RLPF.ar(Pulse.ar(freq * 0.999, 0.34), XLine.kr(2400, 430, 0.24), 0.55) * 0.7,
            LFTri.ar(freq) * 0.68 + SinOsc.ar(freq * 2.99) * 0.24,
            keys * SinOsc.kr(4.6, 0, 0.13, 0.87), mallet, pluck, reed, bell,
            guitar, vibes, flute, strings, organ, sax, saw
        ]);
        var filtered = LPF.ar(HPF.ar(tone, 24 + ((1 - color) * 140)), 900 + (color.pow(3) * 13600));
        Out.ar(16, Pan2.ar(filtered * env * amp, pan));
    })
].do({ |definition| definition.writeDefFile(folder) });
0.exit;
)

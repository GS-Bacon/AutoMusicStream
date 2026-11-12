(
var folder = thisProcess.argv[0];
[
    SynthDef(\radioMix, {
        var sound = In.ar(16, 2);
        var wet = FreeVerb2.ar(sound[0], sound[1], 0.18, 0.78, 0.52);
        Out.ar(0, Limiter.ar(LeakDC.ar(HPF.ar(wet, 27)) * 1.12, 0.87));
    }),
    SynthDef(\radioKick, { |amp = 0.3|
        var freq = EnvGen.kr(Env([145, 52, 44], [0.045, 0.19], \exp));
        var env = EnvGen.ar(Env.perc(0.003, 0.32, curve: -5), doneAction: 2);
        var tick = BPF.ar(WhiteNoise.ar, 2900, 0.7) * EnvGen.ar(Env.perc(0.001, 0.017));
        Out.ar(16, ((SinOsc.ar(freq) * env * 1.5).tanh + (tick * 0.09)).dup * amp);
    }),
    SynthDef(\radioSnare, { |amp = 0.15|
        var env = EnvGen.ar(Env.perc(0.002, 0.18, curve: -6), doneAction: 2);
        var noise = BPF.ar(PinkNoise.ar, 2100, 0.9);
        var body = SinOsc.ar(XLine.kr(220, 116, 0.13)) * 0.35;
        Out.ar(16, Pan2.ar((noise * 1.65 + body) * env * amp, 0.05));
    }),
    SynthDef(\radioHat, { |amp = 0.1, pan = 0, hold = 0.09|
        var env = EnvGen.ar(Env.perc(0.002, hold, curve: -7), doneAction: 2);
        var sound = HPF.ar(WhiteNoise.ar, 6900) + (SinOsc.ar(6482) * 0.14);
        Out.ar(16, Pan2.ar(sound * env * amp, pan));
    }),
    SynthDef(\radioBass, { |freq = 65, amp = 0.2, hold = 0.4|
        var env = EnvGen.ar(Env.linen(0.02, hold, 0.11, curve: -3), doneAction: 2);
        var tone = SinOsc.ar(freq) + (LFTri.ar(freq * 2) * 0.16);
        Out.ar(16, (tone * env * amp).dup);
    }),
    SynthDef(\radioPad, { |freq = 220, amp = 0.04, pan = 0, hold = 3|
        var env = EnvGen.ar(Env.linen(0.36, hold, 0.72, curve: \sin), doneAction: 2);
        var tone = (LFTri.ar(freq * [0.997, 1.003]).sum * 0.32) + (SinOsc.ar(freq * 2.002) * 0.24);
        Out.ar(16, Pan2.ar(LPF.ar(tone, 880 + SinOsc.kr(0.16, freq, 200)), pan) * env * amp);
    }),
    SynthDef(\radioLead, { |freq = 440, amp = 0.11, pan = 0, hold = 0.5, shape = 0|
        var env = EnvGen.ar(Env.perc(0.008, hold, curve: -4), doneAction: 2);
        var mod = SinOsc.ar(freq * 2.01) * EnvGen.kr(Env.perc(0.008, 0.26, 1.7));
        var tone = Select.ar(shape, [
            SinOsc.ar(freq, mod),
            RLPF.ar(Pulse.ar(freq * 0.999, 0.34), XLine.kr(2400, 430, 0.24), 0.55) * 0.7,
            LFTri.ar(freq) * 0.68 + SinOsc.ar(freq * 2.99) * 0.24
        ]);
        Out.ar(16, Pan2.ar(tone * env * amp, pan));
    })
].do({ |definition| definition.writeDefFile(folder) });
0.exit;
)

const TAU = Math.PI * 2;
const PALETTES = [
  [192, 256, 322],
  [161, 199, 287],
  [37, 326, 268],
  [226, 277, 173],
];
const SPECTRUM_BARS = 144;
const PARTICLE_LIMIT = 160;

const color = (hue, light, alpha) => `hsla(${hue}, 94%, ${light}%, ${alpha})`;
const ease = (rate, dt) => 1 - Math.exp(-rate * dt);
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

function softLight() {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 160;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(80, 80, 0, 80, 80, 80);
  gradient.addColorStop(0, "#fff");
  gradient.addColorStop(0.09, "#fff");
  gradient.addColorStop(0.27, "#fff8");
  gradient.addColorStop(0.54, "#fff2");
  gradient.addColorStop(1, "#fff0");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 160, 160);
  return canvas;
}

function tintLight(mask, hue) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = mask.width;
  const context = canvas.getContext("2d");
  context.drawImage(mask, 0, 0);
  context.globalCompositeOperation = "source-in";
  context.fillStyle = color(hue, 55, 1);
  context.fillRect(0, 0, canvas.width, canvas.height);
  return canvas;
}

function stars() {
  let seed = 1968;
  const next = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 2 ** 32;
  };
  return Array.from({ length: 190 }, () => ({
    x: next(), y: next(), size: 0.45 + next() ** 3 * 1.65, phase: next() * TAU,
  }));
}

export function createVisualizer(canvas, analyser) {
  const ctx = canvas.getContext("2d", { alpha: false });
  const spectrum = new Uint8Array(analyser.frequencyBinCount);
  const waveform = new Float32Array(analyser.fftSize);
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const hzPerBin = analyser.context.sampleRate / analyser.fftSize;
  const starfield = stars();
  const lightMask = softLight();
  const lights = PALETTES.map((palette) => palette.map((hue) => tintLight(lightMask, hue)));
  const hues = [...PALETTES[0]];
  const particles = [];
  const pulses = [];
  const wavePath = new Float32Array(176);
  const barLevels = new Float32Array(SPECTRUM_BARS);
  const barBins = Array.from({ length: SPECTRUM_BARS }, (_, i) =>
    Math.min(spectrum.length - 1, Math.round(45 * (8400 / 45) ** (i / (SPECTRUM_BARS - 1)) / hzPerBin)));
  let width, height, centerX, centerY, radius, backdrop;
  let palette = 0;
  let previousPalette = 0;
  let paletteMix = 1;
  let lastTime = 0;
  let time = 0;
  let bass = 0;
  let mids = 0;
  let highs = 0;
  let baseline = 0;
  let nextBeat = 0;
  let impact = 0;

  function setTrack(id) {
    const next = (id - 1) % PALETTES.length;
    if (next === palette) return;
    previousPalette = palette;
    palette = next;
    paletteMix = 0;
    document.documentElement.style.setProperty("--accent", color(PALETTES[palette][0], 73, 1));
  }

  function size() {
    width = innerWidth;
    height = innerHeight;
    const ratio = Math.min(devicePixelRatio || 1, 1.5, Math.sqrt(2400000 / (width * height)));
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0);
    const narrow = width / height < 1.12;
    centerX = width * (narrow ? 0.52 : 0.65);
    centerY = height * (narrow ? 0.41 : 0.47);
    radius = Math.min(width * (narrow ? 0.30 : 0.235), height * 0.285);
    backdrop = ctx.createLinearGradient(0, 0, width, height);
    backdrop.addColorStop(0, "#030615");
    backdrop.addColorStop(0.59, "#090921");
    backdrop.addColorStop(1, "#100823");
  }
  window.addEventListener("resize", size);
  size();

  function band(from, to) {
    const first = Math.max(1, Math.round(from / hzPerBin));
    const end = Math.min(spectrum.length, Math.max(first + 1, Math.round(to / hzPerBin)));
    let total = 0;
    for (let bin = first; bin < end; bin++) total += spectrum[bin];
    return total / ((end - first) * 255);
  }

  function emit(strength) {
    pulses.push({ age: 0, strength });
    const count = Math.round(18 + strength * 38);
    for (let i = 0; i < count && particles.length < PARTICLE_LIMIT; i++) {
      const angle = Math.random() * TAU;
      const speed = 0.3 + Math.random() * (0.8 + strength);
      particles.push({
        x: Math.cos(angle) * 0.83, y: Math.sin(angle) * 0.83,
        vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
        age: 0, life: 0.38 + Math.random() * 0.74,
        size: 1 + Math.random() * 2.6, hue: hues[i % hues.length],
      });
    }
  }

  function update(dt) {
    analyser.getByteFrequencyData(spectrum);
    analyser.getFloatTimeDomainData(waveform);
    const low = band(35, 125);
    bass += (low - bass) * ease(13, dt);
    mids += (band(160, 1800) - mids) * ease(8, dt);
    highs += (band(2500, 8500) - highs) * ease(8, dt);
    baseline += (low - baseline) * ease(3.2, dt);
    impact *= Math.exp(-4.3 * dt);
    if (!motion.matches && time >= nextBeat && low > Math.max(0.28, baseline + 0.07)) {
      impact = clamp((low - baseline) * 2.8 + low * 0.42, 0.3, 1);
      nextBeat = time + 0.27;
      emit(impact);
    }
    paletteMix = Math.min(1, paletteMix + dt * 0.9);
    PALETTES[palette].forEach((hue, i) => {
      const distance = (hue - hues[i] + 540) % 360 - 180;
      hues[i] = (hues[i] + distance * ease(3, dt) + 360) % 360;
    });
    barBins.forEach((bin, i) => {
      const level = spectrum[bin] / 255;
      barLevels[i] += (level - barLevels[i]) * ease(level > barLevels[i] ? 24 : 10, dt);
    });
  }

  function glow(index, x, y, size, alpha) {
    const left = x - size;
    const top = y - size;
    if (paletteMix < 1) {
      ctx.globalAlpha = alpha * (1 - paletteMix);
      ctx.drawImage(lights[previousPalette][index], left, top, size * 2, size * 2);
    }
    ctx.globalAlpha = alpha * paletteMix;
    ctx.drawImage(lights[palette][index], left, top, size * 2, size * 2);
    ctx.globalAlpha = 1;
  }

  function background() {
    ctx.fillStyle = backdrop;
    ctx.fillRect(0, 0, width, height);
    ctx.globalCompositeOperation = "screen";
    glow(1, width * 0.81, height * 0.26, Math.max(width, height) * 0.61, 0.19 + mids * 0.17);
    glow(2, width * 0.92, height * 0.78, Math.max(width, height) * 0.52, 0.17 + highs * 0.13);
    glow(0, centerX - radius * 0.55, centerY + radius * 0.46, radius * 2.2, 0.20 + bass * 0.19);
    ctx.globalCompositeOperation = "source-over";

    for (const star of starfield) {
      const x = star.x * width;
      const y = star.y * height;
      const alpha = 0.10 + (Math.sin(time * 1.2 + star.phase) + 1) * (0.11 + highs * 0.12);
      ctx.fillStyle = color(hues[1] + star.phase * 9, 85, alpha);
      ctx.fillRect(x, y, star.size, star.size);
    }

    const gradient = ctx.createLinearGradient(width * 0.12, height, width, 0);
    gradient.addColorStop(0, color(hues[2], 50, 0));
    gradient.addColorStop(0.43, color(hues[1], 64, 0.13 + mids * 0.09));
    gradient.addColorStop(0.81, color(hues[0], 74, 0.29));
    gradient.addColorStop(1, color(hues[2], 58, 0.11));
    ctx.strokeStyle = gradient;
    for (let i = 0; i < 13; i++) {
      const gap = (i - 6) * height * 0.021;
      const drift = Math.sin(time * 0.48 + i * 0.19) * height * 0.031;
      ctx.beginPath();
      ctx.moveTo(-width * 0.13, height * 0.67 + gap * 1.6);
      ctx.bezierCurveTo(width * 0.39, height * 0.96 + gap, centerX - radius * 0.09,
        centerY - radius * 1.21 + drift + gap, width * 1.10, height * 0.19 + gap * 1.6);
      ctx.lineWidth = i % 4 === 0 ? 2 : 0.8;
      ctx.stroke();
    }
  }

  function beatEffects(dt) {
    ctx.globalCompositeOperation = "screen";
    for (let i = pulses.length - 1; i >= 0; i--) {
      const pulse = pulses[i];
      pulse.age += dt;
      const fade = 1 - pulse.age / 1.25;
      if (fade <= 0 || motion.matches) {
        pulses.splice(i, 1);
        continue;
      }
      ctx.beginPath();
      ctx.arc(0, 0, radius * (0.87 + pulse.age * 1.14), 0, TAU);
      ctx.lineWidth = radius * (0.003 + fade * 0.016);
      ctx.strokeStyle = color(hues[0], 69, fade * fade * pulse.strength * 0.68);
      ctx.stroke();
    }
    for (let i = particles.length - 1; i >= 0; i--) {
      const spark = particles[i];
      spark.age += dt;
      const fade = 1 - spark.age / spark.life;
      if (fade <= 0 || motion.matches) {
        particles.splice(i, 1);
        continue;
      }
      spark.x += spark.vx * dt;
      spark.y += spark.vy * dt;
      const x = spark.x * radius;
      const y = spark.y * radius;
      ctx.beginPath();
      ctx.moveTo(x - spark.vx * radius * 0.14 * fade, y - spark.vy * radius * 0.14 * fade);
      ctx.lineTo(x, y);
      ctx.lineWidth = spark.size;
      ctx.strokeStyle = color(spark.hue, 72, fade * 0.85);
      ctx.stroke();
      ctx.fillStyle = color(spark.hue, 94, fade);
      ctx.fillRect(x, y, spark.size * 1.4, spark.size * 1.4);
    }
    ctx.globalCompositeOperation = "source-over";
  }

  function orbits() {
    const tilt = 0.56 + Math.sin(time * 0.61) * 0.11;
    for (let orbit = 0; orbit < 3; orbit++) {
      const turn = time * (orbit === 1 ? -0.18 : 0.23) + orbit * 2.04;
      ctx.save();
      ctx.rotate(tilt + orbit * 1.03);
      ctx.scale(1, 0.43 + orbit * 0.12);
      const reach = radius * (1.20 + orbit * 0.15 + impact * 0.06);
      ctx.beginPath();
      ctx.arc(0, 0, reach, 0, TAU);
      ctx.lineWidth = 1;
      ctx.strokeStyle = color(hues[orbit], 72, 0.23 + mids * 0.13);
      ctx.stroke();
      for (let i = 0; i < 4; i++) {
        const start = turn + i * TAU / 4;
        const arc = 0.31 + i * 0.11 + highs * 0.38;
        ctx.beginPath();
        ctx.arc(0, 0, reach, start, start + arc);
        ctx.lineWidth = 2 + radius * 0.009;
        ctx.strokeStyle = color(hues[orbit], 60, 0.27 + highs * 0.25);
        ctx.stroke();
        ctx.lineWidth = 1.2;
        ctx.strokeStyle = color(hues[orbit], 83, 0.77);
        ctx.stroke();
        const x = Math.cos(start + arc) * reach;
        const y = Math.sin(start + arc) * reach;
        ctx.fillStyle = color(hues[orbit], 91, 0.9);
        ctx.fillRect(x - 1.6, y - 2.6, 3.2, 5.2);
      }
      ctx.restore();
    }
  }

  function equalizer() {
    const inner = radius * (0.84 + bass * 0.09 + impact * 0.055);
    ctx.lineCap = "round";
    for (let group = 0; group < 12; group++) {
      const hue = hues[Math.floor(group / 4)] + (group % 4 - 1.5) * 9;
      ctx.beginPath();
      for (let i = group * 12; i < group * 12 + 12; i++) {
        const angle = i / SPECTRUM_BARS * TAU - Math.PI / 2 + time * 0.14;
        const level = barLevels[i];
        const outer = inner + radius * (0.018 + level ** 1.5 * (0.29 + impact * 0.14));
        const x = Math.cos(angle);
        const y = Math.sin(angle);
        ctx.moveTo(inner * x, inner * y);
        ctx.lineTo(outer * x, outer * y);
      }
      ctx.lineWidth = Math.max(2.8, radius * 0.025);
      ctx.strokeStyle = color(hue, 54, 0.25 + impact * 0.09);
      ctx.stroke();
      ctx.lineWidth = Math.max(1, radius * 0.0095);
      ctx.strokeStyle = color(hue, 75, 0.68 + highs * 0.21);
      ctx.stroke();
    }
    ctx.lineCap = "butt";
  }

  function waveRibbons() {
    for (let i = 0; i < wavePath.length; i++) {
      const sample = i * 5 + 320;
      wavePath[i] = (waveform[sample] + waveform[sample + 1] + waveform[sample + 2]) / 3;
    }
    const gradient = ctx.createLinearGradient(-radius * 0.8, -radius * 0.66, radius * 0.8, radius * 0.66);
    gradient.addColorStop(0, color(hues[0], 77, 0.96));
    gradient.addColorStop(0.53, color(hues[1], 79, 0.91));
    gradient.addColorStop(1, color(hues[2], 73, 0.97));
    ctx.globalCompositeOperation = "screen";
    for (let layer = 0; layer < 5; layer++) {
      ctx.beginPath();
      for (let i = 0; i < wavePath.length; i++) {
        const progress = i / wavePath.length;
        const angle = progress * TAU;
        const sample = wavePath[(i + layer * 19) % wavePath.length];
        const wave = sample * Math.sin(progress * Math.PI) ** 0.6;
        const curl = Math.sin(angle * 3 + time * 1.9 + layer * 0.61) * (0.045 + mids * 0.075);
        const fold = Math.sin(angle * 5 - time * 1.3 - layer * 0.7) * (0.023 + highs * 0.061);
        const reach = radius * (0.43 + layer * 0.05 + bass * 0.075 + impact * 0.08
          + curl + fold + wave * (0.35 + layer * 0.055));
        ctx.lineTo(Math.cos(angle) * reach, Math.sin(angle) * reach);
      }
      ctx.closePath();
      ctx.strokeStyle = color(hues[layer % hues.length], 58, 0.15 + impact * 0.07);
      ctx.lineWidth = Math.max(3, radius * 0.036);
      ctx.stroke();
      ctx.strokeStyle = gradient;
      ctx.globalAlpha = 0.53 + layer * 0.092;
      ctx.lineWidth = Math.max(1, radius * (0.005 + layer * 0.0025));
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.globalCompositeOperation = "source-over";
  }

  function paint(timestamp) {
    const dt = lastTime ? Math.min((timestamp - lastTime) / 1000, 0.05) : 1 / 60;
    lastTime = timestamp;
    time += dt * (motion.matches ? 0.25 : 1);
    update(dt);
    background();
    ctx.save();
    ctx.translate(centerX, centerY);
    ctx.globalCompositeOperation = "screen";
    glow(1, 0, 0, radius * 1.24, 0.23 + mids * 0.22);
    glow(0, -radius * 0.12, radius * 0.08, radius * 0.72, 0.17 + bass * 0.17);
    ctx.globalCompositeOperation = "source-over";
    beatEffects(dt);
    orbits();
    equalizer();
    waveRibbons();
    ctx.restore();

    const shade = ctx.createLinearGradient(0, height * 0.59, 0, height);
    shade.addColorStop(0, "#03040f00");
    shade.addColorStop(1, "#03040fc9");
    ctx.fillStyle = shade;
    ctx.fillRect(0, height * 0.59, width, height * 0.41);
  }

  return { paint, setTrack };
}

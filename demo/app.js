const rawCanvas = document.getElementById('raw-canvas');
const rawCtx = rawCanvas.getContext('2d');
const overlayCanvas = document.getElementById('overlay-canvas');
const overlayCtx = overlayCanvas.getContext('2d');
const modeSelect = document.getElementById('mode-select');
const ballDetectorSelect = document.getElementById('ball-detector-select');
const effectSelect = document.getElementById('effect-select');
const overlayRoot = document.getElementById('overlay-status');
const metricsRoot = document.getElementById('metrics');
const rallyStatsRoot = document.getElementById('rally-stats');
const shotDistRoot = document.getElementById('shot-dist');
const heatmapCanvas = document.getElementById('heatmap-canvas');
const heatmapCtx = heatmapCanvas.getContext('2d');
const landingZonesRoot = document.getElementById('landing-zones');
const netApproachRoot = document.getElementById('net-approach');
const speedStatsRoot = document.getElementById('speed-stats');

const SEI_UUID_HEX = '7ce15f8687544f0fa4cfc9a0ab12f65b';

let ws = null;
let runtimeConfig = null;
let activeSessionId = 0;
let wsMetadataByFrameId = new Map();
let rawPlayer = null;
let overlayPlayer = null;
let activeShotFx = null;
let playerRenderState = new Map();

const SHOT_FX_DURATION_MS = 260;

function renderPairs(root, data) {
  root.innerHTML = '';
  Object.entries(data).forEach(([key, value]) => {
    const keyNode = document.createElement('div');
    keyNode.className = 'key';
    keyNode.textContent = key;
    const valueNode = document.createElement('div');
    valueNode.className = 'value';
    valueNode.textContent = typeof value === 'object' ? JSON.stringify(value) : String(value);
    root.appendChild(keyNode);
    root.appendChild(valueNode);
  });
}

function getSelectedMode() {
  return modeSelect.value || (runtimeConfig ? runtimeConfig.overlay_mode : 'sei');
}

function getSelectedEffect() {
  return effectSelect && effectSelect.value ? effectSelect.value : 'smooth';
}

function configureBallDetectorOptions() {
  if (!ballDetectorSelect) {
    return;
  }
  const availableDetectors = Array.isArray(runtimeConfig.available_ball_detectors) && runtimeConfig.available_ball_detectors.length
    ? runtimeConfig.available_ball_detectors
    : [{ key: 'yolo', label: 'YOLO' }];
  ballDetectorSelect.innerHTML = '';
  availableDetectors.forEach((detector) => {
    const option = document.createElement('option');
    option.value = detector.key;
    option.textContent = detector.label || detector.key;
    ballDetectorSelect.appendChild(option);
  });
  ballDetectorSelect.value = runtimeConfig.ball_detector || availableDetectors[0].key;
  ballDetectorSelect.disabled = availableDetectors.length <= 1;
}

function configureModeOptions() {
  const availableModes = Array.isArray(runtimeConfig.available_modes) && runtimeConfig.available_modes.length
    ? runtimeConfig.available_modes
    : ['sei'];
  const labels = {
    sei: 'SEI 解析叠框',
    websocket: 'WebSocket 叠框',
  };
  modeSelect.innerHTML = '';
  availableModes.forEach((mode) => {
    const option = document.createElement('option');
    option.value = mode;
    option.textContent = labels[mode] || mode;
    modeSelect.appendChild(option);
  });
  modeSelect.value = runtimeConfig.overlay_mode || availableModes[0];
  modeSelect.disabled = availableModes.length <= 1;
}

function concatArrays(chunks) {
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Uint8Array(totalLength);
  let offset = 0;
  chunks.forEach((chunk) => {
    merged.set(chunk, offset);
    offset += chunk.length;
  });
  return merged;
}

function hexByte(value) {
  return value.toString(16).padStart(2, '0').toUpperCase();
}

function findStartCode(buffer, startIndex = 0) {
  for (let index = startIndex; index < buffer.length - 3; index += 1) {
    if (buffer[index] === 0x00 && buffer[index + 1] === 0x00 && buffer[index + 2] === 0x01) {
      return { index, length: 3 };
    }
    if (
      index < buffer.length - 4 &&
      buffer[index] === 0x00 &&
      buffer[index + 1] === 0x00 &&
      buffer[index + 2] === 0x00 &&
      buffer[index + 3] === 0x01
    ) {
      return { index, length: 4 };
    }
  }
  return null;
}

function removeEmulationPrevention(data) {
  const output = [];
  for (let index = 0; index < data.length; index += 1) {
    if (
      index + 2 < data.length &&
      data[index] === 0x00 &&
      data[index + 1] === 0x00 &&
      data[index + 2] === 0x03
    ) {
      output.push(0x00, 0x00);
      index += 2;
      continue;
    }
    output.push(data[index]);
  }
  return new Uint8Array(output);
}

function getNalType(nalUnit) {
  const startCode = nalUnit[2] === 0x01 ? 3 : 4;
  return nalUnit[startCode] & 0x1F;
}

function extractSeiMetadata(nalUnit) {
  const startCode = nalUnit[2] === 0x01 ? 3 : 4;
  const rbsp = removeEmulationPrevention(nalUnit.slice(startCode + 1));
  let cursor = 0;
  while (cursor + 2 <= rbsp.length) {
    let payloadType = 0;
    while (cursor < rbsp.length && rbsp[cursor] === 0xFF) {
      payloadType += 0xFF;
      cursor += 1;
    }
    if (cursor >= rbsp.length) {
      break;
    }
    payloadType += rbsp[cursor];
    cursor += 1;

    let payloadSize = 0;
    while (cursor < rbsp.length && rbsp[cursor] === 0xFF) {
      payloadSize += 0xFF;
      cursor += 1;
    }
    if (cursor >= rbsp.length) {
      break;
    }
    payloadSize += rbsp[cursor];
    cursor += 1;
    const payload = rbsp.slice(cursor, cursor + payloadSize);
    cursor += payloadSize;
    if (payloadType === 5 && payload.length > 16) {
      const uuidHex = [...payload.slice(0, 16)].map((value) => value.toString(16).padStart(2, '0')).join('');
      if (uuidHex === SEI_UUID_HEX) {
        const text = new TextDecoder().decode(payload.slice(16));
        return JSON.parse(text);
      }
    }
    if (cursor < rbsp.length && rbsp[cursor] === 0x80) {
      break;
    }
  }
  return null;
}

function getCodecFromSps(nalUnit) {
  const startCode = nalUnit[2] === 0x01 ? 3 : 4;
  const profile = nalUnit[startCode + 1];
  const constraints = nalUnit[startCode + 2];
  const level = nalUnit[startCode + 3];
  return `avc1.${hexByte(profile)}${hexByte(constraints)}${hexByte(level)}`;
}

function normalizeBox(box) {
  return Array.isArray(box) && box.length === 4 ? box.map((value) => Number(value)) : null;
}

function normalizeTrail(points) {
  if (!Array.isArray(points)) {
    return [];
  }
  return points
    .filter((point) => Array.isArray(point) && point.length >= 2)
    .map((point) => [Number(point[0]), Number(point[1])])
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
}

function subdivideTrail(points) {
  if (points.length < 3) {
    return points.slice();
  }
  const refined = [points[0]];
  for (let index = 0; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const q = [
      current[0] * 0.75 + next[0] * 0.25,
      current[1] * 0.75 + next[1] * 0.25,
    ];
    const r = [
      current[0] * 0.25 + next[0] * 0.75,
      current[1] * 0.25 + next[1] * 0.75,
    ];
    refined.push(q, r);
  }
  refined.push(points[points.length - 1]);
  return refined;
}

function smoothRenderTrail(ballTrail, ballBox) {
  if (!ballTrail.length) {
    return [];
  }
  let points = ballTrail.slice();
  if (ballBox && points.length) {
    points[points.length - 1] = [
      (ballBox[0] + ballBox[2]) / 2,
      (ballBox[1] + ballBox[3]) / 2,
    ];
  }
  if (ballBox && points.length >= 2) {
    const head = points[points.length - 1];
    const prev = points[points.length - 2];
    points = [
      ...points.slice(0, -1),
      [
        prev[0] * 0.35 + head[0] * 0.65,
        prev[1] * 0.35 + head[1] * 0.65,
      ],
      head,
    ];
  }
  points = subdivideTrail(points);
  points = subdivideTrail(points);
  return points;
}

function predictBallHead(ballTrail, ballBox) {
  const sourcePoints = ballTrail.length ? ballTrail : [];
  const alignedHead = ballBox
    ? [((ballBox[0] + ballBox[2]) / 2), ((ballBox[1] + ballBox[3]) / 2)]
    : sourcePoints[sourcePoints.length - 1];
  if (!alignedHead) {
    return null;
  }
  if (sourcePoints.length < 2) {
    return alignedHead;
  }
  const tail = sourcePoints[sourcePoints.length - 2];
  const head = sourcePoints[sourcePoints.length - 1];
  const velocityX = head[0] - tail[0];
  const velocityY = head[1] - tail[1];
  const speed = Math.hypot(velocityX, velocityY);
  if (!Number.isFinite(speed) || speed < 2) {
    return alignedHead;
  }
  const leadScale = Math.min(0.38, 0.14 + speed / 140);
  return [
    alignedHead[0] + velocityX * leadScale,
    alignedHead[1] + velocityY * leadScale,
  ];
}

function buildRenderedBallBox(ballBox, predictedHead) {
  if (!ballBox) {
    return null;
  }
  if (!predictedHead) {
    return ballBox;
  }
  const [x1, y1, x2, y2] = ballBox;
  const halfWidth = (x2 - x1) / 2;
  const halfHeight = (y2 - y1) / 2;
  return [
    predictedHead[0] - halfWidth,
    predictedHead[1] - halfHeight,
    predictedHead[0] + halfWidth,
    predictedHead[1] + halfHeight,
  ];
}

function blendBox(fromBox, toBox, weight) {
  return fromBox.map((value, index) => value * (1 - weight) + toBox[index] * weight);
}

function predictPlayerBox(box, previousRawBox) {
  if (!previousRawBox) {
    return box.slice();
  }
  const width = Math.max(box[2] - box[0], 1);
  const height = Math.max(box[3] - box[1], 1);
  const maxShiftX = width * 0.32;
  const maxShiftY = height * 0.24;
  return box.map((value, index) => {
    const velocity = value - previousRawBox[index];
    const maxShift = index % 2 === 0 ? maxShiftX : maxShiftY;
    const predictedShift = Math.max(-maxShift, Math.min(maxShift, velocity * 0.22));
    return value + predictedShift;
  });
}

function getRenderedPlayerBox(playerId, box) {
  const previous = playerRenderState.get(playerId) || null;
  const predicted = predictPlayerBox(box, previous ? previous.rawBox : null);
  const rendered = previous ? blendBox(previous.renderedBox, predicted, 0.72) : predicted;
  playerRenderState.set(playerId, {
    rawBox: box.slice(),
    renderedBox: rendered.slice(),
  });
  return rendered;
}

function prunePlayerRenderState(activePlayerIds) {
  [...playerRenderState.keys()].forEach((playerId) => {
    if (!activePlayerIds.has(playerId)) {
      playerRenderState.delete(playerId);
    }
  });
}

function traceSmoothTrail(ctx, points) {
  if (!points.length) {
    return;
  }
  ctx.beginPath();
  ctx.moveTo(points[0][0], points[0][1]);
  if (points.length === 2) {
    ctx.lineTo(points[1][0], points[1][1]);
    return;
  }
  for (let index = 1; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const midX = (current[0] + next[0]) / 2;
    const midY = (current[1] + next[1]) / 2;
    ctx.quadraticCurveTo(current[0], current[1], midX, midY);
  }
  const penultimate = points[points.length - 2];
  const last = points[points.length - 1];
  ctx.quadraticCurveTo(penultimate[0], penultimate[1], last[0], last[1]);
}

function drawSmoothTrail(ctx, points) {
  if (points.length < 2) {
    return;
  }
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  ctx.shadowBlur = 18;
  ctx.shadowColor = 'rgba(255, 120, 0, 0.28)';
  ctx.strokeStyle = 'rgba(255, 120, 0, 0.18)';
  ctx.lineWidth = 18;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  ctx.shadowBlur = 10;
  ctx.shadowColor = 'rgba(255, 180, 0, 0.2)';
  ctx.strokeStyle = 'rgba(255, 170, 0, 0.32)';
  ctx.lineWidth = 10;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  ctx.shadowBlur = 0;
  ctx.strokeStyle = 'rgba(255, 235, 160, 0.7)';
  ctx.lineWidth = 4;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  points.forEach((point, index) => {
    const alpha = (index + 1) / points.length;
    ctx.fillStyle = `rgba(255, 220, 90, ${0.12 + alpha * 0.24})`;
    ctx.beginPath();
    ctx.arc(point[0], point[1], 2.5 + alpha * 3.5, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.restore();
}

function drawCometTrail(ctx, points, boost = 0) {
  if (points.length < 2) {
    return;
  }
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.shadowBlur = 22 + boost * 10;
  ctx.shadowColor = 'rgba(111, 208, 255, 0.45)';
  ctx.strokeStyle = `rgba(86, 196, 255, ${0.22 + boost * 0.16})`;
  ctx.lineWidth = 14 + boost * 5;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  ctx.strokeStyle = `rgba(230, 250, 255, ${0.55 + boost * 0.2})`;
  ctx.lineWidth = 4 + boost * 2;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  const head = points[points.length - 1];
  ctx.fillStyle = `rgba(255, 255, 255, ${0.72 + boost * 0.18})`;
  ctx.beginPath();
  ctx.arc(head[0], head[1], 8 + boost * 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawFlameTrail(ctx, points, boost = 0) {
  if (points.length < 2) {
    return;
  }
  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  ctx.shadowBlur = 30 + boost * 14;
  ctx.shadowColor = 'rgba(255, 82, 18, 0.48)';
  ctx.strokeStyle = `rgba(255, 72, 18, ${0.22 + boost * 0.16})`;
  ctx.lineWidth = 24 + boost * 8;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  ctx.shadowBlur = 18 + boost * 10;
  ctx.shadowColor = 'rgba(255, 176, 48, 0.42)';
  ctx.strokeStyle = `rgba(255, 166, 32, ${0.4 + boost * 0.18})`;
  ctx.lineWidth = 12 + boost * 5;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  ctx.shadowBlur = 8 + boost * 5;
  ctx.shadowColor = 'rgba(255, 245, 190, 0.3)';
  ctx.strokeStyle = `rgba(255, 244, 208, ${0.78 + boost * 0.14})`;
  ctx.lineWidth = 4 + boost * 2;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  points.forEach((point, index) => {
    const alpha = (index + 1) / points.length;
    const emberOffset = (1 - alpha) * (10 + boost * 8);
    ctx.fillStyle = `rgba(255, 148, 48, ${0.08 + alpha * 0.18})`;
    ctx.beginPath();
    ctx.arc(point[0] - emberOffset * 0.35, point[1] + emberOffset * 0.18, 2 + alpha * 4, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.restore();
}

function drawRibbonTrail(ctx, points, boost = 0) {
  if (points.length < 2) {
    return;
  }
  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  ctx.shadowBlur = 24 + boost * 10;
  ctx.shadowColor = 'rgba(94, 255, 208, 0.34)';
  ctx.strokeStyle = `rgba(72, 255, 202, ${0.18 + boost * 0.14})`;
  ctx.lineWidth = 20 + boost * 7;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  ctx.shadowBlur = 10 + boost * 5;
  ctx.shadowColor = 'rgba(214, 255, 244, 0.26)';
  ctx.strokeStyle = `rgba(186, 255, 240, ${0.48 + boost * 0.18})`;
  ctx.lineWidth = 9 + boost * 3;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  ctx.strokeStyle = `rgba(248, 255, 252, ${0.72 + boost * 0.12})`;
  ctx.lineWidth = 3.5 + boost * 1.5;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  points.forEach((point, index) => {
    const alpha = (index + 1) / points.length;
    const spread = (1 - alpha) * (6 + boost * 4);
    ctx.fillStyle = `rgba(172, 255, 231, ${0.08 + alpha * 0.12})`;
    ctx.beginPath();
    ctx.arc(point[0] + spread, point[1] - spread * 0.3, 2 + alpha * 3, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.restore();
}

function getEffectPalette(effect, boost = 0) {
  if (effect === 'comet') {
    return {
      burstStroke: `rgba(178, 236, 255, ${0.45 + boost * 0.4})`,
      burstFill: `rgba(232, 248, 255, ${0.2 + boost * 0.32})`,
      ballAura: `rgba(122, 220, 255, ${0.28 + boost * 0.16})`,
      ballCore: '#c9f3ff',
    };
  }
  if (effect === 'flame') {
    return {
      burstStroke: `rgba(255, 145, 60, ${0.5 + boost * 0.36})`,
      burstFill: `rgba(255, 226, 176, ${0.22 + boost * 0.34})`,
      ballAura: `rgba(255, 98, 28, ${0.38 + boost * 0.18})`,
      ballCore: '#fff0a8',
    };
  }
  if (effect === 'ribbon') {
    return {
      burstStroke: `rgba(172, 255, 226, ${0.48 + boost * 0.36})`,
      burstFill: `rgba(225, 255, 242, ${0.2 + boost * 0.32})`,
      ballAura: `rgba(82, 255, 198, ${0.28 + boost * 0.16})`,
      ballCore: '#e4fff4',
    };
  }
  return {
    burstStroke: `rgba(255, 200, 90, ${0.52 + boost * 0.36})`,
    burstFill: `rgba(255, 245, 210, ${0.18 + boost * 0.35})`,
    ballAura: `rgba(255, 140, 0, ${0.35 + boost * 0.18})`,
    ballCore: '#ffde59',
  };
}

function drawTrailByEffect(ctx, points, effect, boost = 0) {
  if (effect === 'comet') {
    drawCometTrail(ctx, points, boost);
    return;
  }
  if (effect === 'flame') {
    drawFlameTrail(ctx, points, boost);
    return;
  }
  if (effect === 'ribbon') {
    drawRibbonTrail(ctx, points, boost);
    return;
  }
  drawSmoothTrail(ctx, points);
}

function markShotEffect(metadata, ballBox, ballTrail) {
  if (!metadata || !metadata.shot_event) {
    return;
  }
  const shotPts = Number(metadata.shot_event.pts);
  const framePts = Number(metadata.pts || 0);
  if (!Number.isFinite(shotPts) || Math.abs(framePts - shotPts) > 0.12) {
    return;
  }
  const anchor = ballBox
    ? [((ballBox[0] + ballBox[2]) / 2), ((ballBox[1] + ballBox[3]) / 2)]
    : ballTrail[ballTrail.length - 1];
  if (!anchor) {
    return;
  }
  const signature = `${shotPts.toFixed(3)}:${Number(metadata.shot_event.player_id || 0)}`;
  if (activeShotFx && activeShotFx.signature === signature) {
    return;
  }
  activeShotFx = {
    signature,
    startedAt: performance.now(),
    x: anchor[0],
    y: anchor[1],
    speedKmh: Number(metadata.shot_event.speed_kmh || 0),
  };
}

function getShotBoost() {
  if (!activeShotFx) {
    return 0;
  }
  const ageMs = performance.now() - activeShotFx.startedAt;
  if (ageMs >= SHOT_FX_DURATION_MS) {
    activeShotFx = null;
    return 0;
  }
  return 1 - ageMs / SHOT_FX_DURATION_MS;
}

function drawShotBurst(ctx, effect, boost) {
  if (!activeShotFx || boost <= 0) {
    return;
  }
  const radiusBase = 34 + boost * 42;
  const angleStep = effect === 'arcade' ? 6 : 8;
  const palette = getEffectPalette(effect, boost);
  ctx.save();
  ctx.translate(activeShotFx.x, activeShotFx.y);
  ctx.globalCompositeOperation = 'screen';
  ctx.strokeStyle = palette.burstStroke;
  ctx.lineWidth = 3 + boost * 4;
  for (let index = 0; index < angleStep; index += 1) {
    const angle = (Math.PI * 2 * index) / angleStep;
    const inner = 8 + boost * 8;
    const outer = radiusBase + (index % 2 === 0 ? 10 : -2);
    ctx.beginPath();
    ctx.moveTo(Math.cos(angle) * inner, Math.sin(angle) * inner);
    ctx.lineTo(Math.cos(angle) * outer, Math.sin(angle) * outer);
    ctx.stroke();
  }
  ctx.fillStyle = palette.burstFill;
  ctx.beginPath();
  ctx.arc(0, 0, 16 + boost * 18, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function formatMetric(value, unit, digits = 1) {
  const numeric = Number(value || 0);
  return `${numeric.toFixed(digits)} ${unit}`;
}

function drawStatsPanel(ctx, canvas, stats) {
  if (!stats || !Object.keys(stats).length) {
    return;
  }
  const panelWidth = Math.min(420, canvas.width * 0.28);
  const rowHeight = 30;
  const panelHeight = 196;
  const startX = canvas.width - panelWidth - 18;
  const startY = canvas.height - panelHeight - 18;
  const rows = [
    ['击球数', `${Math.round(Number(stats.player_1_number_of_shots || 0))}`, `${Math.round(Number(stats.player_2_number_of_shots || 0))}`],
    ['跑动距离', formatMetric(stats.player_1_total_distance_run, 'm'), formatMetric(stats.player_2_total_distance_run, 'm')],
    ['卡路里', formatMetric(stats.player_1_total_calories_burned, 'kcal'), formatMetric(stats.player_2_total_calories_burned, 'kcal')],
    ['瞬时跑速', formatMetric(stats.player_1_last_player_speed, 'km/h'), formatMetric(stats.player_2_last_player_speed, 'km/h')],
    ['击球时速', formatMetric(stats.player_1_last_shot_speed, 'km/h'), formatMetric(stats.player_2_last_shot_speed, 'km/h')],
  ];

  ctx.save();
  ctx.fillStyle = 'rgba(6, 12, 24, 0.62)';
  ctx.strokeStyle = 'rgba(139, 208, 255, 0.28)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(startX, startY, panelWidth, panelHeight, 16);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 18px Arial';
  ctx.fillText('实时球员数据', startX + 16, startY + 28);

  const labelX = startX + 18;
  const p1X = startX + panelWidth * 0.54;
  const p2X = startX + panelWidth * 0.79;
  ctx.font = 'bold 14px Arial';
  ctx.fillStyle = '#ffd86b';
  ctx.fillText('P1', p1X, startY + 54);
  ctx.fillStyle = '#8ad6ff';
  ctx.fillText('P2', p2X, startY + 54);

  rows.forEach((row, index) => {
    const top = startY + 62 + index * rowHeight;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.07)';
    ctx.beginPath();
    ctx.moveTo(startX + 14, top);
    ctx.lineTo(startX + panelWidth - 14, top);
    ctx.stroke();

    ctx.font = '13px Arial';
    ctx.fillStyle = '#dce7f6';
    ctx.fillText(row[0], labelX, top + 20);
    ctx.fillStyle = '#ffd86b';
    ctx.fillText(row[1], p1X - 6, top + 20);
    ctx.fillStyle = '#8ad6ff';
    ctx.fillText(row[2], p2X - 6, top + 20);
  });

  ctx.font = '12px Arial';
  ctx.fillStyle = '#9bd0ff';
  ctx.fillText(`球速 ${formatMetric(stats.ball_speed_kmh, 'km/h')}`, startX + 16, startY + panelHeight - 12);
  ctx.restore();
}

function rememberWsMetadata(metadata) {
  if (!metadata || metadata.frame_id === undefined) {
    return;
  }
  wsMetadataByFrameId.set(Number(metadata.frame_id), metadata);
  const keys = [...wsMetadataByFrameId.keys()].sort((a, b) => a - b);
  while (keys.length > 160) {
    wsMetadataByFrameId.delete(keys.shift());
  }
}

function findWsMetadata(streamMetadata, fallbackTimestampUs) {
  if (streamMetadata && wsMetadataByFrameId.has(Number(streamMetadata.frame_id))) {
    return wsMetadataByFrameId.get(Number(streamMetadata.frame_id));
  }
  const pts = streamMetadata ? Number(streamMetadata.pts || 0) : fallbackTimestampUs / 1_000_000;
  let candidate = null;
  let minDistance = Number.POSITIVE_INFINITY;
  wsMetadataByFrameId.forEach((metadata) => {
    const distance = Math.abs(Number(metadata.pts || 0) - pts);
    if (distance < minDistance) {
      minDistance = distance;
      candidate = metadata;
    }
  });
  return minDistance <= 0.2 ? candidate : null;
}

function drawOverlay(ctx, canvas, metadata) {
  if (!metadata) {
    return;
  }

  const playerBoxes = metadata.player_boxes || {};
  const activePlayerIds = new Set();
  Object.entries(playerBoxes).forEach(([playerId, box]) => {
    const normalized = normalizeBox(box);
    if (!normalized) {
      return;
    }
    activePlayerIds.add(String(playerId));
    const [x1, y1, x2, y2] = getRenderedPlayerBox(String(playerId), normalized);
    const footX = (x1 + x2) / 2;
    const footY = y2;
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.ellipse(footX, footY, Math.max((x2 - x1) * 0.35, 18), Math.max((x2 - x1) * 0.12, 8), 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = '#ffffff';
    ctx.font = '20px Arial';
    ctx.fillText(`P${playerId}`, x1, Math.max(y1 - 10, 24));
  });
  prunePlayerRenderState(activePlayerIds);

  const ballBox = normalizeBox(metadata.ball_box);
  const rawBallTrail = normalizeTrail(metadata.ball_trail);
  const predictedBallHead = predictBallHead(rawBallTrail, ballBox);
  const ballTrail = smoothRenderTrail(rawBallTrail, ballBox);
  if (predictedBallHead && ballTrail.length) {
    ballTrail[ballTrail.length - 1] = predictedBallHead;
  }
  const renderedBallBox = buildRenderedBallBox(ballBox, predictedBallHead);
  const effect = getSelectedEffect();
  markShotEffect(metadata, renderedBallBox, ballTrail);
  const shotBoost = getShotBoost();
  const effectPalette = getEffectPalette(effect, shotBoost);
  if (ballTrail.length >= 2) {
    drawTrailByEffect(ctx, ballTrail, effect, shotBoost);
  }

  if (renderedBallBox) {
    const [x1, y1, x2, y2] = renderedBallBox;
    const centerX = (x1 + x2) / 2;
    const centerY = (y1 + y2) / 2;
    const radius = Math.max((x2 - x1) / 2, 6);
    ctx.fillStyle = effectPalette.ballAura;
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius + 8 + shotBoost * 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = effectPalette.ballCore;
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius + shotBoost * 2.5, 0, Math.PI * 2);
    ctx.fill();
  }

  drawShotBurst(ctx, effect, shotBoost);

  const statusText = `frame=${metadata.frame_id} pts=${Number(metadata.pts || 0).toFixed(3)} status=${metadata.status || 'idle'} mode=${getSelectedMode()}`;
  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
  ctx.fillRect(12, 12, Math.max(420, statusText.length * 9), 34);
  ctx.fillStyle = '#00ff7f';
  ctx.font = '18px Arial';
  ctx.fillText(statusText, 18, 35);

  const stats = metadata.stats_row || {};
  if (Object.keys(stats).length) {
    drawStatsPanel(ctx, canvas, stats);
  }
}

class StreamPlayer {
  constructor(canvas, ctx, streamUrl, onFrame, defaultFps = 25) {
    this.canvas = canvas;
    this.ctx = ctx;
    this.streamUrl = streamUrl;
    this.onFrame = onFrame;
    this.defaultFps = defaultFps;
    this.decoder = null;
    this.decoderConfigured = false;
    this.streamMetadataByTimestamp = new Map();
    this.annexbBuffer = new Uint8Array(0);
    this.currentAccessUnit = [];
    this.syntheticTimestampUs = 0;
    this.abortController = null;
  }

  reset() {
    this.close();
    if (this.decoder) {
      this.decoder.close();
    }
    this.decoder = new VideoDecoder({
      output: (frame) => this.handleDecodedFrame(frame),
      error: (error) => console.error('VideoDecoder error:', error),
    });
    this.decoderConfigured = false;
    this.streamMetadataByTimestamp = new Map();
    this.annexbBuffer = new Uint8Array(0);
    this.currentAccessUnit = [];
    this.syntheticTimestampUs = 0;
    this.abortController = new AbortController();
  }

  close() {
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
    if (this.decoder) {
      try {
        this.decoder.close();
      } catch (_error) {
        // Ignore decoder shutdown races during mode switches.
      }
      this.decoder = null;
    }
    this.decoderConfigured = false;
  }

  configureDecoderIfNeeded(codec) {
    if (this.decoderConfigured) {
      return;
    }
    this.decoder.configure({
      codec,
      optimizeForLatency: true,
      hardwareAcceleration: 'prefer-hardware',
    });
    this.decoderConfigured = true;
  }

  extractNals() {
    const nals = [];
    while (true) {
      const first = findStartCode(this.annexbBuffer, 0);
      if (!first) {
        this.annexbBuffer = new Uint8Array(0);
        break;
      }
      if (first.index > 0) {
        this.annexbBuffer = this.annexbBuffer.slice(first.index);
        continue;
      }
      const second = findStartCode(this.annexbBuffer, first.length);
      if (!second) {
        break;
      }
      nals.push(this.annexbBuffer.slice(0, second.index));
      this.annexbBuffer = this.annexbBuffer.slice(second.index);
    }
    return nals;
  }

  async flushAccessUnit(nalUnits) {
    if (!nalUnits.length) {
      return;
    }
    let metadata = null;
    let codec = null;
    let isKey = false;
    nalUnits.forEach((nalUnit) => {
      const nalType = getNalType(nalUnit);
      if (nalType === 7 && !codec) {
        codec = getCodecFromSps(nalUnit);
      }
      if (nalType === 6 && !metadata) {
        metadata = extractSeiMetadata(nalUnit);
      }
      if (nalType === 5) {
        isKey = true;
      }
    });
    if (!codec && !this.decoderConfigured) {
      return;
    }
    if (codec) {
      this.configureDecoderIfNeeded(codec);
    }
    if (!this.decoderConfigured) {
      return;
    }
    const timestamp = metadata
      ? Math.round(Number(metadata.pts || 0) * 1_000_000)
      : this.syntheticTimestampUs;
    this.syntheticTimestampUs = timestamp + Math.round(1_000_000 / Math.max(this.defaultFps, 1));
    this.streamMetadataByTimestamp.set(timestamp, metadata);
    const chunkData = concatArrays(nalUnits);
    this.decoder.decode(new EncodedVideoChunk({
      type: isKey ? 'key' : 'delta',
      timestamp,
      data: chunkData,
    }));
  }

  handleDecodedFrame(frame) {
    if (this.canvas.width !== frame.displayWidth || this.canvas.height !== frame.displayHeight) {
      this.canvas.width = frame.displayWidth;
      this.canvas.height = frame.displayHeight;
    }
    this.ctx.drawImage(frame, 0, 0, this.canvas.width, this.canvas.height);
    const metadata = this.streamMetadataByTimestamp.get(frame.timestamp) || null;
    this.onFrame(frame, metadata, frame.timestamp);
    frame.close();
  }

  async consume(sessionId) {
    const response = await fetch(this.streamUrl, {
      cache: 'no-store',
      signal: this.abortController ? this.abortController.signal : undefined,
    });
    if (!response.ok || !response.body) {
      throw new Error(`stream request failed: ${response.status}`);
    }
    const reader = response.body.getReader();
    while (sessionId === activeSessionId) {
      const { value, done } = await reader.read();
      if (done) {
        if (this.currentAccessUnit.length) {
          await this.flushAccessUnit(this.currentAccessUnit);
          this.currentAccessUnit = [];
        }
        break;
      }
      this.annexbBuffer = concatArrays([this.annexbBuffer, value]);
      const nalUnits = this.extractNals();
      for (const nalUnit of nalUnits) {
        const nalType = getNalType(nalUnit);
        if (nalType === 9 && this.currentAccessUnit.length) {
          await this.flushAccessUnit(this.currentAccessUnit);
          this.currentAccessUnit = [];
        }
        this.currentAccessUnit.push(nalUnit);
      }
    }
  }
}

function stopWebSocket() {
  if (ws) {
    ws.close();
    ws = null;
  }
}

function stopPlayers() {
  if (rawPlayer) {
    rawPlayer.close();
    rawPlayer = null;
  }
  if (overlayPlayer) {
    overlayPlayer.close();
    overlayPlayer = null;
  }
  playerRenderState = new Map();
  activeShotFx = null;
}

function connectWebSocket(sessionId) {
  if (!runtimeConfig.ws_url) {
    renderPairs(overlayRoot, { error: '当前实例未启用 WebSocket 模式' });
    return;
  }
  stopWebSocket();
  ws = new WebSocket(runtimeConfig.ws_url);
  ws.onmessage = (event) => {
    if (sessionId !== activeSessionId) {
      return;
    }
    const payload = JSON.parse(event.data);
    if (payload.type === 'heartbeat') {
      return;
    }
    rememberWsMetadata(payload);
  };
}

async function refreshPanels() {
  const metricsResp = await fetch('/api/metrics', { cache: 'no-store' });
  const overlayResp = await fetch('/api/overlay', { cache: 'no-store' });
  const runtimeResp = await fetch('/api/runtime', { cache: 'no-store' });
  const metrics = await metricsResp.json();
  const overlay = await overlayResp.json();
  const runtime = await runtimeResp.json();
  renderPairs(metricsRoot, metrics);
  renderPairs(overlayRoot, {
    ...overlay,
    source_rtmp: runtime.source_rtmp_url || 'n/a',
    analysis_rtmp: runtime.analysis_rtmp_url || 'n/a',
    ball_detector: runtime.ball_detector || 'yolo',
    effect: getSelectedEffect(),
  });
}

async function loadRuntimeConfig() {
  const response = await fetch('/api/runtime', { cache: 'no-store' });
  runtimeConfig = await response.json();
  configureModeOptions();
  configureBallDetectorOptions();
}

async function switchBallDetector() {
  if (!runtimeConfig || !ballDetectorSelect) {
    return;
  }
  const response = await fetch('/api/runtime', {
    method: 'POST',
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      ball_detector: ballDetectorSelect.value,
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || '切换球检测器失败');
  }
  runtimeConfig = payload;
  configureModeOptions();
  configureBallDetectorOptions();
}

async function startPlayback() {
  if (!('VideoDecoder' in window)) {
    renderPairs(overlayRoot, { error: '当前浏览器不支持 WebCodecs VideoDecoder' });
    return;
  }

  activeSessionId += 1;
  const sessionId = activeSessionId;
  wsMetadataByFrameId = new Map();
  stopWebSocket();
  stopPlayers();

  rawPlayer = new StreamPlayer(
    rawCanvas,
    rawCtx,
    runtimeConfig.raw_stream_url,
    () => {},
    Number(runtimeConfig.fps || 25),
  );
  overlayPlayer = new StreamPlayer(
    overlayCanvas,
    overlayCtx,
    runtimeConfig.analysis_stream_url,
    (_frame, metadata, timestamp) => {
      const overlayMetadata = getSelectedMode() === 'websocket'
        ? findWsMetadata(metadata, timestamp)
        : metadata;
      drawOverlay(overlayCtx, overlayCanvas, overlayMetadata);
    },
    Number(runtimeConfig.fps || 25),
  );

  rawPlayer.reset();
  overlayPlayer.reset();

  if (getSelectedMode() === 'websocket') {
    connectWebSocket(sessionId);
  }

  rawPlayer.consume(sessionId).catch((error) => {
    if (sessionId !== activeSessionId || error.name === 'AbortError') {
      return;
    }
    console.error(error);
    renderPairs(overlayRoot, { error: `原始流异常: ${String(error)}` });
  });

  overlayPlayer.consume(sessionId).catch((error) => {
    if (sessionId !== activeSessionId || error.name === 'AbortError') {
      return;
    }
    console.error(error);
    renderPairs(overlayRoot, { error: `分析流异常: ${String(error)}` });
  });
}

modeSelect.addEventListener('change', () => {
  if (!runtimeConfig) {
    return;
  }
  startPlayback();
});

if (ballDetectorSelect) {
  ballDetectorSelect.addEventListener('change', async () => {
    try {
      await switchBallDetector();
      await startPlayback();
      await refreshPanels();
    } catch (error) {
      console.error(error);
      renderPairs(overlayRoot, { error: `切换球检测失败: ${String(error)}` });
      await loadRuntimeConfig();
      await refreshPanels();
    }
  });
}

if (effectSelect) {
  effectSelect.addEventListener('change', refreshPanels);
}

loadRuntimeConfig().then(() => startPlayback());
refreshPanels();
setInterval(refreshPanels, 500);

const SHOT_TYPE_LABELS = {
  forehand: '正手',
  backhand: '反手',
  volley: '截击',
  serve: '发球',
  overhead: '高压',
  unknown: '其他',
};

function renderRallyStats(data) {
  if (!data || !rallyStatsRoot) return;
  const rs = data.rally_stats || {};
  renderPairs(rallyStatsRoot, {
    '总回合数': rs.total_rallies || 0,
    '最长回合': (rs.max_rally_length || 0) + ' 拍',
    '平均回合': (rs.avg_rally_length || 0) + ' 拍',
    '当前回合': (rs.current_rally_length || 0) + ' 拍',
    'P1 赢回合': (rs.wins_by_player || {})['1'] || 0,
    'P2 赢回合': (rs.wins_by_player || {})['2'] || 0,
  });
}

function renderShotDistribution(data) {
  if (!data || !shotDistRoot) return;
  const dist = data.shot_distribution || {};
  const allTypes = new Set();
  Object.values(dist).forEach((player) => Object.keys(player).forEach((t) => allTypes.add(t)));
  allTypes.delete('total');

  let html = '';
  allTypes.forEach((shotType) => {
    const p1Count = (dist['1'] || {})[shotType] || 0;
    const p2Count = (dist['2'] || {})[shotType] || 0;
    const maxCount = Math.max(p1Count, p2Count, 1);
    const label = SHOT_TYPE_LABELS[shotType] || shotType;
    html += `<div class="shot-bar-row">
      <span class="shot-bar-label">${label}</span>
      <div class="shot-bar-track"><div class="shot-bar-fill p1-bar" style="width:${(p1Count / maxCount * 100).toFixed(1)}%"></div></div>
      <span class="shot-bar-value">${p1Count}</span>
      <div class="shot-bar-track"><div class="shot-bar-fill p2-bar" style="width:${(p2Count / maxCount * 100).toFixed(1)}%"></div></div>
      <span class="shot-bar-value">${p2Count}</span>
    </div>`;
  });
  if (html) {
    html = '<div style="display:flex;justify-content:space-between;font-size:11px;color:#89a3c7;margin-bottom:4px"><span></span><span>P1</span><span></span><span>P2</span><span></span></div>' + html;
  }
  shotDistRoot.innerHTML = html || '<div style="color:#89a3c7;font-size:12px">等待数据...</div>';
}

function renderHeatmap(data) {
  if (!data || !heatmapCanvas || !heatmapCtx) return;
  const hm = data.player_heatmap || {};
  const width = heatmapCanvas.width;
  const height = heatmapCanvas.height;
  const halfH = height / 2;

  heatmapCtx.clearRect(0, 0, width, height);
  heatmapCtx.fillStyle = '#0b1220';
  heatmapCtx.fillRect(0, 0, width, height);

  heatmapCtx.strokeStyle = '#3a5070';
  heatmapCtx.lineWidth = 2;
  heatmapCtx.beginPath();
  heatmapCtx.moveTo(0, halfH);
  heatmapCtx.lineTo(width, halfH);
  heatmapCtx.stroke();

  const courtMargin = 6;
  heatmapCtx.strokeStyle = '#25324a';
  heatmapCtx.lineWidth = 1;
  [courtMargin, halfH - courtMargin, halfH + courtMargin, height - courtMargin].forEach((y) => {
    heatmapCtx.beginPath();
    heatmapCtx.moveTo(courtMargin, y);
    heatmapCtx.lineTo(width - courtMargin, y);
    heatmapCtx.stroke();
  });
  [courtMargin, width / 3, (width * 2) / 3, width - courtMargin].forEach((x) => {
    heatmapCtx.beginPath();
    heatmapCtx.moveTo(x, courtMargin);
    heatmapCtx.lineTo(x, height - courtMargin);
    heatmapCtx.stroke();
  });

  const playerColors = {
    '1': { r: 255, g: 216, b: 107 },
    '2': { r: 138, g: 214, b: 255 },
  };

  Object.entries(hm).forEach(([playerId, playerData]) => {
    const grid = playerData.grid;
    const size = playerData.size || 10;
    const maxVal = playerData.max || 1;
    const color = playerColors[playerId] || { r: 200, g: 200, b: 200 };
    const isP1 = playerId === '1';
    const halfSize = Math.ceil(size / 2);

    for (let row = 0; row < size; row++) {
      for (let col = 0; col < size; col++) {
        const val = (grid[row] || [])[col] || 0;
        if (val === 0) continue;

        const isInPlayerHalf = isP1 ? (row < halfSize) : (row >= halfSize);
        if (!isInPlayerHalf) continue;

        const intensity = Math.min(val / maxVal, 1.0);
        const alpha = 0.2 + intensity * 0.7;
        heatmapCtx.fillStyle = `rgba(${color.r},${color.g},${color.b},${alpha.toFixed(2)})`;

        const cellW = (width - 2 * courtMargin) / size;
        const cellH = (halfH - 2 * courtMargin) / halfSize;
        let drawX = courtMargin + col * cellW;
        let drawY;
        if (isP1) {
          drawY = courtMargin + row * cellH;
        } else {
          drawY = halfH + courtMargin + (row - halfSize) * cellH;
        }
        heatmapCtx.fillRect(drawX, drawY, cellW, cellH);
      }
    }
  });

  heatmapCtx.fillStyle = '#ffd86b';
  heatmapCtx.font = 'bold 11px Arial';
  heatmapCtx.textAlign = 'center';
  heatmapCtx.fillText('P1', width / 2, courtMargin + 12);

  heatmapCtx.fillStyle = '#8ad6ff';
  heatmapCtx.fillText('P2', width / 2, height - courtMargin - 4);

  heatmapCtx.fillStyle = '#5a7a9a';
  heatmapCtx.font = '9px Arial';
  heatmapCtx.fillText('NET', width / 2, halfH - 3);
}

function renderLandingZones(data) {
  if (!data || !landingZonesRoot) return;
  const zones = data.landing_zones || {};
  const allZoneKeys = new Set();
  Object.values(zones).forEach((player) => Object.keys(player).forEach((z) => allZoneKeys.add(z)));
  allZoneKeys.delete('total');

  let html = '';
  const sortedZones = Array.from(allZoneKeys).sort();
  sortedZones.forEach((zone) => {
    const p1Count = (zones['1'] || {})[zone] || 0;
    const p2Count = (zones['2'] || {})[zone] || 0;
    const maxCount = Math.max(p1Count, p2Count, 1);
    html += `<div class="zone-bar-row">
      <span class="zone-bar-label">${zone}</span>
      <div class="zone-bar-track"><div class="zone-bar-fill p1-bar" style="width:${(p1Count / maxCount * 100).toFixed(1)}%"></div></div>
      <span class="zone-bar-value">${p1Count}</span>
      <div class="zone-bar-track"><div class="zone-bar-fill p2-bar" style="width:${(p2Count / maxCount * 100).toFixed(1)}%"></div></div>
      <span class="zone-bar-value">${p2Count}</span>
    </div>`;
  });
  if (html) {
    html = '<div style="display:flex;justify-content:space-between;font-size:11px;color:#89a3c7;margin-bottom:4px"><span></span><span>P1</span><span></span><span>P2</span><span></span></div>' + html;
  }
  landingZonesRoot.innerHTML = html || '<div style="color:#89a3c7;font-size:12px">等待数据...</div>';
}

function renderNetApproach(data) {
  if (!data || !netApproachRoot) return;
  const na = data.net_approach || {};
  const p1 = na['1'] || {};
  const p2 = na['2'] || {};
  renderPairs(netApproachRoot, {
    'P1 上网次数': p1.attempts || 0,
    'P1 上网得分': p1.wins || 0,
    'P1 上网得分率': ((p1.win_rate || 0) * 100).toFixed(0) + '%',
    'P2 上网次数': p2.attempts || 0,
    'P2 上网得分': p2.wins || 0,
    'P2 上网得分率': ((p2.win_rate || 0) * 100).toFixed(0) + '%',
  });
}

function renderSpeedStats(data) {
  if (!data || !speedStatsRoot) return;
  const speeds = data.speed_by_shot_type || {};
  const rows = {};
  Object.entries(speeds).forEach(([playerId, typeSpeeds]) => {
    const label = playerId === '1' ? 'P1' : 'P2';
    Object.entries(typeSpeeds).forEach(([shotType, stats]) => {
      const typeLabel = SHOT_TYPE_LABELS[shotType] || shotType;
      rows[`${label} ${typeLabel} 均速`] = (stats.avg || 0).toFixed(1) + ' km/h';
      rows[`${label} ${typeLabel} 最快`] = (stats.max || 0).toFixed(1) + ' km/h';
    });
  });
  if (Object.keys(rows).length === 0) {
    rows['等待数据'] = '';
  }
  renderPairs(speedStatsRoot, rows);
}

async function refreshTacticalPanel() {
  try {
    const resp = await fetch('/api/tactical', { cache: 'no-store' });
    const data = await resp.json();
    if (!data || !Object.keys(data).length) return;
    renderRallyStats(data);
    renderShotDistribution(data);
    renderHeatmap(data);
    renderLandingZones(data);
    renderNetApproach(data);
    renderSpeedStats(data);
  } catch (e) {
    // ignore
  }
}

setInterval(refreshTacticalPanel, 1000);

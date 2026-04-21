const rawCanvas = document.getElementById('raw-canvas');
const rawCtx = rawCanvas.getContext('2d');
const overlayCanvas = document.getElementById('overlay-canvas');
const overlayCtx = overlayCanvas.getContext('2d');
const modeSelect = document.getElementById('mode-select');
const effectSelect = document.getElementById('effect-select');
const overlayRoot = document.getElementById('overlay-status');
const metricsRoot = document.getElementById('metrics');

const SEI_UUID_HEX = '7ce15f8687544f0fa4cfc9a0ab12f65b';

let ws = null;
let runtimeConfig = null;
let activeSessionId = 0;
let wsMetadataByFrameId = new Map();
let rawPlayer = null;
let overlayPlayer = null;
let activeShotFx = null;

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

function drawArcadeTrail(ctx, points, boost = 0) {
  if (points.length < 2) {
    return;
  }
  ctx.save();
  points.forEach((point, index) => {
    const alpha = (index + 1) / points.length;
    const hue = 20 + alpha * 70;
    ctx.fillStyle = `hsla(${hue}, 100%, 60%, ${0.16 + alpha * 0.42})`;
    ctx.beginPath();
    ctx.arc(point[0], point[1], 4 + alpha * 9 + boost * 3, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.setLineDash([8, 10]);
  ctx.lineCap = 'round';
  ctx.shadowBlur = 16 + boost * 8;
  ctx.shadowColor = 'rgba(255, 120, 0, 0.36)';
  ctx.strokeStyle = `rgba(255, 210, 0, ${0.35 + boost * 0.15})`;
  ctx.lineWidth = 6 + boost * 3;
  traceSmoothTrail(ctx, points);
  ctx.stroke();
  ctx.restore();
}

function drawImpactTrail(ctx, points, boost = 0) {
  if (points.length < 2) {
    return;
  }
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.shadowBlur = 26 + boost * 12;
  ctx.shadowColor = 'rgba(255, 90, 0, 0.5)';
  ctx.strokeStyle = `rgba(255, 80, 0, ${0.24 + boost * 0.18})`;
  ctx.lineWidth = 22 + boost * 8;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  ctx.shadowBlur = 14 + boost * 6;
  ctx.shadowColor = 'rgba(255, 220, 120, 0.38)';
  ctx.strokeStyle = `rgba(255, 196, 64, ${0.48 + boost * 0.2})`;
  ctx.lineWidth = 10 + boost * 4;
  traceSmoothTrail(ctx, points);
  ctx.stroke();

  ctx.restore();
}

function drawTrailByEffect(ctx, points, effect, boost = 0) {
  if (effect === 'comet') {
    drawCometTrail(ctx, points, boost);
    return;
  }
  if (effect === 'arcade') {
    drawArcadeTrail(ctx, points, boost);
    return;
  }
  if (effect === 'impact') {
    drawImpactTrail(ctx, points, boost);
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
  if (ageMs >= 320) {
    activeShotFx = null;
    return 0;
  }
  return 1 - ageMs / 320;
}

function drawShotBurst(ctx, effect, boost) {
  if (!activeShotFx || boost <= 0) {
    return;
  }
  const radiusBase = 34 + boost * 42;
  const angleStep = effect === 'arcade' ? 6 : 8;
  ctx.save();
  ctx.translate(activeShotFx.x, activeShotFx.y);
  ctx.globalCompositeOperation = 'screen';
  ctx.strokeStyle = effect === 'comet' ? `rgba(178, 236, 255, ${0.45 + boost * 0.4})` : `rgba(255, 200, 90, ${0.52 + boost * 0.36})`;
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
  ctx.fillStyle = `rgba(255, 245, 210, ${0.18 + boost * 0.35})`;
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
  Object.entries(playerBoxes).forEach(([playerId, box]) => {
    const normalized = normalizeBox(box);
    if (!normalized) {
      return;
    }
    const [x1, y1, x2, y2] = normalized;
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

  const ballBox = normalizeBox(metadata.ball_box);
  const ballTrail = normalizeTrail(metadata.ball_trail);
  const effect = getSelectedEffect();
  markShotEffect(metadata, ballBox, ballTrail);
  const shotBoost = getShotBoost();
  if (ballTrail.length >= 2) {
    drawTrailByEffect(ctx, ballTrail, effect, shotBoost);
  }

  if (ballBox) {
    const [x1, y1, x2, y2] = ballBox;
    const centerX = (x1 + x2) / 2;
    const centerY = (y1 + y2) / 2;
    const radius = Math.max((x2 - x1) / 2, 6);
    ctx.fillStyle = `rgba(255, 140, 0, ${0.35 + shotBoost * 0.18})`;
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius + 8 + shotBoost * 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = effect === 'comet' ? '#c9f3ff' : '#ffde59';
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
    effect: getSelectedEffect(),
  });
}

async function loadRuntimeConfig() {
  const response = await fetch('/api/runtime', { cache: 'no-store' });
  runtimeConfig = await response.json();
  configureModeOptions();
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

if (effectSelect) {
  effectSelect.addEventListener('change', refreshPanels);
}

loadRuntimeConfig().then(() => startPlayback());
refreshPanels();
setInterval(refreshPanels, 500);

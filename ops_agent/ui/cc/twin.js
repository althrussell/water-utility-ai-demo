// Baroon Pocket Dam digital twin (Lake Baroon). Loaded on demand by cc.js.
// Terrain: public elevation (AWS Terrain Tiles). Lake bed, structures and buoy positions are illustrative.
// Data (level, buoys, depth profile, offtakes) comes from governed Unity Catalog tables via /api/seqwater/twin.
import * as THREE from "./vendor/three.module.min.js";
import { OrbitControls } from "./vendor/OrbitControls.js";

const U = 10;          // metres per world unit
const EXAG = 1.8;      // vertical exaggeration
const BASE = 150;      // elevation subtracted before scaling (m)
const SEQ = [          // brand sequential orange (Oat -> Lava) keyed by log10(cells/mL); the water stays visible under it
  [3.3, [255, 221, 216, 0]], [4.0, [255, 221, 216, 0.18]], [4.5, [255, 184, 173, 0.30]],
  [4.8, [255, 148, 130, 0.42]], [5.0, [255, 92, 61, 0.52]], [5.2, [255, 54, 33, 0.62]],
];

const fmt = (v, d = 0) => (v == null || isNaN(v) ? "–" : Number(v).toLocaleString("en-AU", { maximumFractionDigits: d, minimumFractionDigits: d }));
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const dayLabel = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short" });

// smooth value noise so the bloom reads as drifting surface scum rather than a flat wash
function noise2(x, y) {
  const h = (i, j) => { const n = Math.sin(i * 127.1 + j * 311.7) * 43758.5453; return n - Math.floor(n); };
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = h(xi, yi), b = h(xi + 1, yi), c = h(xi, yi + 1), d = h(xi + 1, yi + 1);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
function fbm(x, y) { return 0.55 * noise2(x, y) + 0.3 * noise2(x * 2.1, y * 2.1) + 0.15 * noise2(x * 4.3, y * 4.3); }

function rampColour(cells) {
  const x = Math.log10(Math.max(cells, 1));
  if (x <= SEQ[0][0]) return [0, 0, 0, 0];
  for (let i = 1; i < SEQ.length; i++) {
    if (x <= SEQ[i][0]) {
      const [x0, c0] = SEQ[i - 1], [x1, c1] = SEQ[i], t = (x - x0) / (x1 - x0);
      return c0.map((v, k) => v + (c1[k] - v) * t);
    }
  }
  return SEQ[SEQ.length - 1][1];
}

export async function mountTwin(root, { onAsk, onSelectBuoy } = {}) {
  const [meta, terrainBuf, lakeBuf] = await Promise.all([
    fetch("/cc-assets/twin/baroon-meta.json").then((r) => r.json()),
    fetch("/cc-assets/twin/baroon-terrain.bin").then((r) => r.arrayBuffer()),
    fetch("/cc-assets/twin/baroon-lake.bin").then((r) => r.arrayBuffer()),
  ]);
  const N = meta.grid.width;
  const cell = meta.grid.cell_m;
  const elev = new Uint16Array(terrainBuf);
  const lake = new Uint8Array(lakeBuf);
  const heightAt = (r, c) => elev[Math.max(0, Math.min(N - 1, Math.round(r))) * N + Math.max(0, Math.min(N - 1, Math.round(c)))] * meta.grid.elevation_scale;
  const W = (N * cell) / U;
  const toWorld = (r, c, h) => new THREE.Vector3((c / N - 0.5) * W, ((h - BASE) / U) * EXAG, (r / N - 0.5) * W);
  const toRC = ([lat, lon]) => [
    ((lat - meta.bbox.north) / (meta.bbox.south - meta.bbox.north)) * N - 0.5,
    ((lon - meta.bbox.west) / (meta.bbox.east - meta.bbox.west)) * N - 0.5,
  ];

  const state = { data: null, day: null, days: [], selected: "BPD-B1", showBloom: true, level: meta.full_supply_level_m };
  const stage = root.querySelector(".twin-stage");
  const canvas = root.querySelector("#twin-canvas");
  const labels = root.querySelector("#twin-labels");

  // ---------------------------------------------------------------- scene
  let gl = true;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  } catch {
    gl = false;
  }
  if (!gl || !renderer) {
    root.querySelector(".twin-stage").classList.add("no-webgl");
    root.querySelector(".twin-fallback").hidden = false;
    return { refresh: async () => {}, dispose: () => {} };
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#F9F7F4");
  scene.fog = new THREE.Fog("#F9F7F4", 420, 980);
  const camera = new THREE.PerspectiveCamera(32, 1, 1, 4000);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 90;
  controls.maxDistance = 900;
  controls.maxPolarAngle = 1.32;
  controls.screenSpacePanning = false;

  scene.add(new THREE.HemisphereLight(0xf9f7f4, 0x1b5162, 1.9));
  const sun = new THREE.DirectionalLight(0xfffaf0, 2.1);
  sun.position.set(-260, 420, -180);
  scene.add(sun);

  // terrain: 256 x 256 segments sampled from the 512 grid, draped with the baked colour image
  const SEG = 255;
  const tgeo = new THREE.PlaneGeometry(W, W, SEG, SEG);
  tgeo.rotateX(-Math.PI / 2);
  const pos = tgeo.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const c = ((pos.getX(i) / W) + 0.5) * (N - 1);
    const r = ((pos.getZ(i) / W) + 0.5) * (N - 1);
    pos.setY(i, ((heightAt(r, c) - BASE) / U) * EXAG);
  }
  tgeo.computeVertexNormals();
  const loader = new THREE.TextureLoader();
  const drape = await loader.loadAsync("/cc-assets/twin/baroon-drape.webp");
  drape.colorSpace = THREE.SRGBColorSpace;
  drape.anisotropy = renderer.capabilities.getMaxAnisotropy();
  scene.add(new THREE.Mesh(tgeo, new THREE.MeshStandardMaterial({ map: drape, roughness: 0.96, metalness: 0 })));

  // lake extent (bounding box of the basin) for the water and bloom planes
  let r0 = N, r1 = 0, c0 = N, c1 = 0;
  for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) if (lake[r * N + c]) { r0 = Math.min(r0, r); r1 = Math.max(r1, r); c0 = Math.min(c0, c); c1 = Math.max(c1, c); }
  r0 -= 2; c0 -= 2; r1 += 2; c1 += 2;
  const lw = c1 - c0 + 1, lh = r1 - r0 + 1;
  const centre = toWorld((r0 + r1) / 2, (c0 + c1) / 2, meta.full_supply_level_m);

  const maskCanvas = document.createElement("canvas");
  maskCanvas.width = lw; maskCanvas.height = lh;
  const maskTex = new THREE.CanvasTexture(maskCanvas);
  const waterTex = await loader.loadAsync("/cc-assets/img/tex-water.webp");
  waterTex.wrapS = waterTex.wrapT = THREE.RepeatWrapping;
  waterTex.repeat.set(lw / 48, lh / 48);
  waterTex.colorSpace = THREE.SRGBColorSpace;
  const waterGeo = new THREE.PlaneGeometry((lw * cell) / U, (lh * cell) / U);
  waterGeo.rotateX(-Math.PI / 2);
  const water = new THREE.Mesh(waterGeo, new THREE.MeshStandardMaterial({
    map: waterTex, color: 0x9fc4cf, roughness: 0.22, metalness: 0.15, transparent: true, opacity: 0.94, alphaMap: maskTex, depthWrite: false,
  }));
  water.position.set(((c0 + c1) / 2 / N - 0.5) * W, 0, ((r0 + r1) / 2 / N - 0.5) * W);
  scene.add(water);

  const bloomCanvas = document.createElement("canvas");
  bloomCanvas.width = lw; bloomCanvas.height = lh;
  const bloomTex = new THREE.CanvasTexture(bloomCanvas);
  bloomTex.colorSpace = THREE.SRGBColorSpace;
  const bloom = new THREE.Mesh(waterGeo.clone(), new THREE.MeshBasicMaterial({ map: bloomTex, transparent: true, depthWrite: false }));
  bloom.position.copy(water.position);
  scene.add(bloom);

  // structures
  const f = meta.features;
  const concrete = new THREE.MeshStandardMaterial({ color: 0xc9ced3, roughness: 0.85 });
  const navy = new THREE.MeshStandardMaterial({ color: 0x0b2026, roughness: 0.6 });
  const lava = new THREE.MeshStandardMaterial({ color: 0xff3621, emissive: 0xff3621, emissiveIntensity: 0.35, roughness: 0.5 });
  const [dr, dc] = f.dam_wall.rc;
  const ax = f.dam_wall.axis[1], az = f.dam_wall.axis[0];   // world x, z of the dam -> deep-water direction
  const px = -az, pz = ax;                                    // wall runs perpendicular
  const bedAtDam = Math.min(heightAt(dr + az * 6, dc + ax * 6), meta.full_supply_level_m - 30);
  const crest = f.dam_wall.crest_m;
  const wallH = ((crest - bedAtDam) / U) * EXAG;
  const wall = new THREE.Mesh(new THREE.BoxGeometry(f.dam_wall.crest_length_m / U, wallH, 2.4), concrete);
  const wp = toWorld(dr, dc, bedAtDam);
  wall.position.set(wp.x, wp.y + wallH / 2, wp.z);
  wall.rotation.y = Math.atan2(-pz, px);
  scene.add(wall);

  const [sr, sc] = f.spillway.rc;
  const spill = new THREE.Mesh(new THREE.BoxGeometry(2.2, 0.6, 14), concrete);
  const sp = toWorld(sr, sc, meta.full_supply_level_m - 1);
  spill.position.set(sp.x - ax * 6, sp.y, sp.z - az * 6);
  spill.rotation.y = Math.atan2(-az, ax) + Math.PI / 2;
  scene.add(spill);

  const [ir, ic] = f.intake.rc;
  const bedAtIntake = Math.min(heightAt(ir, ic), meta.offtakes.Lower - 6);
  const towerH = ((crest + 6 - bedAtIntake) / U) * EXAG;
  const tower = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 1.1, towerH, 20), concrete);
  const tp = toWorld(ir, ic, bedAtIntake);
  tower.position.set(tp.x, tp.y + towerH / 2, tp.z);
  scene.add(tower);
  const bridge = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.25, 14), concrete);
  bridge.position.set(tp.x - ax * 7, ((crest - BASE) / U) * EXAG, tp.z - az * 7);
  bridge.rotation.y = Math.atan2(-az, ax) + Math.PI / 2;
  scene.add(bridge);
  const rings = {};
  for (const [lv, elevM] of Object.entries(meta.offtakes)) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(1.25, 0.22, 10, 28), navy);
    ring.rotation.x = Math.PI / 2;
    ring.position.set(tp.x, ((elevM - BASE) / U) * EXAG, tp.z);
    scene.add(ring);
    rings[lv] = ring;
  }

  // pipeline to Landers Shute: follows the terrain along its bearing from the intake
  const brg = (meta.pipeline.bearing_deg * Math.PI) / 180;
  const pts = [];
  for (let k = 0; k <= 60; k++) {
    const r = ir - Math.cos(brg) * k * 2.6, c = ic + Math.sin(brg) * k * 2.6;
    if (r < 2 || c > N - 3) break;
    const h = Math.max(heightAt(r, c), k < 6 ? crest : 0) + 3;
    pts.push(toWorld(r, c, h));
  }
  const pipe = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 120, 0.45, 8, false), navy);
  scene.add(pipe);
  const pipeEnd = pts[pts.length - 1];

  // ---------------------------------------------------------------- labels (DOM, so text stays crisp and accessible)
  const labelItems = [];
  const addLabel = (vec, node) => { labels.append(node); labelItems.push({ vec, node }); return node; };
  const tag = (text, cls = "twin-tag") => el("span", cls, text);
  addLabel(new THREE.Vector3(wp.x, wp.y + wallH + 3, wp.z), tag("Dam wall"));
  addLabel(new THREE.Vector3(sp.x - ax * 12, sp.y + 2, sp.z - az * 12), tag("Spillway"));
  const intakeTag = addLabel(new THREE.Vector3(tp.x, tp.y + towerH + 1, tp.z), tag("Intake tower"));
  addLabel(pipeEnd.clone().add(new THREE.Vector3(0, 4, 0)), tag("To Landers Shute WTP →"));
  const buoyNodes = {};

  // project labels and nudge any that overlap an earlier one upward (buoy pins keep their place)
  function project() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const placed = [];
    const items = [...labelItems].sort((a, b) => (b.pin ? 1 : 0) - (a.pin ? 1 : 0));
    for (const it of items) {
      const v = it.vec.clone().project(camera);
      const vis = v.z < 1 && v.x > -1.05 && v.x < 1.05 && v.y > -1.05 && v.y < 1.05;
      const bw = it.node.offsetWidth || 80, bh = it.node.offsetHeight || 22;
      let x = ((v.x + 1) / 2) * w - bw / 2, y = ((1 - v.y) / 2) * h - bh - 4;
      for (let k = 0; k < 6 && !it.pin; k++) {
        const hit = placed.find((b) => x < b.x + b.w && x + bw > b.x && y < b.y + b.h && y + bh > b.y);
        if (!hit) break;
        y = hit.y - bh - 4;
      }
      if (vis) placed.push({ x, y, w: bw, h: bh });
      it.node.style.transform = `translate(${x}px, ${y}px)`;
      it.node.style.visibility = vis ? "visible" : "hidden";
    }
  }

  let raf = 0, idle = 0;
  function render() {
    controls.update();
    renderer.render(scene, camera);
    project();
  }
  function loop() {
    const moved = controls.update();
    renderer.render(scene, camera);
    project();
    idle = moved ? 0 : idle + 1;
    raf = idle < 30 ? requestAnimationFrame(loop) : 0;
  }
  const kick = () => { idle = 0; if (!raf) raf = requestAnimationFrame(loop); };
  controls.addEventListener("change", kick);

  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    kick();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(stage);

  function resetView() {
    controls.target.set(centre.x, centre.y - 4, centre.z);
    camera.position.set(centre.x + 210, centre.y + 190, centre.z + 300);
    controls.update();
    kick();
  }

  // ---------------------------------------------------------------- data layers
  const levelOn = (day) => (state.data.level.find((l) => l.reading_date === day) || state.data.level[state.data.level.length - 1]);

  function drawWater(levelM) {
    const ctx = maskCanvas.getContext("2d");
    const img = ctx.createImageData(lw, lh);
    for (let y = 0; y < lh; y++) for (let x = 0; x < lw; x++) {
      const r = r0 + y, c = c0 + x;
      const on = r >= 0 && c >= 0 && r < N && c < N && lake[r * N + c] && heightAt(r, c) < levelM;
      const k = (y * lw + x) * 4;
      img.data[k] = img.data[k + 1] = img.data[k + 2] = on ? 255 : 0;
      img.data[k + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    maskTex.needsUpdate = true;
    const y = ((levelM - BASE) / U) * EXAG + 0.05;
    water.position.y = y;
    bloom.position.y = y + 0.08;
  }

  function drawBloom(day, levelM) {
    const ctx = bloomCanvas.getContext("2d");
    const img = ctx.createImageData(lw, lh);
    const rows = state.data.readings.filter((r) => r.reading_date === day);
    const pts = rows.map((r) => {
      const b = state.data.buoys.find((x) => x.buoy_id === r.buoy_id);
      const [br, bc] = toRC([Number(b.latitude), Number(b.longitude)]);
      return { r: br, c: bc, v: Math.log10(Math.max(Number(r.cyanobacteria_cells_ml), 1)) };
    });
    for (let y = 0; y < lh; y++) for (let x = 0; x < lw; x++) {
      const r = r0 + y, c = c0 + x;
      const k = (y * lw + x) * 4;
      if (!(r >= 0 && c >= 0 && r < N && c < N && lake[r * N + c] && heightAt(r, c) < levelM) || !state.showBloom) { img.data[k + 3] = 0; continue; }
      let num = 0, den = 0;
      for (const p of pts) { const d2 = (p.r - r) ** 2 + (p.c - c) ** 2 + 4; const w = 1 / (d2 * d2); num += w * p.v; den += w; }
      const col = rampColour(10 ** (num / den));
      const streak = fbm(c * 0.09 + r * 0.03, r * 0.05 - c * 0.02);    // stretched along the prevailing breeze
      const a = col[3] * Math.min(1.25, Math.max(0.25, (streak - 0.25) * 1.9));
      img.data[k] = col[0]; img.data[k + 1] = col[1]; img.data[k + 2] = col[2]; img.data[k + 3] = a * 255;
    }
    ctx.putImageData(img, 0, 0);
    bloomTex.needsUpdate = true;
  }

  function placeBuoys(levelM) {
    for (const b of state.data.buoys) {
      const [br, bc] = toRC([Number(b.latitude), Number(b.longitude)]);
      const vec = toWorld(br, bc, levelM).add(new THREE.Vector3(0, 1.2, 0));
      if (!buoyNodes[b.buoy_id]) {
        const btn = el("button", "twin-buoy-pin");
        btn.type = "button";
        btn.addEventListener("click", () => select(b.buoy_id));
        buoyNodes[b.buoy_id] = { node: addLabel(vec, btn), item: labelItems[labelItems.length - 1] };
        labelItems[labelItems.length - 1].pin = true;
      }
      buoyNodes[b.buoy_id].item.vec = vec;
    }
  }

  function updateBuoyPins(day) {
    for (const b of state.data.buoys) {
      const r = state.data.readings.find((x) => x.reading_date === day && x.buoy_id === b.buoy_id);
      const v = Number(r?.cyanobacteria_cells_ml);
      const btn = buoyNodes[b.buoy_id].node;
      btn.replaceChildren(el("img", null), el("span", null, `${b.buoy_id.replace("BPD-", "")} · ${v >= 1000 ? `${fmt(v / 1000)}k` : fmt(v)}`));
      btn.firstChild.src = "/cc-assets/img/icon-buoy.webp";
      btn.firstChild.alt = "";
      btn.setAttribute("aria-label", `${b.buoy_name}: ${fmt(v)} cyanobacteria cells per mL`);
      btn.setAttribute("aria-pressed", String(b.buoy_id === state.selected));
      btn.classList.toggle("alert", v >= 15000);
    }
  }

  function offtakeDepths(levelM) {
    return state.data.offtakes.map((o) => ({ ...o, depth: levelM - Number(o.centre_elevation_m) }));
  }

  function updateOfftakes(levelM) {
    const inService = state.data.offtakes.find((o) => o.in_service)?.offtake_level || "Upper";
    for (const [lv, ring] of Object.entries(rings)) ring.material = lv === inService ? lava : navy;
    intakeTag.textContent = `Intake · ${inService.toLowerCase()} offtake`;
    return inService;
  }

  // ---------------------------------------------------------------- side panels
  function renderHud(day) {
    const l = levelOn(day);
    const below = meta.full_supply_level_m - Number(l.water_level_m);
    const inService = state.data.offtakes.find((o) => o.in_service)?.offtake_level || "Upper";
    root.querySelector("#twin-hud").replaceChildren(
      hudItem("Water level", `${fmt(l.water_level_m, 1)} m`, `${fmt(below, 1)} m below full supply`),
      hudItem("Storage", `${fmt(l.percent_full, 1)}%`, `${fmt(l.volume_ml)} ML`),
      hudItem("Supplying Landers Shute", `${inService} offtake`, `${fmt(Number(l.water_level_m) - Number(meta.offtakes[inService]), 1)} m below the surface`),
    );
  }
  function hudItem(label, value, note) {
    const d = el("div", "hud-item");
    d.append(el("span", "hud-label", label), el("span", "hud-value", value), el("span", "hud-note", note));
    return d;
  }

  function renderBuoy(day) {
    const b = state.data.buoys.find((x) => x.buoy_id === state.selected);
    const series = state.data.readings.filter((r) => r.buoy_id === b.buoy_id);
    const i = series.findIndex((r) => r.reading_date === day);
    const at = (k) => series[Math.max(0, i - k)];
    const box = root.querySelector("#twin-buoy");
    const now = at(0), wk = at(7);
    const growth = Number(now.cyanobacteria_cells_ml) / Math.max(Number(wk.cyanobacteria_cells_ml), 1);
    const head = el("div", "twin-buoy-head");
    const ic = el("img"); ic.src = "/cc-assets/img/icon-buoy.webp"; ic.alt = "";
    const t = el("div");
    t.append(el("h3", null, b.buoy_name), el("p", "meta", `${b.buoy_id} · ${fmt(b.depth_at_full_supply_m)} m deep at full supply`));
    head.append(ic, t);
    const tbl = el("table", "twin-table");
    tbl.innerHTML = "<thead><tr><th></th><th>Today</th><th>3 days ago</th><th>7 days ago</th><th>14 days ago</th></tr></thead>";
    const tb = el("tbody");
    const row = (label, key, d = 0) => {
      const tr = el("tr");
      tr.append(el("th", null, label), ...[0, 3, 7, 14].map((k) => el("td", null, fmt(at(k)?.[key], d))));
      tb.append(tr);
    };
    row("Cyanobacteria (cells/mL)", "cyanobacteria_cells_ml");
    row("Geosmin (ng/L)", "geosmin_ng_l", 1);
    row("Surface temp (°C)", "surface_temp_c", 1);
    tbl.append(tb);
    const summary = el("p", "twin-summary");
    summary.innerHTML = "";
    const nowV = Number(now.cyanobacteria_cells_ml), wkV = Number(wk.cyanobacteria_cells_ml);
    summary.append(
      el("b", null, `${fmt(nowV)} cells/mL`),
      document.createTextNode(` at the surface, ${nowV >= 2000 ? `${fmt(nowV / 2000, 0)}× Alert Level 1` : "below Alert Level 1"}. ` +
        (growth >= 1.5 ? `A week ago it was ${fmt(wkV)}.` : growth < 0.9 ? `Falling: ${fmt(wkV)} a week ago.` : "About the same as a week ago.")),
    );
    const ask = el("button", "btn btn-secondary btn-sm", "Ask the agent about this buoy");
    ask.type = "button";
    ask.onclick = () => onAsk?.(`On Lake Baroon, what is happening at buoy ${b.buoy_id} (${b.buoy_name})? How fast is the bloom spreading toward the intake, and what should we do?`);
    box.replaceChildren(head, summary, tbl, ask);
  }

  function renderProfile(day, levelM) {
    const prof = state.data.profile.filter((p) => p.reading_date === day).map((p) => ({
      z: Number(p.depth_m), t: Number(p.water_temp_c), o: Number(p.dissolved_oxygen_mg_l), c: Number(p.cyanobacteria_cells_ml), m: Number(p.manganese_mg_l),
    }));
    const offs = offtakeDepths(levelM);
    const zmax = Math.max(...prof.map((p) => p.z), ...offs.map((o) => o.depth)) + 2;
    const cols = [
      { key: "t", label: "Temperature", unit: "°C", min: 16, max: 27, colour: "#0B2026" },
      { key: "o", label: "Oxygen", unit: "mg/L", min: 0, max: 10, colour: "#4462C9" },
      { key: "c", label: "Cyanobacteria", unit: "cells/mL (log)", min: 2, max: 5.3, colour: "#FF3621", log: true },
      { key: "m", label: "Manganese", unit: "mg/L", min: 0, max: 0.6, colour: "#4A5568", guide: 0.1 },
    ];
    const Wc = 118, H = 250, top = 36, left = 42, gap = 12;
    const width = left + cols.length * (Wc + gap);
    const y = (z) => top + (z / zmax) * (H - top - 8);
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${H}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Depth profile of Lake Baroon: temperature, oxygen, cyanobacteria and manganese by depth, with the three offtake levels");
    const add = (name, attrs, text) => { const n = document.createElementNS(ns, name); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); if (text != null) n.textContent = text; svg.append(n); return n; };
    for (let z = 0; z <= zmax; z += 10) {
      add("text", { x: left - 8, y: y(z) + 4, "text-anchor": "end", class: "ax" }, `${z} m`);
    }
    cols.forEach((col, i) => {
      const x0 = left + i * (Wc + gap);
      add("rect", { x: x0, y: top, width: Wc, height: H - top - 8, class: "col-bg" });
      add("text", { x: x0, y: 14, class: "col-title" }, col.label);
      add("text", { x: x0, y: 27, class: "ax" }, col.unit);
      const sx = (v) => x0 + ((((col.log ? Math.log10(Math.max(v, 1)) : v) - col.min) / (col.max - col.min)) * Wc);
      if (col.guide) add("line", { x1: sx(col.guide), x2: sx(col.guide), y1: top, y2: H - 8, class: "guide" });
      const d = prof.map((p, k) => `${k ? "L" : "M"}${Math.max(x0, Math.min(x0 + Wc, sx(p[col.key]))).toFixed(1)},${y(p.z).toFixed(1)}`).join(" ");
      add("path", { d, fill: "none", stroke: col.colour, "stroke-width": 2.2, "stroke-linejoin": "round" });
    });
    for (const o of offs) {
      const yy = y(o.depth);
      add("line", { x1: left - 4, x2: width - gap, y1: yy, y2: yy, class: `off ${o.in_service ? "in-service" : ""}` });
      add("text", { x: left + 2, y: yy - 4, class: `off-label ${o.in_service ? "in-service" : ""}` }, `${o.offtake_level} offtake · ${fmt(o.depth, 1)} m${o.in_service ? " · in service" : ""}`);
    }
    root.querySelector("#twin-profile-chart").replaceChildren(svg);

    // offtake comparison
    const near = (z) => prof.reduce((a, b) => (Math.abs(b.z - z) < Math.abs(a.z - z) ? b : a));
    const rows = offs.map((o) => ({ ...o, q: near(o.depth) }));
    const best = rows.filter((r) => r.q.m < 0.1).sort((a, b) => a.q.c - b.q.c)[0];
    const tbl = el("table", "twin-table");
    tbl.innerHTML = "<thead><tr><th>Offtake</th><th>Depth</th><th>Algae<br>cells/mL</th><th>Mn<br>mg/L</th><th>O₂<br>mg/L</th></tr></thead>";
    const tb = el("tbody");
    for (const r of rows) {
      const tr = el("tr");
      const status = r.in_service ? "In service" : r === best ? "Best quality" : r.q.m >= 0.1 ? "High manganese" : "";
      const name = el("th");
      name.append(el("span", null, r.offtake_level));
      if (status) name.append(el("span", `chip-state ${r.in_service ? "in-service" : r === best ? "best" : "warn"}`, status));
      tr.append(name, el("td", null, `${fmt(r.depth, 1)} m`), el("td", null, fmt(r.q.c)), el("td", null, fmt(r.q.m, 3)), el("td", null, fmt(r.q.o, 1)));
      tb.append(tr);
    }
    tbl.append(tb);
    const actions = el("div", "twin-actions");
    const cur = rows.find((r) => r.in_service);
    if (best && cur && best.offtake_level !== cur.offtake_level) {
      const cut = (1 - best.q.c / cur.q.c) * 100;
      const btn = el("button", "btn btn-secondary btn-sm", `Ask the agent to switch to the ${best.offtake_level.toLowerCase()} offtake`);
      btn.type = "button";
      btn.onclick = () => onAsk?.(`Switch Landers Shute WTP to the ${best.offtake_level} offtake at Baroon Pocket Dam. Check the depth profile first, then request the offtake change for my approval.`);
      actions.append(el("p", "meta", `The ${best.offtake_level.toLowerCase()} offtake would cut cyanobacteria reaching Landers Shute by about ${fmt(cut)}%, without drawing high-manganese water.`), btn);
    } else if (state.data.offtake_change) {
      const ch = state.data.offtake_change;
      actions.append(el("p", "twin-done", `${ch.level} offtake in service: change ${ch.reference_id} approved by ${ch.requested_by}.`));
    }
    root.querySelector("#twin-offtakes").replaceChildren(tbl, actions);
  }

  function select(id) {
    state.selected = id;
    updateBuoyPins(state.day);
    renderBuoy(state.day);
    onSelectBuoy?.(id);
  }

  function setDay(day) {
    state.day = day;
    const levelM = Number(levelOn(day).water_level_m);
    drawWater(levelM);
    drawBloom(day, levelM);
    placeBuoys(levelM);
    updateBuoyPins(day);
    updateOfftakes(levelM);
    renderHud(day);
    renderBuoy(day);
    renderProfile(day, levelM);
    const out = root.querySelector("#twin-day");
    out.textContent = day === state.days[state.days.length - 1] ? `${dayLabel(day)} · latest` : dayLabel(day);
    kick();
  }

  // ---------------------------------------------------------------- timeline + controls
  const slider = root.querySelector("#twin-slider");
  const play = root.querySelector("#twin-play");
  let timer = 0;
  slider.addEventListener("input", () => setDay(state.days[Number(slider.value)]));
  play.addEventListener("click", () => {
    if (timer) { clearInterval(timer); timer = 0; play.textContent = "Play"; return; }
    let i = Number(slider.value) >= state.days.length - 1 ? 0 : Number(slider.value);
    play.textContent = "Pause";
    timer = setInterval(() => {
      slider.value = String(i);
      setDay(state.days[i]);
      if (++i >= state.days.length) { clearInterval(timer); timer = 0; play.textContent = "Replay 14 days"; }
    }, 650);
  });
  root.querySelector("#twin-reset").addEventListener("click", resetView);
  root.querySelector("#twin-bloom").addEventListener("change", (e) => { state.showBloom = e.target.checked; setDay(state.day); });

  async function refresh(fresh = false) {
    const r = await fetch(`/api/seqwater/twin${fresh ? "?fresh=true" : ""}`, { credentials: "same-origin" });
    const data = await r.json();
    if (!r.ok || data.error) throw new Error(data.error || r.statusText);
    state.data = data;
    const all = [...new Set(data.readings.map((x) => x.reading_date))].sort();
    state.days = all.slice(-14);
    slider.max = String(state.days.length - 1);
    if (!state.day || !state.days.includes(state.day)) { slider.value = slider.max; state.day = state.days[state.days.length - 1]; }
    setDay(state.day);
  }

  resize();
  resetView();
  await refresh();
  root.querySelector(".twin-loading")?.remove();
  render();
  return {
    refresh,
    focusBuoy: select,
    dispose: () => { ro.disconnect(); cancelAnimationFrame(raf); renderer.dispose(); },
  };
}

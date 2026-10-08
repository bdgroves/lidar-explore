/* LiDAR Explore project page. Data comes from docs/data, written by
   build_web_data.py during the GitHub rebuild. Each section draws itself
   independently, so a missing file blanks only its own section. */
(function () {
  "use strict";
  var C = { bark: "#edefea", spruce: "#1e2b27", lichen: "#a9b5a0", moss: "#4f6e45",
            paint: "#e8642a", cold: "#3f6f8f", white: "#fbfcfa", plot: "#f4f5f1" };
  var reduceMotion = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function $(id) { return document.getElementById(id); }
  function getJSON(name) {
    return fetch("data/" + name, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(name + " " + r.status);
      return r.json();
    });
  }
  function fmt(x, d) { return x == null ? "–" : Number(x).toFixed(d == null ? 1 : d); }
  function setK(k, v) {
    document.querySelectorAll('[data-k="' + k + '"]').forEach(function (el) { el.textContent = v; });
  }
  function safe(name, fn) {
    return function () {
      try { return fn.apply(null, arguments); }
      catch (e) { console.error(name, e); }
    };
  }
  /* a crisp canvas at device resolution, drawn in CSS pixels */
  function prep(canvas, aspect) {
    var w = canvas.clientWidth || canvas.width, h = Math.round(w * aspect);
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    canvas.style.height = h + "px";
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, w: w, h: h };
  }
  var FONT = '500 12px Archivo, "Helvetica Neue", Arial, sans-serif';
  var FONTB = '700 12px Archivo, "Helvetica Neue", Arial, sans-serif';

  /* height ramp shared by the cloud: ground brown, through moss, to pale crown */
  var STOPS = [[0, [92, 78, 62]], [2, [110, 112, 80]], [8, [79, 110, 69]], [18, [118, 150, 92]],
               [28, [196, 206, 150]], [38, [244, 242, 214]]];
  function rampRGB(h) {
    if (h <= STOPS[0][0]) return STOPS[0][1];
    for (var i = 1; i < STOPS.length; i++) {
      if (h <= STOPS[i][0]) {
        var a = STOPS[i - 1], b = STOPS[i], t = (h - a[0]) / (b[0] - a[0]);
        return [a[1][0] + (b[1][0] - a[1][0]) * t, a[1][1] + (b[1][1] - a[1][1]) * t, a[1][2] + (b[1][2] - a[1][2]) * t];
      }
    }
    return STOPS[STOPS.length - 1][1];
  }

  /* ============================== hero cloud ============================== */
  var heroCloud = safe("cloud", function (syn) {
    var canvas = $("cloud"), load = $("cloud-load");
    if (!window.THREE) { load.textContent = "The 3D view needs WebGL and couldn't start here."; return; }
    var renderer;
    try { renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true }); }
    catch (e) { load.textContent = "The 3D view needs WebGL and couldn't start here."; return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

    return fetch("data/cloud.bin").then(function (r) { return r.arrayBuffer(); }).then(function (buf) {
      var n = syn.points_shown, u16 = new Uint16Array(buf, 0, n * 4), cls = new Uint8Array(buf, n * 8, n);
      var W = syn.extent_m[0], H = syn.extent_m[1];
      var pos = new Float32Array(n * 3), colH = new Float32Array(n * 3), colC = new Float32Array(n * 3);
      var zmin = 1e9;
      for (var i = 0; i < n; i++) zmin = Math.min(zmin, u16[i * 4 + 2] / 10);
      for (i = 0; i < n; i++) {
        var x = u16[i * 4] / 10 - W / 2, y = u16[i * 4 + 1] / 10 - H / 2, z = u16[i * 4 + 2] / 10 - zmin, hag = u16[i * 4 + 3] / 10;
        pos[i * 3] = x; pos[i * 3 + 1] = z; pos[i * 3 + 2] = -y;
        var c = rampRGB(cls[i] === 2 ? 0 : hag);
        colH[i * 3] = c[0] / 255; colH[i * 3 + 1] = c[1] / 255; colH[i * 3 + 2] = c[2] / 255;
        var g = cls[i] === 2 ? [0.62, 0.52, 0.40] : (cls[i] === 3 ? [0.55, 0.62, 0.42] : [0.36, 0.56, 0.36]);
        if (cls[i] >= 5) g = [0.30, 0.50, 0.32];
        colC[i * 3] = g[0]; colC[i * 3 + 1] = g[1]; colC[i * 3 + 2] = g[2];
      }
      var scene = new THREE.Scene();
      var geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      var colAttr = new THREE.BufferAttribute(colH.slice(), 3);
      geo.setAttribute("color", colAttr);
      var mat = new THREE.PointsMaterial({ size: 1.15, vertexColors: true, sizeAttenuation: true });
      scene.add(new THREE.Points(geo, mat));

      /* tree markers: the detected tops (hits pale, false alarms orange) and the missed trees (orange rings) */
      function sprite(kind) {
        var c = document.createElement("canvas"); c.width = c.height = 64;
        var x = c.getContext("2d");
        x.lineWidth = 9;
        if (kind === "hit") { x.fillStyle = C.white; x.strokeStyle = C.spruce; x.beginPath(); x.arc(32, 32, 22, 0, 7); x.fill(); x.stroke(); }
        else if (kind === "false") { x.strokeStyle = C.paint; x.lineWidth = 11; x.beginPath(); x.moveTo(12, 12); x.lineTo(52, 52); x.moveTo(52, 12); x.lineTo(12, 52); x.stroke(); }
        else { x.strokeStyle = C.paint; x.beginPath(); x.arc(32, 32, 24, 0, 7); x.stroke(); }
        var t = new THREE.CanvasTexture(c); return t;
      }
      function markerSet(list, kind, size) {
        var p = new Float32Array(list.length * 3);
        list.forEach(function (m, k) { p[k * 3] = m[0] - W / 2; p[k * 3 + 1] = m[2] - zmin + 1.2; p[k * 3 + 2] = -(m[1] - H / 2); });
        var g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(p, 3));
        var m = new THREE.PointsMaterial({ size: size, map: sprite(kind), transparent: true, depthTest: false, sizeAttenuation: true });
        var pts = new THREE.Points(g, m); pts.renderOrder = 2; return pts;
      }
      /* detections carry height above ground; place them on the ground under them */
      var ground = syn.truth.map(function (t) { return [t[0], t[1], t[2]]; });
      function groundAt(x, y) {
        var best = 1e9, z = 0;
        for (var k = 0; k < ground.length; k++) {
          var d = (ground[k][0] - x) * (ground[k][0] - x) + (ground[k][1] - y) * (ground[k][1] - y);
          if (d < best) { best = d; z = ground[k][2]; }
        }
        return z;
      }
      var hits = [], falses = [];
      syn.detections.forEach(function (d) {
        var top = [d[0], d[1], groundAt(d[0], d[1]) + d[2]];
        (d[3] ? hits : falses).push(top);
      });
      var missed = syn.truth.filter(function (t) { return !t[5]; }).map(function (t) { return [t[0], t[1], t[2] + t[3]]; });
      var markers = new THREE.Group();
      markers.add(markerSet(hits, "hit", 4.5), markerSet(falses, "false", 12), markerSet(missed, "miss", 12));
      scene.add(markers);
      var m = syn.metrics;
      $("hero-key").innerHTML = '<i style="background:#fbfcfa;border:2px solid #1e2b27"></i>' + m.tp + ' found &nbsp; ' +
        '<i style="border:2px solid #e8642a"></i>' + m.fn + ' missed &nbsp; ' +
        '<i style="background:#e8642a"></i>' + m.fp + ' false';

      var camera = new THREE.PerspectiveCamera(42, 1, 1, 5000);
      var target = new THREE.Vector3(0, 70, 0);
      var state = { az: 0.75, el: 0.62, dist: 560, spin: !reduceMotion };
      function place() {
        var ce = Math.cos(state.el);
        camera.position.set(target.x + state.dist * ce * Math.sin(state.az), target.y + state.dist * Math.sin(state.el),
                            target.z + state.dist * ce * Math.cos(state.az));
        camera.lookAt(target);
      }
      function resize() {
        var w = canvas.clientWidth, h = canvas.clientHeight;
        renderer.setSize(w, h, false); camera.aspect = w / h;
        state.dist = Math.max(state.dist, w < 600 ? 640 : 520);
        camera.updateProjectionMatrix();
      }
      var drag = null, pinch = null, pointers = {};
      canvas.addEventListener("pointerdown", function (e) {
        pointers[e.pointerId] = [e.clientX, e.clientY]; canvas.setPointerCapture(e.pointerId);
        drag = [e.clientX, e.clientY]; state.spin = false; setSpin(false);
      });
      canvas.addEventListener("pointermove", function (e) {
        if (!(e.pointerId in pointers)) return;
        pointers[e.pointerId] = [e.clientX, e.clientY];
        var ids = Object.keys(pointers);
        if (ids.length === 2) {
          var a = pointers[ids[0]], b = pointers[ids[1]], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
          if (pinch) state.dist = Math.min(1400, Math.max(140, state.dist * pinch / d));
          pinch = d; return;
        }
        if (!drag) return;
        state.az -= (e.clientX - drag[0]) * 0.006;
        state.el = Math.min(1.45, Math.max(0.08, state.el + (e.clientY - drag[1]) * 0.005));
        drag = [e.clientX, e.clientY];
      });
      function up(e) { delete pointers[e.pointerId]; drag = null; pinch = null; }
      canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
      canvas.addEventListener("wheel", function (e) {
        e.preventDefault(); state.dist = Math.min(1400, Math.max(140, state.dist * (1 + e.deltaY * 0.0012)));
      }, { passive: false });

      document.querySelectorAll("[data-color]").forEach(function (b) {
        b.addEventListener("click", function () {
          document.querySelectorAll("[data-color]").forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
          colAttr.array.set(b.dataset.color === "class" ? colC : colH); colAttr.needsUpdate = true;
        });
      });
      $("toggle-trees").addEventListener("click", function () {
        markers.visible = !markers.visible; this.setAttribute("aria-pressed", String(markers.visible));
        $("hero-key").style.display = markers.visible ? "" : "none";
      });
      function setSpin(on) { state.spin = on; $("toggle-spin").setAttribute("aria-pressed", String(on)); }
      $("toggle-spin").addEventListener("click", function () { setSpin(!state.spin); });
      setSpin(state.spin);

      var visible = true;
      if ("IntersectionObserver" in window) {
        new IntersectionObserver(function (es) { visible = es[0].isIntersecting; }).observe(canvas);
      }
      window.addEventListener("resize", resize);
      resize(); place();
      load.remove();
      (function frame() {
        requestAnimationFrame(frame);
        if (!visible) return;
        if (state.spin) state.az += 0.0016;
        place(); renderer.render(scene, camera);
      })();
    });
  });

  /* ============================== density ============================== */
  var densitySection = safe("density", function (d) {
    var steps = d.steps.slice().sort(function (a, b) { return a.density - b.density; });
    var range = $("density-range"), canvas = $("density-canvas");
    range.max = steps.length - 1; range.value = steps.length - 1;
    $("density-ticks").innerHTML = steps.map(function (s) { return "<span>" + fmt(s.density, 1) + "</span>"; }).join("");
    var imgs = steps.map(function (s) { var im = new Image(); im.src = "data/" + s.png; im.onload = function () { draw(); }; return im; });
    function draw() {
      var s = steps[+range.value], im = imgs[+range.value];
      var P = prep(canvas, 1), ctx = P.ctx, w = P.w, h = P.h;
      ctx.fillStyle = C.plot; ctx.fillRect(0, 0, w, h);
      var b = s.bounds, sx = w / (b[2] - b[0]), sy = h / (b[3] - b[1]);
      if (im.complete && im.naturalWidth) { ctx.imageSmoothingEnabled = false; ctx.drawImage(im, 0, 0, w, h); }
      function px(p) { return [(p[0] - b[0]) * sx, (b[3] - p[1]) * sy]; }
      var r = Math.max(2, w / 260);
      s.dets.forEach(function (p) {
        var q = px(p);
        if (p[2]) { ctx.beginPath(); ctx.arc(q[0], q[1], r, 0, 7); ctx.fillStyle = C.white; ctx.fill(); ctx.lineWidth = 1; ctx.strokeStyle = C.spruce; ctx.stroke(); }
      });
      ctx.lineWidth = 2;
      s.missed.forEach(function (p) { var q = px(p); ctx.beginPath(); ctx.arc(q[0], q[1], r + 2, 0, 7); ctx.strokeStyle = C.paint; ctx.stroke(); });
      s.dets.forEach(function (p) {
        if (p[2]) return;
        var q = px(p), k = r + 1.5;
        ctx.strokeStyle = C.paint; ctx.lineWidth = 2.4; ctx.beginPath();
        ctx.moveTo(q[0] - k, q[1] - k); ctx.lineTo(q[0] + k, q[1] + k); ctx.moveTo(q[0] + k, q[1] - k); ctx.lineTo(q[0] - k, q[1] + k); ctx.stroke();
      });
      $("d-recall").textContent = fmt(s.recall) + "%";
      $("d-precision").textContent = fmt(s.precision) + "%";
      $("d-rmse").textContent = fmt(s.rmse, 2) + " m";
      range.setAttribute("aria-valuetext", fmt(s.density, 2) + " points per square metre");
      $("density-now").textContent = fmt(s.density, 2) + " points per m²: " + s.detected + " detections, " +
        s.fp + " with no tree under them, " + s.fn + " trees missed. " + fmt(s.empty_pct, 0) + "% of the 1 m cells got no laser return at all.";
    }
    range.addEventListener("input", draw);
    window.addEventListener("resize", draw);
    draw();

    /* finding 2: 1 m against 2 m */
    var c2 = $("res-canvas");
    function drawRes() {
      var P = prep(c2, 0.5), ctx = P.ctx, w = P.w, h = P.h, L = 46, R = 16, T = 18, B = 66;
      ctx.clearRect(0, 0, w, h); ctx.fillStyle = C.plot; ctx.fillRect(0, 0, w, h);
      var one = steps.map(function (s) { return [s.density, s.recall]; });
      var two = d.two_m.map(function (s) { return [s.density, s.recall]; });
      var oneB = d.one_m_birch.map(function (s) { return [s.density, s.birch]; });
      var twoB = d.two_m.map(function (s) { return [s.density, s.birch]; });
      var lx = function (v) { return L + (Math.log(v) - Math.log(0.4)) / (Math.log(8) - Math.log(0.4)) * (w - L - R); };
      var ly = function (v) { return T + (95 - v) / (95 - 45) * (h - T - B); };
      ctx.font = FONT; ctx.fillStyle = C.spruce; ctx.strokeStyle = "#d9ded5"; ctx.lineWidth = 1;
      [50, 60, 70, 80, 90].forEach(function (v) { ctx.beginPath(); ctx.moveTo(L, ly(v)); ctx.lineTo(w - R, ly(v)); ctx.stroke(); ctx.fillText(v + "%", 8, ly(v) + 4); });
      [0.5, 1, 2, 4].forEach(function (v) { ctx.fillText(v + " p/m²", lx(v) - 18, h - B + 20); });
      function line(pts, col, dash, label) {
        ctx.setLineDash(dash); ctx.strokeStyle = col; ctx.lineWidth = 2.5; ctx.beginPath();
        pts.forEach(function (p, i) { var X = lx(p[0]), Y = ly(p[1]); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); }); ctx.stroke();
        ctx.setLineDash([]); ctx.fillStyle = col;
        pts.forEach(function (p) { ctx.beginPath(); ctx.arc(lx(p[0]), ly(p[1]), 3.2, 0, 7); ctx.fill(); });
        legendItems.push([col, dash, label]);
      }
      var legendItems = [];
      line(one, C.moss, [], "1 m grid, all trees");
      line(two, C.paint, [], "2 m grid, all trees");
      line(oneB, C.moss, [5, 4], "1 m grid, birch");
      line(twoB, C.paint, [5, 4], "2 m grid, birch");
      ctx.font = FONT; var lxp = L, ly0 = h - 26;
      legendItems.forEach(function (it) {
        var wd = ctx.measureText(it[2]).width + 46;
        if (lxp + wd > w - R) { lxp = L; ly0 += 16; }
        ctx.setLineDash(it[1]); ctx.strokeStyle = it[0]; ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.moveTo(lxp, ly0 - 4); ctx.lineTo(lxp + 22, ly0 - 4); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = C.spruce; ctx.fillText(it[2], lxp + 28, ly0); lxp += wd;
      });
    }
    drawRes(); window.addEventListener("resize", drawRes);
  });

  /* ============================== change ============================== */
  var changeSection = safe("change", function (c) {
    var cv = $("change-canvas");
    function draw() {
      var P = prep(cv, 0.46), ctx = P.ctx, w = P.w, h = P.h, L = 54, R = 12, T = 16, B = 40;
      ctx.fillStyle = C.plot; ctx.fillRect(0, 0, w, h);
      var max = 0.65, min = -0.1, n = c.bands.length, bw = (w - L - R) / n;
      var y = function (v) { return T + (max - v) / (max - min) * (h - T - B); };
      ctx.font = FONT; ctx.strokeStyle = "#d9ded5"; ctx.fillStyle = C.spruce;
      [0, 0.2, 0.4, 0.6].forEach(function (v) { ctx.beginPath(); ctx.moveTo(L, y(v)); ctx.lineTo(w - R, y(v)); ctx.stroke(); ctx.fillText(v.toFixed(1) + " m", 6, y(v) + 4); });
      c.bands.forEach(function (b, i) {
        var x0 = L + i * bw + bw * 0.18, x1 = L + (i + 1) * bw - bw * 0.18;
        ctx.fillStyle = b.rate > b.cap ? C.paint : C.moss;
        ctx.fillRect(x0, Math.min(y(b.rate), y(0)), x1 - x0, Math.abs(y(b.rate) - y(0)));
        ctx.setLineDash([5, 4]); ctx.strokeStyle = C.spruce; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(x0 - 6, y(b.cap)); ctx.lineTo(x1 + 6, y(b.cap)); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = C.spruce; ctx.font = FONTB; ctx.fillText((b.rate >= 0 ? "+" : "") + b.rate.toFixed(2), x0, y(Math.max(b.rate, 0)) - 6);
        ctx.font = FONT; ctx.fillText(b.band, x0, h - 14);
      });
    }
    draw(); window.addEventListener("resize", draw);
    $("change-cap").textContent = "Height gain per year, 2008 to 2020, grouped by height in 2015. Dashed lines are what forest of that height can plausibly add; orange bars exceed it. Bare ground agreed to " +
      (c.ground_offset_m >= 0 ? "+" : "") + c.ground_offset_m.toFixed(2) + " m across " + c.bare_pixels.toLocaleString("en-US") + " bare pixels.";
  });

  /* ============================== stand map ============================== */
  var mapSection = safe("map", function (real, stands) {
    setK("stem_recovery_median", fmt(real.stem_recovery_median, 1));
    setK("det_h_r", fmt(real.det_h_r, 3));
    var map = L.map("map", { scrollWheelZoom: false, zoomSnap: 0.25 });
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 18, attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics; stands and canopy &copy; Finnish Forest Centre, CC BY 4.0" }).addTo(map);
    var b = real.chm_bounds, chm = L.imageOverlay("data/chm_2020.png", [[b[0], b[1]], [b[2], b[3]]], { opacity: 0.85 }).addTo(map);
    map.fitBounds([[b[0], b[1]], [b[2], b[3]]]);
    var metric = "bias";
    var CLS = { "02": ["young thinning", "#9fb68a"], "03": ["advanced thinning", "#5f8a52"], "04": ["regeneration-mature", "#2f4a2c"],
                "T2": ["advanced seedlings", "#cfd8a8"], "Y1": ["seedlings under overstory", "#d8c890"], "A0": ["open", "#d9d2c3"],
                "T1": ["seedlings", "#e6e0c8"], "S0": ["seed-tree", "#b9a06e"], "05": ["shelterwood", "#8d7a52"] };
    function div(v, lo, hi) {   /* cold - pale - paint */
      var t = Math.max(-1, Math.min(1, v < 0 ? -(v / lo) : v / hi));
      var pale = [238, 236, 226], cold = [63, 111, 143], hot = [232, 100, 42];
      var e = t < 0 ? cold : hot, k = Math.abs(t);
      return "rgb(" + pale.map(function (p, i) { return Math.round(p + (e[i] - p) * k); }).join(",") + ")";
    }
    function seq(v, lo, hi) {
      var t = Math.max(0, Math.min(1, (v - lo) / (hi - lo))), a = [238, 236, 226], z = [79, 110, 69];
      return "rgb(" + a.map(function (p, i) { return Math.round(p + (z[i] - p) * t); }).join(",") + ")";
    }
    function style(f) {
      var p = f.properties, v = p.validated, fill = "#000", op = 0;
      if (metric === "cls") { fill = (CLS[p.cls] || ["", "#cccccc"])[1]; op = 0.75; }
      else if (v && metric === "bias" && p.det_h != null && p.inv_h != null) { fill = div(p.det_h - p.inv_h, -4, 4); op = 0.85; }
      else if (v && metric === "rate" && p.inv_n) { fill = seq(100 * p.det_n / p.inv_n, 0, 35); op = 0.85; }
      return { color: "#fbfcfa", weight: 0.7, opacity: 0.8, fillColor: fill, fillOpacity: op };
    }
    function pop(p) {
      var row = function (k, v) { return "<tr><td>" + k + "</td><td><b>" + v + "</b></td></tr>"; };
      var cls = CLS[p.cls] ? p.cls + ", " + CLS[p.cls][0] : (p.cls || "unclassified");
      var html = '<div class="stand-pop"><b>Stand ' + p.standid + "</b><table>" + row("Class", cls) + row("Area", fmt(p.ha, 1) + " ha");
      if (p.inv_h != null) html += row("Inventory height", fmt(p.inv_h) + " m" + (p.obs ? " (" + p.obs + ")" : ""));
      if (p.det_h != null) html += row("Detected tops", fmt(p.det_h) + " m");
      if (p.inv_n) html += row("Stems found", Math.round(p.det_n) + " of " + Math.round(p.inv_n) + " /ha");
      if (p.cov != null && p.cov < 99) html += row("Has canopy data", fmt(p.cov, 0) + "%");
      html += row("Cutting proposed", p.op_cut ? "yes" : "no");
      if (!p.validated) html += '<tr><td colspan="2">Not in the validation set (old, unusable or no inventory)</td></tr>';
      return html + "</table></div>";
    }
    var layer = L.geoJSON(stands, { style: style, onEachFeature: function (f, l) { l.bindPopup(pop(f.properties)); } }).addTo(map);
    var legend = L.control({ position: "topright" });
    legend.onAdd = function () { this._div = L.DomUtil.create("div", "map-legend"); return this._div; };
    legend.addTo(map);
    function updLegend() {
      var d = legend._div;
      if (metric === "bias") d.innerHTML = "Detected-top height minus inventory height<div class='bar' style='background:linear-gradient(90deg,rgb(63,111,143),rgb(238,236,226),rgb(232,100,42))'></div><div class='ends'><span>−4 m</span><span>0</span><span>+4 m</span></div>";
      else if (metric === "rate") d.innerHTML = "Share of inventory stems detected<div class='bar' style='background:linear-gradient(90deg,rgb(238,236,226),rgb(79,110,69))'></div><div class='ends'><span>0%</span><span>35%+</span></div>";
      else d.innerHTML = Object.keys(CLS).filter(function (k) { return ["02", "03", "04", "T2", "Y1", "A0"].indexOf(k) >= 0; })
        .map(function (k) { return "<div><i style='display:inline-block;width:10px;height:10px;background:" + CLS[k][1] + ";margin-right:6px'></i>" + k + " " + CLS[k][0] + "</div>"; }).join("");
    }
    updLegend();
    document.querySelectorAll("[data-metric]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        metric = btn.dataset.metric;
        document.querySelectorAll("[data-metric]").forEach(function (o) { o.setAttribute("aria-pressed", String(o === btn)); });
        layer.setStyle(style); updLegend();
      });
    });
    $("chm-toggle").addEventListener("change", function () {
      this.checked ? chm.addTo(map) : map.removeLayer(chm);
    });
    if (real.inventory_source) {
      var s2 = real.inventory_source, tot = s2.field + s2.remote_sensed + s2.other;
      $("inv-source").textContent = "One caution on that correlation. Of the " + tot.toLocaleString("en-US") + " stands checked, " +
        s2.remote_sensed.toLocaleString("en-US") + " have an inventory the Forest Centre interpreted from airborne laser data, and " + s2.field +
        (s2.field === 1 ? " was" : " were") + " measured in the field. So this is largely laser checked against laser, which flatters the agreement. The stem-count gap is a different matter: the inventory's stem numbers come from models calibrated on field sample plots, which count the suppressed trees that a laser looking down at the canopy can't pick out one by one.";
    }
    if (real.proposals) {
      $("proposal-source").textContent = "The Forest Centre's 2025 data release explains why. Its cutting proposals are labelled by origin, and of the " +
        real.proposals.stands.toLocaleString("en-US") + " stands with one on this sheet, " + (real.proposals.field === 0 ? "none" : real.proposals.field === 1 ? "one" : real.proposals.field) +
        " came from a forester in the field. The rest are simulated by the Forest Centre's planning calculation from the same inventory. A model that proposes cutting for mature stands will propose it for nearly every mature stand.";
    }
    if (real.validated_low_cov != null) {
      $("cov-note").textContent = "The rebuild found " + real.validated_low_cov + " stands in the validation set with under 90% coverage; leaving them out moves median stem recovery from " +
        fmt(real.stem_recovery_median) + "% to " + fmt(real.stem_recovery_median_full_cov) + "%. The next version of the check should filter on it.";
    }
    $("map-cap").textContent = real.stands.toLocaleString("en-US") + " private forest stands on map sheet L4132D, " +
      real.validated.toLocaleString("en-US") + " of them with a fresh, usable inventory to check against (filled). Click a stand for its numbers.";

    /* the negative result */
    var grid = $("grid472"), html = "";
    for (var i = 0; i < real.pool; i++) html += i < real.pool_cut ? "<i></i>" : '<i class="no" title="not proposed for cutting"></i>';
    grid.innerHTML = html;
    $("grid472-cap").innerHTML = "<span class='num'>" + real.pool_cut + "</span> of <span class='num'>" + real.pool +
      "</span> eligible mature stands were already proposed for cutting. Green: proposed. Orange: not.";
  });

  var machineSection = safe("machine", function (m) {
    var s = m.season, a = m.access;
    function row(k, v) { return "<tr><td>" + k + "</td><td class='r'>" + (v || 0) + "</td></tr>"; }
    $("machine-table").innerHTML =
      "<table class='data'><thead><tr><th>Season, from wetness</th><th class='r'>stands</th></tr></thead><tbody>" +
      row("summer-trafficable", s["summer-trafficable"]) + row("dry season preferred", s["dry season preferred"]) + row("frozen ground only", s["frozen-ground only"]) +
      "</tbody></table><table class='data'><thead><tr><th>Access, from slope</th><th class='r'>stands</th></tr></thead><tbody>" +
      row("conventional", a["conventional"]) + row("winch assist advised", a["winch assist advised"]) + row("steep, review access", a["steep - review access"]) +
      "</tbody></table><p class='small'>" + m.scheduled + " mature stands with a cutting proposal; " + m.both + " are both wet and steep.</p>";
  });

  /* ============================== Washington ============================== */
  var waSection = safe("wa", function (w) {
    var apps = w.apps, cv = $("wa-canvas"), range = $("wa-range");
    var nY = apps.filter(function (a) { return a[1]; }).length;
    var bins = 60, lo = 0, hi = 75;
    function draw() {
      var t = +range.value, P = prep(cv, 0.58), ctx = P.ctx, W = P.w, H = P.h, L = 36, R = 10, T = 14, B = 34;
      ctx.fillStyle = C.plot; ctx.fillRect(0, 0, W, H);
      var hy = new Array(bins).fill(0), hn = new Array(bins).fill(0);
      apps.forEach(function (a) { var k = Math.min(bins - 1, Math.max(0, Math.floor((a[0] - lo) / (hi - lo) * bins))); (a[1] ? hy : hn)[k]++; });
      var mx = Math.max.apply(null, hy.concat(hn)), bw = (W - L - R) / bins;
      var x = function (v) { return L + (v - lo) / (hi - lo) * (W - L - R); }, half = (H - T - B) / 2, mid = T + half;
      for (var k = 0; k < bins; k++) {
        ctx.fillStyle = C.paint; ctx.fillRect(L + k * bw + 0.5, mid - hy[k] / mx * half, bw - 1, hy[k] / mx * half);
        ctx.fillStyle = C.cold; ctx.fillRect(L + k * bw + 0.5, mid, bw - 1, hn[k] / mx * half);
      }
      ctx.font = FONT; ctx.fillStyle = C.spruce;
      [0, 15, 30, 45, 60, 75].forEach(function (v) { ctx.fillText(v + "°", x(v) - 6, H - 12); });
      ctx.fillText("flagged", L + 4, T + 12); ctx.fillText("not flagged", L + 4, H - B - 6);
      ctx.strokeStyle = C.spruce; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x(t), T); ctx.lineTo(x(t), H - B); ctx.stroke();
      ctx.font = FONTB; ctx.fillText(t.toFixed(1) + "°", Math.min(x(t) + 6, W - 48), T + 12);
      var steepN = 0, flatY = 0;
      apps.forEach(function (a) { if (a[0] >= t && !a[1]) steepN++; if (a[0] < t && a[1]) flatY++; });
      $("wa-acc").textContent = fmt(100 * (apps.length - steepN - flatY) / apps.length) + "%";
      $("wa-sn").textContent = steepN; $("wa-fn").textContent = flatY;
      range.setAttribute("aria-valuetext", t.toFixed(1) + " degrees");
    }
    $("wa-note").textContent = apps.length.toLocaleString("en-US") + " applications, " + fmt(100 * nY / apps.length) +
      "% flagged, so guessing gets you about half. The slider starts at the best single cutoff, 33.7°.";
    range.addEventListener("input", draw); window.addEventListener("resize", draw); draw();
  });

  /* ============================== boot ============================== */
  getJSON("synthetic.json").then(function (syn) {
    setK("truth", syn.metrics.truth);
    var m = syn.metrics;
    $("hero-score").textContent = "On this forest the method found " + m.tp + " of " + m.truth + " trees (" + fmt(m.recall) +
      "%), and " + fmt(m.precision) + "% of its detections were real, with tree heights off by " + fmt(m.rmse, 2) +
      " m on average (RMSE). Spruce " + fmt(m.by_species.spruce) + "%, pine " + fmt(m.by_species.pine) + "%, birch " + fmt(m.by_species.birch) + "%.";
    return heroCloud(syn);
  }).catch(function (e) { console.error(e); $("cloud-load").textContent = "The point cloud didn't load."; });
  getJSON("density.json").then(densitySection).catch(console.error);
  getJSON("change.json").then(changeSection).catch(console.error);
  Promise.all([getJSON("real.json"), getJSON("stands.geojson")]).then(function (x) { mapSection(x[0], x[1]); }).catch(console.error);
  getJSON("machine.json").then(machineSection).catch(console.error);
  getJSON("wa.json").then(waSection).catch(console.error);
  fetch("data/build.json").then(function (r) { return r.ok ? r.json() : null; }).then(function (b) {
    if (b) $("build-note").textContent = "Last rebuilt " + b.date + " from commit " + b.commit + ".";
  }).catch(function () {});
})();

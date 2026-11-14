/* Biverse website: direct download links, "your computer" hint and the hero demo.
   Everything works without this script (links fall back to the latest release page). */
(function () {
  "use strict";

  var REPO = "https://github.com/CeoFred/biverse";
  var version = document.documentElement.getAttribute("data-version") || "";

  // -- direct download links ------------------------------------------------------------
  function assetUrl(name) {
    return REPO + "/releases/download/v" + version + "/" + name;
  }
  if (version) {
    document.querySelectorAll("[data-file]").forEach(function (a) {
      var f = a.getAttribute("data-file");
      if (f) a.href = assetUrl("Biverse-" + version + "-" + f + ".zip");
    });
    document.querySelectorAll("[data-pack]").forEach(function (a) {
      a.href = assetUrl("Biverse-" + a.getAttribute("data-pack") + "-" + version + ".zip");
    });
  }

  // -- which download fits this computer ------------------------------------------------
  function detect() {
    var ua = navigator.userAgent || "";
    var platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    if (/Windows NT (6\.[123])/.test(ua)) return { row: "windows-legacy", file: "windows-legacy-x64", label: "Windows 7/8" };
    if (/Win/i.test(platform) || /Windows/.test(ua)) return { row: "windows", file: "windows-x64", label: "Windows" };
    if (/Mac/i.test(platform) || /Mac OS X/.test(ua)) {
      if (/iPhone|iPad/.test(ua) || navigator.maxTouchPoints > 1) return null; // iPad reports "Mac"
      return { row: "mac", file: null, label: "Mac" };
    }
    return null;
  }

  function appleSilicon() {
    // A WebGL renderer string is the only reliable hint in Safari and Chrome.
    try {
      var gl = document.createElement("canvas").getContext("webgl");
      var ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
      var r = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "";
      if (/Apple M\d|Apple GPU/i.test(r)) return true;
      if (/Intel|AMD|Radeon|NVIDIA/i.test(r)) return false;
    } catch (e) { /* ignore */ }
    return null;
  }

  var os = detect();
  if (os) {
    if (os.row === "mac") {
      var arm = appleSilicon();
      if (arm === true) { os.row = "mac-arm"; os.file = "macos-arm"; os.label = "Mac (Apple Silicon)"; }
      else if (arm === false) { os.row = "mac-intel"; os.file = "macos-intel"; os.label = "Mac (Intel)"; }
    }
    var row = document.querySelector('tr[data-os="' + os.row + '"]');
    if (row) row.classList.add("is-yours");
    var cta = document.getElementById("primary-download");
    if (cta && os.file && version) {
      cta.href = assetUrl("Biverse-" + version + "-" + os.file + ".zip");
      cta.textContent = "Download for " + os.label;
    } else if (cta && os.row === "mac") {
      cta.textContent = "Download for Mac";
    }
  }

  // -- hero demo: a few spoken references, cross-faded -----------------------------------
  var examples = [
    { said: "…so this morning, turn with me to <mark>John chapter three verse sixteen</mark>…",
      ref: "John 3:16", v: "KJV",
      text: "For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life." },
    { said: "…the apostle writes in <mark>Romans eight and verse twenty eight</mark>, listen…",
      ref: "Romans 8:28", v: "KJV",
      text: "And we know that all things work together for good to them that love God, to them who are the called according to his purpose." },
    { said: "…let’s read it together, <mark>Psalm one nineteen verse one oh five</mark>…",
      ref: "Psalm 119:105", v: "KJV",
      text: "Thy word is a lamp unto my feet, and a light unto my path." },
    { said: "…<mark>second Timothy three sixteen</mark>, in the ASV this time…",
      ref: "2 Timothy 3:16", v: "ASV",
      text: "Every scripture inspired of God is also profitable for teaching, for reproof, for correction, for instruction which is in righteousness." }
  ];

  var demo = document.querySelector(".demo");
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!demo || reduce) return;

  var el = {
    said: document.getElementById("demo-transcript"),
    chip: document.getElementById("demo-chip"),
    verse: document.getElementById("demo-verse"),
    ref: document.getElementById("demo-ref")
  };
  var i = 0;
  var timer = null;

  function show(ex) {
    demo.classList.add("is-swapping");
    setTimeout(function () {
      el.said.innerHTML = "“" + ex.said + "”";
      el.chip.textContent = ex.ref + " · " + ex.v;
      el.verse.textContent = ex.text;
      el.ref.innerHTML = "";
      el.ref.appendChild(document.createTextNode(ex.ref + " "));
      var s = document.createElement("span");
      s.textContent = ex.v;
      el.ref.appendChild(s);
      demo.classList.remove("is-swapping");
    }, 360);
  }

  function start() {
    if (timer) return;
    timer = setInterval(function () { i = (i + 1) % examples.length; show(examples[i]); }, 6000);
  }
  function stop() { clearInterval(timer); timer = null; }

  document.addEventListener("visibilitychange", function () { document.hidden ? stop() : start(); });
  demo.addEventListener("mouseenter", stop);
  demo.addEventListener("mouseleave", start);
  start();
})();

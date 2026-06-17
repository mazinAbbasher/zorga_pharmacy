/*
 * PharmaScanner — a reusable, robust barcode / QR scanner overlay.
 *
 * Used in two places:
 *   - POS terminal  -> scan to find a medicine and add it to the cart.
 *   - Drug form     -> scan to fill the barcode/SKU field when adding medicine.
 *
 * Design goals (reliability on a desktop install):
 *   - Enumerate cameras and let the user pick; remember the choice.
 *   - Clear, friendly messages for every failure (no camera, permission denied,
 *     camera busy) instead of silently doing nothing.
 *   - A manual-entry box as a guaranteed fallback (also lets a USB barcode
 *     scanner type straight in and submit).
 *   - Bullet-proof start/stop lifecycle so the camera is always released.
 *
 * Public API:
 *   PharmaScanner.open({ title, onScan, continuous })
 *   PharmaScanner.close()
 *
 *   onScan(code)  -> called with the decoded/typed text (already trimmed).
 *   continuous    -> if true, keep scanning after each hit (POS multi-add);
 *                    if false, scan once then close (filling a form field).
 */
(function () {
    "use strict";

    var STORAGE_KEY = "pharma_scanner_camera_id";
    var SUPPORTED_FORMATS = null; // computed lazily once the library is loaded

    var state = {
        html5: null,
        running: false,
        starting: false,
        overlay: null,
        opts: null,
        lastCode: null,
        lastCodeAt: 0,
        audioCtx: null,
    };

    /* ---------------------------------------------------------------- audio */
    function beep() {
        try {
            if (!state.audioCtx) {
                var Ctx = window.AudioContext || window.webkitAudioContext;
                if (!Ctx) return;
                state.audioCtx = new Ctx();
            }
            var ctx = state.audioCtx;
            var osc = ctx.createOscillator();
            var gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.type = "sine";
            osc.frequency.setValueAtTime(880, ctx.currentTime);
            gain.gain.setValueAtTime(0.12, ctx.currentTime);
            osc.start();
            osc.stop(ctx.currentTime + 0.1);
        } catch (e) { /* audio is non-critical */ }
    }

    /* -------------------------------------------------------------- formats */
    function supportedFormats() {
        if (SUPPORTED_FORMATS !== null) return SUPPORTED_FORMATS;
        SUPPORTED_FORMATS = undefined; // default: let the library detect everything
        try {
            var F = window.Html5QrcodeSupportedFormats;
            if (F) {
                // Common pharmacy/retail symbologies + QR.
                SUPPORTED_FORMATS = [
                    F.QR_CODE, F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E,
                    F.CODE_128, F.CODE_39, F.CODE_93, F.ITF, F.CODABAR,
                    F.DATA_MATRIX,
                ].filter(function (x) { return x !== undefined; });
            }
        } catch (e) { SUPPORTED_FORMATS = undefined; }
        return SUPPORTED_FORMATS;
    }

    /* ---------------------------------------------------------------- view */
    function buildOverlay() {
        if (state.overlay) return state.overlay;

        var el = document.createElement("div");
        el.id = "pharma-scanner-overlay";
        el.className = "hidden";
        el.style.cssText =
            "position:fixed;inset:0;z-index:200;display:flex;align-items:center;" +
            "justify-content:center;padding:1rem;background:rgba(15,23,42,.65);" +
            "backdrop-filter:blur(6px);";

        el.innerHTML =
            '<div style="width:100%;max-width:30rem;background:#fff;border-radius:1.75rem;' +
            'overflow:hidden;box-shadow:0 40px 120px rgba(0,0,0,.4);">' +
              '<div style="display:flex;align-items:center;justify-content:space-between;' +
              'padding:1.25rem 1.5rem;border-bottom:1px solid #f1f5f9;">' +
                '<h3 id="pharma-scanner-title" style="font-size:1.1rem;font-weight:800;' +
                'color:#0f172a;margin:0;">Scan Barcode</h3>' +
                '<button type="button" id="pharma-scanner-close" aria-label="Close" ' +
                'style="border:0;background:#f1f5f9;color:#475569;width:2.25rem;height:2.25rem;' +
                'border-radius:.85rem;font-size:1.1rem;cursor:pointer;line-height:1;">&times;</button>' +
              '</div>' +
              '<div style="padding:1.25rem 1.5rem;">' +
                '<select id="pharma-scanner-cameras" style="display:none;width:100%;' +
                'margin-bottom:.85rem;padding:.6rem .75rem;border:1px solid #e2e8f0;' +
                'border-radius:.85rem;font-size:.85rem;font-weight:600;color:#334155;' +
                'background:#f8fafc;cursor:pointer;"></select>' +

                '<div id="pharma-scanner-view" style="width:100%;aspect-ratio:1/1;' +
                'background:#0f172a;border-radius:1.25rem;overflow:hidden;"></div>' +

                '<p id="pharma-scanner-status" style="margin:.85rem 0 0;font-size:.8rem;' +
                'font-weight:600;color:#64748b;text-align:center;min-height:1.1rem;"></p>' +

                '<div style="margin-top:1rem;border-top:1px dashed #e2e8f0;padding-top:1rem;">' +
                  '<label style="font-size:.62rem;font-weight:800;letter-spacing:.15em;' +
                  'text-transform:uppercase;color:#94a3b8;">Or enter code manually / USB scanner</label>' +
                  '<form id="pharma-scanner-manual" style="display:flex;gap:.5rem;margin-top:.5rem;">' +
                    '<input id="pharma-scanner-input" type="text" autocomplete="off" ' +
                    'placeholder="Type or scan, then Enter" style="flex:1;padding:.6rem .8rem;' +
                    'border:1px solid #e2e8f0;border-radius:.85rem;font-size:.9rem;font-weight:600;' +
                    'outline:none;">' +
                    '<button type="submit" style="border:0;background:#16a34a;color:#fff;' +
                    'padding:0 1.1rem;border-radius:.85rem;font-weight:700;cursor:pointer;">Go</button>' +
                  '</form>' +
                '</div>' +
              '</div>' +
            '</div>';

        document.body.appendChild(el);
        state.overlay = el;

        el.querySelector("#pharma-scanner-close").addEventListener("click", PharmaScanner.close);
        el.addEventListener("mousedown", function (e) {
            if (e.target === el) PharmaScanner.close();
        });

        var camSel = el.querySelector("#pharma-scanner-cameras");
        camSel.addEventListener("change", function () {
            try { localStorage.setItem(STORAGE_KEY, camSel.value); } catch (e) {}
            restartWithCamera(camSel.value);
        });

        var manual = el.querySelector("#pharma-scanner-manual");
        manual.addEventListener("submit", function (e) {
            e.preventDefault();
            var input = el.querySelector("#pharma-scanner-input");
            var code = (input.value || "").trim();
            if (!code) return;
            input.value = "";
            handleHit(code, /*fromManual*/ true);
        });

        return el;
    }

    function setStatus(msg, isError) {
        var s = state.overlay && state.overlay.querySelector("#pharma-scanner-status");
        if (!s) return;
        s.textContent = msg || "";
        s.style.color = isError ? "#dc2626" : "#64748b";
    }

    /* --------------------------------------------------------- scan handling */
    function handleHit(code, fromManual) {
        code = (code || "").trim();
        if (!code) return;

        // Debounce repeated camera reads of the same code.
        var now = Date.now();
        if (!fromManual && code === state.lastCode && (now - state.lastCodeAt) < 1500) {
            return;
        }
        state.lastCode = code;
        state.lastCodeAt = now;

        beep();
        var cb = state.opts && state.opts.onScan;
        var continuous = state.opts && state.opts.continuous;

        if (continuous && !fromManual) {
            setStatus("Scanned: " + code, false);
            if (cb) cb(code);
            // keep the camera running for the next item
        } else {
            // single-shot (or manual entry): close, then deliver the code
            PharmaScanner.close();
            if (cb) cb(code);
        }
    }

    /* --------------------------------------------------------- camera control */
    function startWithCamera(cameraId) {
        if (!window.Html5Qrcode) {
            setStatus("Scanner library failed to load.", true);
            return;
        }
        if (state.starting || state.running) return;
        state.starting = true;
        setStatus("Starting camera…", false);

        if (!state.html5) {
            try {
                state.html5 = new Html5Qrcode("pharma-scanner-view", { verbose: false });
            } catch (e) {
                state.starting = false;
                setStatus("Could not initialise the scanner.", true);
                return;
            }
        }

        var config = { fps: 12, qrbox: function (w, h) {
            var m = Math.floor(Math.min(w, h) * 0.75);
            return { width: m, height: m };
        }};
        var formats = supportedFormats();
        if (formats) config.formatsToSupport = formats;

        var source = cameraId ? cameraId : { facingMode: "environment" };

        state.html5.start(
            source,
            config,
            function (decodedText) { handleHit(decodedText, false); },
            function (/* scanFailure */) { /* per-frame no-match: ignore */ }
        ).then(function () {
            state.running = true;
            state.starting = false;
            setStatus("Point the camera at a barcode.", false);
        }).catch(function (err) {
            state.starting = false;
            state.running = false;
            setStatus(friendlyError(err), true);
        });
    }

    function restartWithCamera(cameraId) {
        stopCamera().then(function () { startWithCamera(cameraId); });
    }

    function stopCamera() {
        var h = state.html5;
        if (!h || (!state.running && !state.starting)) {
            state.running = false;
            return Promise.resolve();
        }
        return h.stop().then(function () {
            state.running = false;
            try { h.clear(); } catch (e) {}
        }).catch(function () {
            state.running = false;
            try { h.clear(); } catch (e) {}
        });
    }

    function friendlyError(err) {
        var name = (err && (err.name || err.toString())) || "";
        if (/NotAllowedError|Permission/i.test(name)) {
            return "Camera permission was denied. Use the USB scanner or type the code below.";
        }
        if (/NotFoundError|Devices|no camera/i.test(name)) {
            return "No camera found. Use a USB scanner or type the code below.";
        }
        if (/NotReadableError|TrackStart|in use/i.test(name)) {
            return "The camera is in use by another program. Close it and try again.";
        }
        return "Could not start the camera. Type the code below instead.";
    }

    function populateCameras() {
        var sel = state.overlay.querySelector("#pharma-scanner-cameras");
        if (!window.Html5Qrcode || !Html5Qrcode.getCameras) {
            startWithCamera(null);
            return;
        }
        Html5Qrcode.getCameras().then(function (cameras) {
            if (!cameras || cameras.length === 0) {
                sel.style.display = "none";
                setStatus("No camera found. Use a USB scanner or type the code below.", true);
                return;
            }
            sel.innerHTML = "";
            cameras.forEach(function (c, i) {
                var opt = document.createElement("option");
                opt.value = c.id;
                opt.textContent = c.label || ("Camera " + (i + 1));
                sel.appendChild(opt);
            });
            sel.style.display = cameras.length > 1 ? "block" : "none";

            var preferred = null;
            try { preferred = localStorage.getItem(STORAGE_KEY); } catch (e) {}
            var ids = cameras.map(function (c) { return c.id; });
            if (!preferred || ids.indexOf(preferred) === -1) preferred = cameras[0].id;
            sel.value = preferred;

            startWithCamera(preferred);
        }).catch(function (err) {
            sel.style.display = "none";
            setStatus(friendlyError(err), true);
        });
    }

    /* ------------------------------------------------------------- public API */
    var PharmaScanner = {
        open: function (opts) {
            opts = opts || {};
            state.opts = opts;
            state.lastCode = null;

            var el = buildOverlay();
            el.querySelector("#pharma-scanner-title").textContent = opts.title || "Scan Barcode";
            el.classList.remove("hidden");
            setStatus("", false);

            // Focus manual input so a USB (keyboard-wedge) scanner works instantly.
            var input = el.querySelector("#pharma-scanner-input");
            if (input) { input.value = ""; setTimeout(function () { input.focus(); }, 50); }

            populateCameras();
        },

        close: function () {
            stopCamera();
            if (state.overlay) state.overlay.classList.add("hidden");
        },

        isOpen: function () {
            return !!(state.overlay && !state.overlay.classList.contains("hidden"));
        },
    };

    // Close on Escape.
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && PharmaScanner.isOpen()) PharmaScanner.close();
    });

    window.PharmaScanner = PharmaScanner;
})();

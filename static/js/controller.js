const socket = io();

// State
let gamepadIndex = null;
let currentMode = 'manual';
let calibMode = 'none'; // 'none', 'x_calib', 'y_calib'

// DOM Elements
const elConn = document.getElementById('status-conn');
const txtConn = document.getElementById('txt-conn');

// HUD Elements (Overlay)
const elHudLaser = document.getElementById('status-laser'); // The dot indicator
const txtHudMode = document.getElementById('txt-mode');     // The text in HUD

// Panel Elements (Right Side)
const txtPanelLaser = document.getElementById('panel-laser');
const txtPanelMode = document.getElementById('panel-mode');

const valPan = document.getElementById('val-pan');
const valTilt = document.getElementById('val-tilt');
const imgStream = document.getElementById('video-stream');
const canvas = document.getElementById('video-overlay');
const ctx = canvas.getContext('2d');
const elCalibStatus = document.getElementById('calib-status');
const btnAuto = document.getElementById('btn-toggle-auto');

// --- MJPEG Reconnection Logic ---
let streamErrors = 0;

imgStream.onerror = () => {
    console.error("Video Stream Broken. Reconnecting...");
    streamErrors++;
    setTimeout(refreshVideoStream, 1000);
};

window.refreshVideoStream = function () {
    console.log(`[Video] Force refreshing stream...`);
    imgStream.src = '';
    setTimeout(() => {
        imgStream.src = `/video_feed?t=${Date.now()}`;
    }, 50);
}

// --- Socket.IO Handlers ---
socket.on('connect', () => {
    elConn.classList.add('active');
    txtConn.innerText = "Connected";
});

socket.on('disconnect', () => {
    elConn.classList.remove('active');
    txtConn.innerText = "Disconnected";
});

socket.on('gimbal_state', (data) => {
    updateUIState(data);
});

socket.on('auto_status', (data) => {
    // data: { state, bbox, roi, roi_radius, frame_size, laser, pan, tilt ... }
    updateUIState(data);
    drawOverlay(data);
});

function updateUIState(data) {
    // 1. Laser
    if (data.laser !== undefined) {
        const isOn = data.laser;
        txtPanelLaser.innerText = isOn ? "ON" : "OFF";
        txtPanelLaser.style.color = isOn ? "#f00" : "#fff";

        if (isOn && elHudLaser) {
            elHudLaser.classList.add('active');
            elHudLaser.classList.add('danger');
        } else if (elHudLaser) {
            elHudLaser.classList.remove('active');
            elHudLaser.classList.remove('danger');
        }
    }

    // 2. Mode (Handle 'mode' from Manual, 'state' from Auto)
    let m = data.mode || data.state;
    if (m !== undefined) {
        // AutoPilot state can be 'AUTO_READY', 'AUTO_COOLDOWN' -> treat as 'AUTO'
        // But for UI display, we might want to show sub-state?
        // Let's normalize for the Mode Toggle Button logic
        currentMode = (m.toLowerCase().includes('auto')) ? 'auto' : 'manual';

        const modeDisplay = m.toUpperCase().replace('_', ' ');
        txtHudMode.innerText = modeDisplay;
        txtPanelMode.innerText = modeDisplay;

        // Update Auto Toggle Button Text
        if (currentMode === 'manual') {
            btnAuto.innerText = "Enable Auto Mode";
            btnAuto.classList.remove('active');
        } else {
            btnAuto.innerText = "Stop Auto Mode";
            btnAuto.classList.add('active');
        }
    }

    // 3. Pan / Tilt
    if (data.pan !== undefined) valPan.innerText = Math.round(data.pan);
    if (data.tilt !== undefined) valTilt.innerText = Math.round(data.tilt);
}

// --- Overlay Logic ---
function drawOverlay(data) {
    if (!data.frame_size) return;

    const [fw, fh] = data.frame_size;

    // Resize Canvas to match Frame Size (Backend Truth)
    if (canvas.width !== fw || canvas.height !== fh) {
        canvas.width = fw;
        canvas.height = fh;
    }

    // Sync Display Size with Image Element
    // This ensures coordinate translation is correct if we used click event on canvas
    canvas.style.width = imgStream.clientWidth + 'px';
    canvas.style.height = imgStream.clientHeight + 'px';

    ctx.clearRect(0, 0, fw, fh);

    // Draw ROI (Yellow)
    if (data.roi) {
        const [rx, ry] = data.roi;
        const r = data.roi_radius || 35;

        ctx.beginPath();
        ctx.strokeStyle = 'yellow';
        ctx.lineWidth = 2;
        // Draw Rect logic as per Plan, but data.roi is center point from calibration
        // Plan said "Draw ROI (Yellow Frame)" so lets draw Rect
        ctx.rect(rx - r, ry - r, r * 2, r * 2);
        ctx.stroke();

        // Center Dot (Hollow Circle)
        // ctx.fillStyle = 'yellow';
        // ctx.fillRect(rx - 2, ry - 2, 4, 4);
        ctx.beginPath();
        ctx.arc(rx, ry, 6, 0, 2 * Math.PI);
        ctx.strokeStyle = 'yellow';
        ctx.lineWidth = 2;
        ctx.stroke();
    }

    // Draw BBoxes (Red)
    if (data.bboxes && data.bboxes.length > 0) {
        ctx.strokeStyle = 'red';
        ctx.lineWidth = 2;
        data.bboxes.forEach(bbox => {
            const [bx, by, bw, bh] = bbox;
            ctx.strokeRect(bx, by, bw, bh);
        });
    }
}

// --- Canvas Interaction (Calibration / Mock) ---
canvas.addEventListener('click', (e) => {
    const rect = canvas.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;

    // Need to send SERVER coordinates?
    // The backend MockDetector expects CLIENT coordinates + Display Size.
    // The backend Calibration expects SERVER coordinates?
    // Let's look at app.py add_sample. It takes X/Y.
    // Ideally we should be consistent.
    // For Calibration, if we send X/Y, we should probably send SERVER coordinates if possible
    // OR send Client coords + Display Size and let server scale.
    // BUT `add_sample` in app.py just calls `calibration.add_sample` with X/Y. `CalibrationLogger` stores it.
    // If we store Client Coords, the calibration will be dependent on Browser Size. BAD.
    // WE MUST SCALE TO FRAME COORDS here or in backend.

    // Let's Scale to Frame Coords HERE for Calibration
    // frame_size is known if we received auto_status. If not, default 640x480.
    const fw = canvas.width || 640;
    const fh = canvas.height || 480;
    const dw = canvas.clientWidth;  // Display width
    const dh = canvas.clientHeight;

    const scaleX = fw / dw;
    const scaleY = fh / dh;

    const frameX = clickX * scaleX;
    const frameY = clickY * scaleY;

    if (calibMode !== 'none') {
        // Calibration Mode
        fetch('/api/calibration/sample', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                x: frameX,
                y: frameY,
                type: calibMode
            })
        })
            .then(r => r.json())
            .then(d => {
                sampleCount++;
                elCalibStatus.innerText = `Sample Added! Total: ${sampleCount}. (Aim -> Click Add again)`;
                elCalibStatus.style.color = "#0f0";
                calibMode = 'none'; // Auto-disarm for safety
            });
    } else {
        // Mock Detector Trigger (Simulate Cat)
        // Send Client Coords + Display Size as per `MockDetector` logic (which expects to do scaling itself)
        // Wait, app.py mock_detection calls detector.set_detection(x, y, w, h, FW, FH).
        // MockDetector uses FW/ClientW to scale.
        // So we should send Client Coords for Mock Detection.

        // Wait, if I shift-click, maybe? Or just click.
        fetch('/api/mock_detection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                x: clickX,
                y: clickY,
                w: 50, h: 50,
                display_w: dw,
                display_h: dh
            })
        });
    }
});

// --- UI Buttons ---
document.getElementById('btn-toggle-auto').addEventListener('click', () => {
    const newMode = (currentMode === 'manual') ? 'auto' : 'manual';
    socket.emit('set_mode', { mode: newMode });
});

// Calibration State
let sampleCount = 0;

document.getElementById('btn-calib-add').addEventListener('click', () => {
    calibMode = 'general';
    elCalibStatus.innerText = ">> CLICK ON LASER DOT IN VIDEO <<";
    elCalibStatus.style.color = "#0cf";
});

document.getElementById('btn-calib-reset').addEventListener('click', () => {
    if (!confirm("Clear all calibration points?")) return;

    fetch('/api/calibration/clear', { method: 'POST' })
        .then(r => r.json())
        .then(() => {
            sampleCount = 0;
            elCalibStatus.innerText = "Samples: 0";
            elCalibStatus.style.color = "#ffff00";
            calibMode = 'none';
        });
});

// Update Canvas Click to handle 'general' and update count
// ... (Logic is inside canvas.click, checking calibMode) ...
// We need to modify the canvas.click Handler in this file too? 
// The instruction above said "Rewrite calibration button handlers". 
// But I also need to update the canvas click response to increment count and reset mode.

// Let's modify the canvas click handler separately/here if it is within range?
// It was around line 163. The snippet target here is 235-245 (Buttons).
// So I will update buttons here.
// And I will let `canvas.click` stay mostly as is, BUT I need to update it to :
// 1. handle 'general' (it blindly sends `calibMode`).
// 2. update UI after add.
// Since separate edit, I will stick to buttons here, but I need to handle the UI update in the fetch result.
// But the fetch is in the `click` handler.
// So I should probably edit the `click` handler too.
// I can do multiple chunks? Yes.

// Chunk 1: Buttons
// Chunk 2: Canvas Click Handler update

// --- Safety Limits & Master Save ---
const badgeUnsaved = document.getElementById('badge-unsaved');
const valLimits = document.getElementById('lbl-limits');
const msgSave = document.getElementById('save-msg');

function setStatusUnsaved() {
    badgeUnsaved.style.display = 'inline-block';
    msgSave.innerText = '';
}

document.getElementById('btn-lim-tilt-min').addEventListener('click', () => {
    setLimit('tilt', 'min');
});
document.getElementById('btn-lim-tilt-max').addEventListener('click', () => {
    setLimit('tilt', 'max');
});

document.getElementById('btn-lim-pan-left').addEventListener('click', () => {
    setLimit('pan', 'max'); // Left is Max (180)
});
document.getElementById('btn-lim-pan-right').addEventListener('click', () => {
    setLimit('pan', 'min'); // Right is Min (0)
});

document.getElementById('btn-set-center').addEventListener('click', () => {
    fetch('/api/center/set', { method: 'POST' })
        .then(r => r.json())
        .then(d => {
            if (d.status === 'ok') {
                document.getElementById('center-msg').innerText =
                    `Center Set: P${Math.round(d.center[0])} T${Math.round(d.center[1])}`;
                setStatusUnsaved();
            }
        });
});

function setLimit(axis, type) {
    fetch('/api/limits/set', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ axis: axis, type: type })
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'ok') {
                const [min, max] = data.limits;
                // Simple feedback, maybe specific to axis
                valLimits.innerText = `${axis.toUpperCase()}: ${Math.round(min)}° ~ ${Math.round(max)}°`;
                setStatusUnsaved();
            } else {
                alert('Error: ' + data.msg);
            }
        });
}

document.getElementById('btn-save-all').addEventListener('click', () => {
    // 1. Commit Calibration (Fit) if pending
    fetch('/api/calibration/fit', { method: 'POST' })
        .then(r => r.json())
        .then(() => {
            // 2. Commit Config (Limits)
            return fetch('/api/config/save', { method: 'POST' });
        })
        .then(r => r.json())
        .then(d => {
            if (d.status === 'ok') {
                badgeUnsaved.style.display = 'none';
                msgSave.innerText = 'All Settings Saved!';
                calibMode = 'none';
                elCalibStatus.innerText = "System Ready";
                elCalibStatus.style.color = "#0f0";
            } else {
                alert("Save Failed: " + d.msg);
            }
        });
});

// --- Gamepad / Keyboard Events (Restored) ---
window.addEventListener("gamepadconnected", (e) => {
    gamepadIndex = e.gamepad.index;
    console.log("Gamepad connected:", e.gamepad.id);
});

window.addEventListener("gamepaddisconnected", (e) => {
    gamepadIndex = null;
    console.log("Gamepad disconnected");
});

let lastBtnA = false;
let lastBtnX = false;
const keys = { up: false, down: false, left: false, right: false };

window.addEventListener('keydown', (e) => {
    // Prevent default scrolling for arrow keys
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].indexOf(e.code) > -1) {
        e.preventDefault();
    }

    switch (e.key) {
        case 'ArrowUp': case 'w': case 'W': keys.up = true; break;
        case 'ArrowDown': case 's': case 'S': keys.down = true; break;
        case 'ArrowLeft': case 'a': case 'A': keys.left = true; break;
        case 'ArrowRight': case 'd': case 'D': keys.right = true; break;
        case ' ': socket.emit('toggle_laser'); break;
        case 'x': case 'X':
            // Toggle Mode
            const newMode = (currentMode === 'manual') ? 'auto' : 'manual';
            socket.emit('set_mode', { mode: newMode });
            break;
    }
});

window.addEventListener('keyup', (e) => {
    switch (e.key) {
        case 'ArrowUp': case 'w': case 'W': keys.up = false; break;
        case 'ArrowDown': case 's': case 'S': keys.down = false; break;
        case 'ArrowLeft': case 'a': case 'A': keys.left = false; break;
        case 'ArrowRight': case 'd': case 'D': keys.right = false; break;
    }
});

// --- Main Control Loop ---
let lastAxisEmit = 0;

function handleButtons(gp) {
    if (gp.buttons[0].pressed && !lastBtnA) {
        socket.emit('toggle_laser');
        lastBtnA = true;
    } else if (!gp.buttons[0].pressed) {
        lastBtnA = false;
    }

    if (gp.buttons[2].pressed && !lastBtnX) {
        // socket.emit('toggle_wobble'); 
        lastBtnX = true;
    } else if (!gp.buttons[2].pressed) {
        lastBtnX = false;
    }
}

function handleAxes(gp) {
    if (currentMode !== 'manual') return;
    const now = Date.now();
    if (now - lastAxisEmit < 20) return;

    const pan = gp.axes[0];
    const tilt = gp.axes[1];

    if (Math.abs(pan) > 0.05 || Math.abs(tilt) > 0.05) {
        socket.emit('joystick_control', { pan_axis: pan, tilt_axis: tilt });
        lastAxisEmit = now;
    }
}

function handleKeyboardAxes() {
    if (currentMode !== 'manual') return;
    const now = Date.now();
    if (now - lastAxisEmit < 20) return;

    let pan = 0;
    let tilt = 0;
    if (keys.left) pan -= 1;
    if (keys.right) pan += 1;
    if (keys.up) tilt -= 1;
    if (keys.down) tilt += 1;

    if (pan !== 0 || tilt !== 0) {
        socket.emit('joystick_control', { pan_axis: pan, tilt_axis: tilt });
        lastAxisEmit = now;
    }
}

function updateLoop() {
    // 1. Handle Gamepad
    if (gamepadIndex !== null) {
        const gp = navigator.getGamepads()[gamepadIndex];
        if (gp) {
            handleButtons(gp);
            handleAxes(gp);
        }
    }
    // 2. Handle Keyboard
    handleKeyboardAxes();
    requestAnimationFrame(updateLoop);
}

// Start Loop
updateLoop();

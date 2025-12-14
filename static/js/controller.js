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
    if (data.laser !== undefined) {
        const isOn = data.laser;
        // Panel Text
        txtPanelLaser.innerText = isOn ? "ON" : "OFF";
        txtPanelLaser.style.color = isOn ? "#f00" : "#fff";
        // HUD Dot
        if (isOn && elHudLaser) elHudLaser.classList.add('active'); // active=green? wait, laser is red usually.
        else if (elHudLaser) elHudLaser.classList.remove('active');

        // Wait, index.html CSS says .indicator.danger { background: #f00 }
        // Let's use 'danger' class for laser
        if (isOn && elHudLaser) elHudLaser.classList.add('danger');
        else if (elHudLaser) elHudLaser.classList.remove('danger');
    }
    if (data.mode !== undefined) {
        currentMode = data.mode;
        const modeStr = currentMode.toUpperCase();

        // Sync Both
        txtHudMode.innerText = modeStr;
        txtPanelMode.innerText = modeStr;

        // Update Auto Toggle Button Text
        if (currentMode === 'manual') {
            btnAuto.innerText = "Enable Auto Mode";
            btnAuto.classList.remove('active');
        } else {
            btnAuto.innerText = "Stop Auto Mode";
            btnAuto.classList.add('active');
        }
    }
    if (data.pan !== undefined) valPan.innerText = Math.round(data.pan);
    if (data.tilt !== undefined) valTilt.innerText = Math.round(data.tilt);
});

socket.on('auto_status', (data) => {
    // data: { state, bbox, roi, roi_radius, frame_size, ... }
    drawOverlay(data);
});

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

        // Center Dot
        ctx.fillStyle = 'yellow';
        ctx.fillRect(rx - 2, ry - 2, 4, 4);
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
                elCalibStatus.innerText = `Sample Added [${calibMode}] P:${Math.round(d.pan)} T:${Math.round(d.tilt)}`;
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

document.getElementById('btn-calib-x').addEventListener('click', () => {
    calibMode = 'x_calib';
    elCalibStatus.innerText = "Mode: X-Calib (Fix Tilt, Click Points)";
    elCalibStatus.style.color = "#0cf";
});

document.getElementById('btn-calib-y').addEventListener('click', () => {
    calibMode = 'y_calib';
    elCalibStatus.innerText = "Mode: Y-Calib (Fix Pan, Click Points)";
    elCalibStatus.style.color = "#0cf";
});

document.getElementById('btn-calib-save').addEventListener('click', () => {
    calibMode = 'none';
    fetch('/api/calibration/fit', { method: 'POST' })
        .then(r => r.json())
        .then(d => {
            elCalibStatus.innerText = "Calibration Saved!";
            elCalibStatus.style.color = "#0f0";
            console.log("Calibration Result:", d);
        });
});

// --- Gamepad / Keyboard Logic (Preserved) ---
// Button Mappings (Standard Xbox)
// 0: A, 1: B, 2: X, 3: Y
// Axes: 0: LeftX, 1: LeftY

window.addEventListener("gamepadconnected", (e) => {
    gamepadIndex = e.gamepad.index;
});

window.addEventListener("gamepaddisconnected", (e) => {
    gamepadIndex = null;
});

let lastBtnA = false;
let lastBtnX = false;
const keys = { up: false, down: false, left: false, right: false };

window.addEventListener('keydown', (e) => {
    switch (e.key) {
        case 'ArrowUp': case 'w': case 'W': keys.up = true; break;
        case 'ArrowDown': case 's': case 'S': keys.down = true; break;
        case 'ArrowLeft': case 'a': case 'A': keys.left = true; break;
        case 'ArrowRight': case 'd': case 'D': keys.right = true; break;
        case ' ': socket.emit('toggle_laser'); break;
        case 'x': case 'X':
            // Toggle Mode (Manual <-> Auto)
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

let lastAxisEmit = 0;

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

function handleButtons(gp) {
    if (gp.buttons[0].pressed && !lastBtnA) {
        socket.emit('toggle_laser');
        lastBtnA = true;
    } else if (!gp.buttons[0].pressed) {
        lastBtnA = false;
    }

    if (gp.buttons[2].pressed && !lastBtnX) {
        // socket.emit('toggle_wobble'); // Disable old wobble button
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

updateLoop();

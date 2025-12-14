const socket = io();

// State
let gamepadIndex = null;
let laserState = false;
let currentMode = 'manual';

// DOM Elements
const elConn = document.getElementById('status-conn');
const txtConn = document.getElementById('txt-conn');
const elLaser = document.getElementById('status-laser');
const txtMode = document.getElementById('txt-mode');
const valPan = document.getElementById('val-pan');
const valTilt = document.getElementById('val-tilt');
const imgStream = document.getElementById('video-stream');

// --- MJPEG Reconnection Logic (iPad Fix) ---
let streamErrors = 0;
let lastFrameTime = Date.now();

imgStream.onerror = () => {
    console.error("Video Stream Broken. Reconnecting...");
    streamErrors++;
    scheduleReconnect();
};

imgStream.onload = () => {
    lastFrameTime = Date.now();
    // Reset connection class if needed
};

// Watchdog: Check if frame hasn't updated in 5 seconds
setInterval(() => {
    if (Date.now() - lastFrameTime > 5000) {
        console.warn("Video Stalled (5s). Force reconnecting...");
        scheduleReconnect();
    }
}, 2000);

function scheduleReconnect() {
    // Basic backoff or immediate
    const delay = Math.min(streamErrors * 1000, 10000); // Capped at 10s
    setTimeout(() => {
        // Force browser to drop old connection by adding timestamp
        imgStream.src = `/video_feed?t=${Date.now()}`;
        lastFrameTime = Date.now(); // Prevent double trigger
        console.log(`Reconnecting video stream... (Attempt ${streamErrors})`);
    }, 1000);
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
        laserState = data.laser;
        if (laserState) elLaser.classList.add('danger');
        else elLaser.classList.remove('danger');
    }
    if (data.mode !== undefined) {
        currentMode = data.mode;
        txtMode.innerText = currentMode.toUpperCase();
    }
    if (data.pan !== undefined) valPan.innerText = Math.round(data.pan);
    if (data.tilt !== undefined) valTilt.innerText = Math.round(data.tilt);
});

// --- Gamepad API ---

window.addEventListener("gamepadconnected", (e) => {
    console.log("Gamepad connected at index %d: %s. %d buttons, %d axes.",
        e.gamepad.index, e.gamepad.id,
        e.gamepad.buttons.length, e.gamepad.axes.length);
    gamepadIndex = e.gamepad.index;
    txtConn.innerText += " + Gamepad";
});

window.addEventListener("gamepaddisconnected", (e) => {
    console.log("Gamepad disconnected from index %d: %s",
        e.gamepad.index, e.gamepad.id);
    gamepadIndex = null;
});

// Button Mappings (Standard Xbox)
// 0: A, 1: B, 2: X, 3: Y
// Axes: 0: LeftX, 1: LeftY

let lastBtnA = false;
let lastBtnX = false;

// Keyboard State
const keys = {
    up: false,
    down: false,
    left: false,
    right: false
};

window.addEventListener('keydown', (e) => {
    console.log("Key pressed:", e.key); // Debug Log
    switch (e.key) {
        case 'ArrowUp': case 'w': case 'W': keys.up = true; break;
        case 'ArrowDown': case 's': case 'S': keys.down = true; break;
        case 'ArrowLeft': case 'a': case 'A': keys.left = true; break;
        case 'ArrowRight': case 'd': case 'D': keys.right = true; break;
        case ' ': // Space for Laser
            socket.emit('toggle_laser');
            break;
        case 'x': case 'X': // X for Wobble
            socket.emit('toggle_wobble');
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
    // 1. Handle Gamepad Input
    if (gamepadIndex !== null) {
        const gp = navigator.getGamepads()[gamepadIndex];
        if (gp) {
            handleButtons(gp);
            handleAxes(gp);
        }
    }

    // 2. Handle Keyboard Input (if no gamepad input or mixed)
    // We run this every loop to allow smooth holding of keys
    handleKeyboardAxes();

    requestAnimationFrame(updateLoop);
}

function handleButtons(gp) {
    // Button A: Toggle Laser
    if (gp.buttons[0].pressed) {
        if (!lastBtnA) {
            socket.emit('toggle_laser');
            lastBtnA = true;
        }
    } else {
        lastBtnA = false;
    }

    // Button X: Toggle Wobble
    if (gp.buttons[2].pressed) {
        if (!lastBtnX) {
            socket.emit('toggle_wobble');
            lastBtnX = true;
        }
    } else {
        lastBtnX = false;
    }
}

function handleAxes(gp) {
    if (currentMode !== 'manual') return;

    // Rate limiting emission to ~20ms (50Hz)
    const now = Date.now();
    if (now - lastAxisEmit < 20) return;

    const pan = gp.axes[0]; // Left Stick X
    const tilt = gp.axes[1]; // Left Stick Y

    if (Math.abs(pan) > 0.05 || Math.abs(tilt) > 0.05) {
        socket.emit('joystick_control', {
            pan_axis: pan,
            tilt_axis: tilt
        });
        lastAxisEmit = now;
    }
}

function handleKeyboardAxes() {
    if (currentMode !== 'manual') return;

    // Rate limiting
    const now = Date.now();
    if (now - lastAxisEmit < 20) return;

    let pan = 0;
    let tilt = 0;

    if (keys.left) pan -= 1;
    if (keys.right) pan += 1;
    if (keys.up) tilt -= 1;   // Up usually means tilt up (servo angle change depends on mounting)
    if (keys.down) tilt += 1;

    // If keyboard is active
    if (pan !== 0 || tilt !== 0) {
        console.log("Sending Keyboard Joystick: Pan", pan, "Tilt", tilt); // Debug Log
        socket.emit('joystick_control', {
            pan_axis: pan,
            tilt_axis: tilt
        });
        lastAxisEmit = now;
    }
}

// Start loop immediately
updateLoop();

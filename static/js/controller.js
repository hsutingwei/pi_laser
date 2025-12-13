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
    requestAnimationFrame(updateLoop);
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

function updateLoop() {
    if (gamepadIndex !== null) {
        const gp = navigator.getGamepads()[gamepadIndex];
        if (gp) {
            handleButtons(gp);
            handleAxes(gp);
        }
    }
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

let lastAxisEmit = 0;

function handleAxes(gp) {
    if (currentMode !== 'manual') return;

    // Rate limiting emission to ~20ms (50Hz) to avoid flooding socket
    const now = Date.now();
    if (now - lastAxisEmit < 20) return;

    const pan = gp.axes[0]; // Left Stick X
    const tilt = gp.axes[1]; // Left Stick Y
    
    // Deadzone check moved to backend or done here?
    // Let's do a simple check here to save bandwidth
    if (Math.abs(pan) > 0.05 || Math.abs(tilt) > 0.05) {
        socket.emit('joystick_control', {
            pan_axis: pan,
            tilt_axis: tilt
        });
        lastAxisEmit = now;
    }
}

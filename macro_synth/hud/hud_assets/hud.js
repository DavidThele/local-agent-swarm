let currentMode = "hidden";
let addedContext = [];
let candidateLabel = "";
let arcItemElements = new Map();

// -----------------------------------------------------------------------------
// AUDIO SPECTRUM ORBIT PARTICLES (CUSTOMIZABLE CONFIG)
// -----------------------------------------------------------------------------
const SPECTRUM_CONFIG = {
  dotCount: 52,            // Customizable density of dots
  amplitude: 14.0,         // Customizable pulse displacement/scale sensitivity
  baseRadius: 2.2,         // Default dot radius (px)
  orbitSpeed: 0.004,       // Angular velocity of the slow spin around the box
  boxWidth: 400,
  boxHeight: 44,
  centerOffsetX: 20,
  centerOffsetY: 38,
  color: "rgba(145, 185, 255, " // Soft modern blue-white glow
};

let isListening = false;
let audioBands = [0, 0, 0, 0, 0, 0, 0, 0];
let currentRotation = 0;
let particles = [];

const canvas = document.getElementById("audio-dots-canvas");
const ctx = canvas.getContext("2d");

function initParticles() {
  particles = [];
  const perimeter = 2 * (SPECTRUM_CONFIG.boxWidth - 44) + 2 * Math.PI * 22;
  
  for (let i = 0; i < SPECTRUM_CONFIG.dotCount; i++) {
    const t = Math.random(); // Position along rounded boundary
    const bandIdx = Math.floor(Math.random() * 8); // Assigned audio frequency band
    const radialOffset = (Math.random() - 0.5) * 8; // Random jitter around boundary
    const phaseOffset = Math.random() * Math.PI * 2;
    particles.push({ t, bandIdx, radialOffset, phaseOffset });
  }
}
initParticles();

function getRoundedRectPoint(progress, rx, ry, w, h) {
  // Returns (x, y) and normal angle along rounded stadium pill
  const r = h / 2;
  const straightW = w - 2 * r;
  const totalP = 2 * straightW + 2 * Math.PI * r;
  let d = ((progress % 1) + 1) % 1 * totalP;

  if (d < straightW) {
    // Top edge
    return { x: rx + r + d, y: ry, nx: 0, ny: -1 };
  }
  d -= straightW;
  if (d < Math.PI * r) {
    // Right cap
    const angle = -Math.PI / 2 + d / r;
    return { x: rx + w - r + r * Math.cos(angle), y: ry + r + r * Math.sin(angle), nx: Math.cos(angle), ny: Math.sin(angle) };
  }
  d -= Math.PI * r;
  if (d < straightW) {
    // Bottom edge
    return { x: rx + w - r - d, y: ry + h, nx: 0, ny: 1 };
  }
  d -= straightW;
  // Left cap
  const angle = Math.PI / 2 + d / r;
  return { x: rx + r + r * Math.cos(angle), y: ry + r + r * Math.sin(angle), nx: Math.cos(angle), ny: Math.sin(angle) };
}

function renderAudioDots() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (isListening) {
    currentRotation = (currentRotation + SPECTRUM_CONFIG.orbitSpeed) % 1.0;
    const rx = SPECTRUM_CONFIG.centerOffsetX;
    const ry = SPECTRUM_CONFIG.centerOffsetY;
    const w = SPECTRUM_CONFIG.boxWidth;
    const h = SPECTRUM_CONFIG.boxHeight;

    particles.forEach(p => {
      const livePos = (p.t + currentRotation) % 1.0;
      const pt = getRoundedRectPoint(livePos, rx, ry, w, h);
      const bandEnergy = audioBands[p.bandIdx] || 0;

      // Pulse calculation
      const pulse = bandEnergy * SPECTRUM_CONFIG.amplitude;
      const x = pt.x + pt.nx * (p.radialOffset + pulse);
      const y = pt.y + pt.ny * (p.radialOffset + pulse);
      const size = SPECTRUM_CONFIG.baseRadius + bandEnergy * 2.5;
      const alpha = 0.25 + bandEnergy * 0.75;

      ctx.beginPath();
      ctx.arc(x, y, Math.max(0.5, size), 0, Math.PI * 2);
      ctx.fillStyle = `${SPECTRUM_CONFIG.color}${alpha.toFixed(2)})`;
      ctx.shadowColor = "rgba(100, 160, 255, 0.6)";
      ctx.shadowBlur = 6 * bandEnergy;
      ctx.fill();
    });
  }

  requestAnimationFrame(renderAudioDots);
}
requestAnimationFrame(renderAudioDots);

window.setAudioLevels = function(bands) {
  if (Array.isArray(bands)) {
    audioBands = bands;
  }
};

window.setListeningActive = function(active) {
  isListening = active;
  if (active) {
    canvas.classList.add("active");
  } else {
    canvas.classList.remove("active");
    audioBands = [0, 0, 0, 0, 0, 0, 0, 0];
  }
};

window.appendTranscript = function(spokenText) {
  if (!isListening) return;
  // If the user hasn't typed over, display spoken text directly
  hudInput.value = spokenText;
};

// -----------------------------------------------------------------------------
// EVENT HANDLING & KEYSTROKE DISCRIMINATOR
// -----------------------------------------------------------------------------
function postToPython(payload) {
  if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.hudBridge) {
    window.webkit.messageHandlers.hudBridge.postMessage(JSON.stringify(payload));
  }
}

const hudRoot = document.getElementById("hud-root");
const hudInput = document.getElementById("hud-input");
const statusLabel = document.getElementById("status-label");
const submitBtn = document.getElementById("submit-btn");
const spinnerIcon = document.getElementById("spinner-icon");
const contextStack = document.getElementById("context-stack");
const wheelWrapper = document.getElementById("wheel-wrapper");
const wheelSlots = document.getElementById("wheel-slots");

hudInput.addEventListener("keydown", (e) => {
  // C) Enter submits immediately
  if (e.key === "Enter") {
    e.preventDefault();
    if (isListening) {
      postToPython({ type: "stop_listening" });
    }
    triggerSubmit();
    return;
  }

  // A) Escape cancels prompt
  if (e.key === "Escape") {
    e.preventDefault();
    if (isListening) {
      postToPython({ type: "stop_listening" });
    }
    if (currentMode === "prompt") {
      postToPython({ type: "cancel_prompt" });
    } else if (currentMode === "feedback") {
      postToPython({ type: "dismiss_feedback" });
    }
    return;
  }

  // B) Keystroke discriminator:
  // If user holds Command (Meta) or Control (e.g. Cmd+W, Cmd+A, Cmd+C), do NOT stop listening
  if (e.metaKey || e.ctrlKey) {
    return;
  }

  // Pure modifier keys (Shift, Alt, Fn) do not constitute typing
  if (["Shift", "Alt", "CapsLock", "Meta", "Control", "Fn"].includes(e.key)) {
    return;
  }

  // If user presses alphanumeric keys, space, backspace, or symbols: stop voice listening immediately
  if (isListening) {
    postToPython({ type: "stop_listening" });
    window.setListeningActive(false);
  }
});

hudInput.addEventListener("blur", () => {
  if (currentMode === "feedback") {
    postToPython({ type: "dismiss_feedback" });
  }
});

submitBtn.addEventListener("click", () => {
  if (isListening) {
    postToPython({ type: "stop_listening" });
  }
  triggerSubmit();
});

function triggerSubmit() {
  const val = hudInput.value || "";
  if (currentMode === "prompt") {
    postToPython({ type: "submit_prompt", text: val });
  } else if (currentMode === "feedback") {
    postToPython({ type: "submit_feedback", text: val });
  }
}

function renderContextPills() {
  contextStack.innerHTML = "";

  addedContext.forEach((label, idx) => {
    const pill = document.createElement("div");
    pill.className = "ctx-pill";
    pill.innerHTML = `<span class="ctx-symbol remove">&times;</span><span class="ctx-label"></span>`;
    pill.querySelector(".ctx-label").textContent = label;
    pill.addEventListener("click", () => {
      pill.classList.add("removing");
      setTimeout(() => {
        postToPython({ type: "remove_context", index: idx });
      }, 200);
    });
    contextStack.appendChild(pill);
  });

  if (candidateLabel) {
    const addPill = document.createElement("div");
    addPill.className = "ctx-pill";
    addPill.innerHTML = `<span class="ctx-symbol add">+</span><span class="ctx-label"></span>`;
    addPill.querySelector(".ctx-label").textContent = candidateLabel;
    addPill.addEventListener("click", () => {
      postToPython({ type: "add_context" });
    });
    contextStack.appendChild(addPill);
  }
}

// Elliptical arc actions rendering
const ARC_CX = 158;
const ARC_CY = 6;
const ARC_RX = 132;
const ARC_RY = 49;
const SLOT_ANGLES_DEG = {
  "-3": 176,
  "-2": 152,
  "-1": 124,
  "0":  90,
  "1":  56,
  "2":  28,
  "3":  4
};

function computeSlotPose(slotIndex) {
  const clamped = Math.max(-3, Math.min(3, slotIndex));
  const deg = SLOT_ANGLES_DEG[String(clamped)];
  const rad = (deg * Math.PI) / 180.0;
  const x = ARC_CX + ARC_RX * Math.cos(rad);
  const y = ARC_CY + ARC_RY * Math.sin(rad);

  const dx = -ARC_RX * Math.sin(rad);
  const dy = ARC_RY * Math.cos(rad);
  let rotDeg = Math.atan2(dy, dx) * (180.0 / Math.PI);
  if (rotDeg > 90) rotDeg -= 180;
  if (rotDeg < -90) rotDeg += 180;
  rotDeg *= 0.85;

  const visible = Math.abs(slotIndex) <= 2;
  const scale = visible ? (slotIndex === 0 ? 1.04 : 0.96) : 0.65;
  const opacity = visible ? 1.0 : 0.0;
  return { x, y, rotDeg, scale, opacity };
}

function renderArcActions(actions) {
  if (!actions || actions.length === 0) {
    wheelWrapper.classList.remove("visible");
    return;
  }
  wheelWrapper.classList.add("visible");

  let centerIdx = actions.findIndex(a => a.state === "active");
  if (centerIdx === -1) {
    let lastDone = -1;
    for (let i = 0; i < actions.length; i++) {
      if (actions[i].state === "done") lastDone = i;
    }
    centerIdx = lastDone !== -1 ? Math.min(actions.length - 1, lastDone + 1) : 0;
  }

  const activeIds = new Set();
  actions.forEach((act, idx) => {
    const id = String(idx);
    activeIds.add(id);

    const slotOffset = centerIdx - idx;
    const pose = computeSlotPose(slotOffset);

    let el = arcItemElements.get(id);
    if (!el) {
      el = document.createElement("div");
      el.className = "arc-item pending";
      const enterPose = computeSlotPose(-3);
      el.style.transform = `translate(${enterPose.x}px, ${enterPose.y}px) translate(-50%, -50%) rotate(${enterPose.rotDeg}deg) scale(${enterPose.scale})`;
      el.style.opacity = "0";
      wheelSlots.appendChild(el);
      arcItemElements.set(id, el);
      void el.offsetWidth;
    }

    el.textContent = act.label || `Step ${idx + 1}`;
    let visualState = act.state || "pending";
    if (slotOffset > 0 && visualState !== "aborted") {
      visualState = "done";
    } else if (slotOffset === 0 && visualState === "pending") {
      visualState = "active";
    }

    el.className = `arc-item ${visualState}`;
    el.style.transform = `translate(${pose.x}px, ${pose.y}px) translate(-50%, -50%) rotate(${pose.rotDeg}deg) scale(${pose.scale})`;
    el.style.opacity = String(pose.opacity);
    el.style.zIndex = String(10 - Math.abs(slotOffset));
  });

  for (const [id, el] of arcItemElements.entries()) {
    if (!activeIds.has(id)) {
      el.remove();
      arcItemElements.delete(id);
    }
  }
}

window.updateHUD = function(state) {
  if (state.scale !== undefined) {
    document.documentElement.style.setProperty("--scale", String(state.scale));
  }

  const prevMode = currentMode;
  if (state.mode) {
    currentMode = state.mode;
  }

  if (currentMode === "hidden") {
    hudRoot.classList.add("hud-hidden");
    wheelWrapper.classList.remove("visible");
    window.setListeningActive(false);
    return;
  } else {
    hudRoot.classList.remove("hud-hidden");
  }

  if (state.addedContext !== undefined) {
    addedContext = state.addedContext;
  }
  if (state.candidateLabel !== undefined) {
    candidateLabel = state.candidateLabel;
  }

  if (currentMode === "prompt") {
    hudInput.classList.remove("hidden");
    statusLabel.classList.add("hidden");
    hudInput.placeholder = "Specify request...";
    if (prevMode !== "prompt" || state.clearInput) {
      hudInput.value = "";
    }
    if (state.focusInput) {
      setTimeout(() => hudInput.focus(), 30);
    }

    submitBtn.classList.remove("hidden");
    spinnerIcon.classList.add("hidden");
    contextStack.classList.remove("hidden");
    wheelWrapper.classList.remove("visible");
    renderContextPills();

  } else if (currentMode === "loading") {
    window.setListeningActive(false);
    hudInput.classList.add("hidden");
    statusLabel.classList.remove("hidden");
    statusLabel.textContent = state.statusText || "Processing...";

    submitBtn.classList.add("hidden");
    spinnerIcon.classList.remove("hidden");
    contextStack.classList.add("hidden");
    wheelWrapper.classList.remove("visible");

  } else if (currentMode === "running") {
    window.setListeningActive(false);
    hudInput.classList.add("hidden");
    statusLabel.classList.remove("hidden");
    statusLabel.textContent = state.statusText || "Processing...";

    submitBtn.classList.add("hidden");
    spinnerIcon.classList.remove("hidden");
    contextStack.classList.add("hidden");
    renderArcActions(state.actions || []);

  } else if (currentMode === "feedback") {
    window.setListeningActive(false);
    hudInput.classList.remove("hidden");
    statusLabel.classList.add("hidden");
    hudInput.placeholder = "Enter feedback...";
    if (prevMode !== "feedback" || state.clearInput) {
      hudInput.value = "";
    }
    if (state.focusInput) {
      setTimeout(() => hudInput.focus(), 30);
    }

    submitBtn.classList.remove("hidden");
    spinnerIcon.classList.add("hidden");
    contextStack.classList.add("hidden");
    wheelWrapper.classList.remove("visible");
  }
};
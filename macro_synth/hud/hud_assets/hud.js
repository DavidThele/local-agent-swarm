let currentMode = "hidden"; // "prompt", "loading", "running", "feedback", "hidden"
let addedContext = [];
let candidateLabel = "";
let arcItemElements = new Map();

// Elliptical arc geometry for the 5 slots (left-to-right: 1-2 upcoming, 3 active, 4-5 done)
// Slot index: -2 (far left), -1 (mid left), 0 (center active), +1 (mid right), +2 (far right)
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

  // Tangent angle along the bottom of the ellipse so pills curve naturally
  const dx = -ARC_RX * Math.sin(rad);
  const dy = ARC_RY * Math.cos(rad);
  let rotDeg = Math.atan2(dy, dx) * (180.0 / Math.PI);
  if (rotDeg > 90) rotDeg -= 180;
  if (rotDeg < -90) rotDeg += 180;
  // Subtle damping so outer pills match the Figma mockup angle
  rotDeg *= 0.85;

  const visible = Math.abs(slotIndex) <= 2;
  const scale = visible ? (slotIndex === 0 ? 1.04 : 0.96) : 0.65;
  const opacity = visible ? 1.0 : 0.0;

  return { x, y, rotDeg, scale, opacity };
}

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
  if (e.key === "Enter") {
    e.preventDefault();
    triggerSubmit();
  } else if (e.key === "Escape") {
    e.preventDefault();
    if (currentMode === "prompt") {
      postToPython({ type: "cancel_prompt" });
    } else if (currentMode === "feedback") {
      triggerSubmit();
    }
  }
});

submitBtn.addEventListener("click", () => {
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

  // Added context pages with red '×'
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

  // Bottom dynamic active external window/app with green '+'
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

function renderArcActions(actions) {
  if (!actions || actions.length === 0) {
    wheelWrapper.classList.remove("visible");
    return;
  }

  wheelWrapper.classList.add("visible");

  // Determine center index (currently executing 'active' action)
  let centerIdx = actions.findIndex(a => a.state === "active");
  if (centerIdx === -1) {
    let lastDone = -1;
    for (let i = 0; i < actions.length; i++) {
      if (actions[i].state === "done") lastDone = i;
    }
    if (lastDone !== -1) {
      centerIdx = Math.min(actions.length - 1, lastDone + 1);
    } else {
      centerIdx = 0;
    }
  }

  const activeIds = new Set();

  actions.forEach((act, idx) => {
    const id = String(idx);
    activeIds.add(id);

    // Left-to-right flow:
    // Upcoming actions (idx > centerIdx) sit on the left (negative slotOffset: -2, -1)
    // Center executing action (idx === centerIdx) sits at bottom center (slotOffset: 0)
    // Completed actions (idx < centerIdx) rotate to the right (positive slotOffset: +1, +2) and turn green
    const slotOffset = centerIdx - idx;
    const pose = computeSlotPose(slotOffset);

    let el = arcItemElements.get(id);
    if (!el) {
      el = document.createElement("div");
      el.className = "arc-item pending";
      // Spawn from the left entrance of the wheel so new items rotate in smoothly
      const enterPose = computeSlotPose(-3);
      el.style.transform = `translate(${enterPose.x}px, ${enterPose.y}px) translate(-50%, -50%) rotate(${enterPose.rotDeg}deg) scale(${enterPose.scale})`;
      el.style.opacity = "0";
      wheelSlots.appendChild(el);
      arcItemElements.set(id, el);
      // Force reflow so the transition animates smoothly to target slot
      void el.offsetWidth;
    }

    el.textContent = act.label || `Step ${idx + 1}`;

    let visualState = act.state || "pending";
    if (slotOffset > 0 && visualState !== "aborted") {
      // Past the middle point -> filled with green
      visualState = "done";
    } else if (slotOffset === 0 && visualState === "pending") {
      visualState = "active";
    }

    el.className = `arc-item ${visualState}`;
    el.style.transform = `translate(${pose.x}px, ${pose.y}px) translate(-50%, -50%) rotate(${pose.rotDeg}deg) scale(${pose.scale})`;
    el.style.opacity = String(pose.opacity);
    el.style.zIndex = String(10 - Math.abs(slotOffset));
  });

  // Clean up removed action nodes
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
    hudInput.classList.add("hidden");
    statusLabel.classList.remove("hidden");
    statusLabel.textContent = state.statusText || "Processing...";

    submitBtn.classList.add("hidden");
    spinnerIcon.classList.remove("hidden");
    contextStack.classList.add("hidden");
    wheelWrapper.classList.remove("visible");

  } else if (currentMode === "running") {
    hudInput.classList.add("hidden");
    statusLabel.classList.remove("hidden");
    statusLabel.textContent = state.statusText || "Processing...";

    submitBtn.classList.add("hidden");
    spinnerIcon.classList.remove("hidden");
    contextStack.classList.add("hidden");
    renderArcActions(state.actions || []);

  } else if (currentMode === "feedback") {
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
let modalState = null;
let inputUnlockedAt = 0;
let guardTimer = null;

const modalCard = document.getElementById("modal-card");
const modalBadge = document.getElementById("modal-badge");
const modalAgent = document.getElementById("modal-agent");
const modalQuestion = document.getElementById("modal-question");
const modalPreview = document.getElementById("modal-preview");
const modalOptions = document.getElementById("modal-options");
const modalScroll = document.getElementById("modal-scroll");
const modalOtherRow = document.getElementById("modal-other-row");
const modalOtherInput = document.getElementById("modal-other-input");
const modalSubmitBtn = document.getElementById("modal-submit-btn");

function postToPython(payload) {
  if (
    window.webkit &&
    window.webkit.messageHandlers &&
    window.webkit.messageHandlers.modalBridge
  ) {
    window.webkit.messageHandlers.modalBridge.postMessage(JSON.stringify(payload));
  }
}

function isInputReady() {
  return modalState !== null && performance.now() >= inputUnlockedAt;
}

function submitOption(index) {
  if (!isInputReady() || !modalState) return;
  const opts = modalState.options || [];
  if (index < 0 || index >= opts.length) return;
  const chosen = opts[index];
  postToPython({
    type: "select_option",
    index: index,
    value: chosen.value,
    action: chosen.action || "answer",
  });
}

function submitCustomText() {
  if (!isInputReady() || !modalState) return;
  const text = (modalOtherInput.value || "").trim();
  if (!text) return;
  postToPython({
    type: "submit_other",
    value: text,
    action: "answer",
  });
}

function dismissModal() {
  if (!isInputReady() || !modalState) return;
  postToPython({ type: "dismiss" });
}

function reportSize() {
  if (!modalState) return;
  const maxCardHeight = modalState.maxCardHeight || 600;
  // Reset scroll max-height briefly to measure natural height
  modalScroll.style.maxHeight = "none";
  const naturalHeight = Math.ceil(modalCard.scrollHeight);
  const clampedCard = Math.min(naturalHeight, maxCardHeight);

  if (naturalHeight > maxCardHeight) {
    const headerH = document.getElementById("modal-header").offsetHeight || 20;
    const otherH = modalOtherRow.classList.contains("hidden")
      ? 0
      : (modalOtherRow.offsetHeight || 38) + 10;
    const chromeH = headerH + otherH + 40;
    modalScroll.style.maxHeight = `${Math.max(120, maxCardHeight - chromeH)}px`;
  } else {
    modalScroll.style.maxHeight = "none";
  }

  postToPython({ type: "resize", height: clampedCard + 28 });
}

window.showModal = function (payload) {
  if (guardTimer) {
    clearTimeout(guardTimer);
    guardTimer = null;
  }

  modalState = payload;
  const guardMs = typeof payload.guardMs === "number" ? payload.guardMs : 500;
  inputUnlockedAt = performance.now() + guardMs;

  if (payload.scale) {
    document.documentElement.style.setProperty("--scale", String(payload.scale));
  }

  const blockerType = payload.blockerType || "Question";
  modalBadge.textContent = blockerType;
  modalBadge.classList.toggle("security", blockerType === "Security");
  modalAgent.textContent = payload.agentId ? `(${payload.agentId})` : "";
  modalQuestion.textContent = payload.promptText || "";

  if (payload.commandPreview) {
    modalPreview.textContent = payload.commandPreview;
    modalPreview.classList.remove("hidden");
  } else {
    modalPreview.textContent = "";
    modalPreview.classList.add("hidden");
  }

  modalOptions.innerHTML = "";
  const options = payload.options || [];
  options.forEach((opt, idx) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "option-btn";
    if (opt.style === "approve") btn.classList.add("approve");
    if (opt.style === "deny") btn.classList.add("deny");

    const keySpan = document.createElement("span");
    keySpan.className = "option-key";
    keySpan.textContent = idx < 9 ? `⌘${idx + 1}` : `${idx + 1}.`;

    const labelSpan = document.createElement("span");
    labelSpan.className = "option-label";
    labelSpan.textContent = opt.label;

    btn.appendChild(keySpan);
    btn.appendChild(labelSpan);
    btn.addEventListener("click", () => submitOption(idx));
    modalOptions.appendChild(btn);
  });

  modalOtherInput.value = "";
  if (payload.allowOther) {
    modalOtherRow.classList.remove("hidden");
  } else {
    modalOtherRow.classList.add("hidden");
  }

  modalCard.classList.add("input-guarded");
  modalCard.classList.remove("modal-hidden");

  requestAnimationFrame(() => {
    reportSize();
  });

  guardTimer = setTimeout(() => {
    modalCard.classList.remove("input-guarded");
    if (payload.allowOther) {
      modalOtherInput.focus();
    }
  }, guardMs);
};

window.hideModal = function () {
  if (guardTimer) {
    clearTimeout(guardTimer);
    guardTimer = null;
  }
  modalState = null;
  modalCard.classList.add("modal-hidden");
  modalCard.classList.add("input-guarded");
};

window.focusOtherInput = function () {
  if (modalState && modalState.allowOther && isInputReady()) {
    modalOtherInput.focus();
  }
};

window.selectNumberedOptionFromNative = function (num) {
  submitOption(num - 1);
};

modalOtherInput.addEventListener("keydown", (e) => {
  if (!isInputReady()) {
    e.preventDefault();
    return;
  }
  if (e.key === "Enter") {
    e.preventDefault();
    submitCustomText();
  }
});

modalSubmitBtn.addEventListener("click", () => {
  submitCustomText();
});

document.addEventListener(
  "keydown",
  (e) => {
    if (!isInputReady()) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      dismissModal();
      return;
    }
    if (e.metaKey && !e.ctrlKey && !e.altKey) {
      const digit = parseInt(e.key, 10);
      if (digit >= 1 && digit <= 9) {
        e.preventDefault();
        submitOption(digit - 1);
      }
    }
  },
  true
);

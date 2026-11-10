"""Native macOS Speech Recognition and real-time audio analysis via PyObjC."""

import math
import struct
import threading
from typing import Callable

import objc
from AppKit import NSRunLoop, NSDefaultRunLoopMode

# Load Frameworks
objc.loadBundle(
    "AVFoundation",
    bundle_path="/System/Library/Frameworks/AVFoundation.framework",
    module_globals=globals(),
)
try:
    objc.loadBundle(
        "Speech",
        bundle_path="/System/Library/Frameworks/Speech.framework",
        module_globals=globals(),
    )
except Exception:
    pass

# -----------------------------------------------------------------------------
# PyObjC Block Signature Registration
# -----------------------------------------------------------------------------
try:
    objc.registerMetaDataForSelector(
        b"AVAudioNode",
        b"installTapOnBus:bufferSize:format:block:",
        {
            "arguments": {
                5: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"@"},
                            2: {"type": b"@"},
                        },
                    }
                }
            }
        },
    )
except Exception:
    pass

try:
    objc.registerMetaDataForSelector(
        b"SFSpeechRecognizer",
        b"requestAuthorization:",
        {
            "arguments": {
                2: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"q"},
                        },
                    }
                }
            }
        },
    )
except Exception:
    pass

try:
    objc.registerMetaDataForSelector(
        b"SFSpeechRecognizer",
        b"recognitionTaskWithRequest:resultHandler:",
        {
            "arguments": {
                3: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"@"},
                            2: {"type": b"@"},
                        },
                    }
                }
            }
        },
    )
except Exception:
    pass

# AVCaptureDevice requestAccessForMediaType:completionHandler:
try:
    objc.registerMetaDataForSelector(
        b"AVCaptureDevice",
        b"requestAccessForMediaType:completionHandler:",
        {
            "arguments": {
                3: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"Z"},  # BOOL granted
                        },
                    }
                }
            }
        },
    )
except Exception:
    pass

from infrastructure.debugging import debug_print


class NativeSpeechEngine:
    def __init__(
        self,
        on_partial_text: Callable[[str], None],
        on_audio_levels: Callable[[list[float]], None],
    ):
        self.on_partial_text = on_partial_text
        self.on_audio_levels = on_audio_levels

        self.audio_engine = None
        self.speech_recognizer = None
        self.recognition_request = None
        self.recognition_task = None

        self._is_running = False
        self._lock = threading.Lock()

    def request_permissions(self):
        """Explicitly triggers both Speech and Microphone permission popups if needed."""
        # 1. Microphone authorization check
        try:
            # AVMediaTypeAudio is 'soun'
            AVMediaTypeAudio = "soun"
            status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
            # 0 = NotDetermined
            if status == 0:
                debug_print("[Speech] Prompting for microphone permission...", "info")
                def _mic_handler(granted):
                    debug_print(f"[Speech] Microphone permission response: {granted}", "info")
                AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, _mic_handler)
        except Exception as exc:
            debug_print(f"[Speech] Mic permission check warning: {exc}", "warning")

        # 2. Speech Recognition authorization check
        try:
            s_status = SFSpeechRecognizer.authorizationStatus()
            if s_status == 0:
                debug_print("[Speech] Prompting for speech recognition permission...", "info")
                def _speech_handler(status):
                    debug_print(f"[Speech] Speech recognition permission response: {status}", "info")
                SFSpeechRecognizer.requestAuthorization_(_speech_handler)
        except Exception as exc:
            debug_print(f"[Speech] Speech permission check warning: {exc}", "warning")

    def start(self):
        with self._lock:
            if self._is_running:
                return

            try:
                self.request_permissions()

                self.speech_recognizer = SFSpeechRecognizer.alloc().init()
                if not self.speech_recognizer or not self.speech_recognizer.isAvailable():
                    debug_print("[Speech] SFSpeechRecognizer is unavailable or offline.", "warning")
                    return

                self.audio_engine = AVAudioEngine.alloc().init()
                input_node = self.audio_engine.inputNode()
                recording_format = input_node.outputFormatForBus_(0)

                # Ensure valid channel and sample rate
                if recording_format.sampleRate() == 0:
                    debug_print("[Speech] Audio input node returned 0 sample rate. Microphone may be muted or denied.", "error")
                    return

                self.recognition_request = SFSpeechAudioBufferRecognitionRequest.alloc().init()
                self.recognition_request.setShouldReportPartialResults_(True)
                
                # Force on-device if available to eliminate network delays
                if hasattr(self.recognition_request, "setRequiresOnDeviceRecognition_"):
                    if self.speech_recognizer.supportsOnDeviceRecognition():
                        self.recognition_request.setRequiresOnDeviceRecognition_(True)

                def _result_handler(result, error):
                    if error:
                        return
                    if result:
                        best = result.bestTranscription()
                        if best:
                            text = str(best.formattedString())
                            if self.on_partial_text:
                                self.on_partial_text(text)

                self.recognition_task = (
                    self.speech_recognizer.recognitionTaskWithRequest_resultHandler_(
                        self.recognition_request, _result_handler
                    )
                )

                def _buffer_tap(buffer, when):
                    if not self._is_running:
                        return
                    if self.recognition_request:
                        self.recognition_request.appendAudioPCMBuffer_(buffer)

                    bands = self._calculate_bands(buffer)
                    if self.on_audio_levels:
                        self.on_audio_levels(bands)

                # Install tap (buffer size 1024)
                input_node.installTapOnBus_bufferSize_format_block_(
                    0, 1024, recording_format, _buffer_tap
                )

                self.audio_engine.prepare()
                started = self.audio_engine.startAndReturnError_(None)
                if not started:
                    debug_print("[Speech] AVAudioEngine failed to start.", "error")
                    self.stop()
                    return

                self._is_running = True
                debug_print("[Speech] Microphone tap active and listening.", "success")

            except Exception as exc:
                debug_print(f"[Speech] Engine start failure: {exc}", "error")
                self.stop()

    def _calculate_bands(self, buffer) -> list[float]:
        try:
            frame_len = int(buffer.frameLength())
            if frame_len <= 0:
                return [0.0] * 8

            # PyObjC returns a pointer wrapper for floatChannelData()[0]
            channel_ptr = buffer.floatChannelData()[0]
            # Convert raw C float array directly to Python memoryview/buffer
            raw_floats = channel_ptr.as_buffer(frame_len * 4)
            samples = struct.unpack(f"{frame_len}f", raw_floats)

            bands = []
            chunk_size = max(1, frame_len // 8)
            for i in range(8):
                start = i * chunk_size
                end = min(frame_len, (i + 1) * chunk_size)
                chunk = samples[start:end]
                if not chunk:
                    bands.append(0.0)
                    continue

                rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
                normalized = min(1.0, max(0.0, rms * 25.0))
                bands.append(round(normalized, 3))

            return bands
        except Exception:
            return [0.0] * 8
        
    def stop(self):
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False

            try:
                if self.audio_engine:
                    input_node = self.audio_engine.inputNode()
                    if input_node:
                        input_node.removeTapOnBus_(0)
                    self.audio_engine.stop()
                    self.audio_engine = None

                if self.recognition_request:
                    self.recognition_request.endAudio()
                    self.recognition_request = None

                if self.recognition_task:
                    self.recognition_task.cancel()
                    self.recognition_task = None

                self.speech_recognizer = None
                debug_print("[Speech] Engine stopped.", "info")
            except Exception as exc:
                debug_print(f"[Speech] Cleanup warning: {exc}", "warning")
import re
import collections

from runtime import REDACTOR_BUFFER_CHARS

class SecretRedactor:
    def __init__(self, buffer_chars=REDACTOR_BUFFER_CHARS):
        self.buffer_chars = buffer_chars
        self.cycles = collections.deque()
        self.patterns = [
            re.compile(r'(?<!\d)(?:\d[\s-]*?){13,19}(?!\d)'),
            re.compile(r'(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)'),
            re.compile(r'(?<!\w)[A-Za-z0-9+/=]{40,}(?!\w)'),
            re.compile(r'sk-[a-zA-Z0-9]{20,}'),
            re.compile(r'Bearer\s+[a-zA-Z0-9\-\.=_]{20,}'),
        ]

    def process_cycle(self, timestamp, app_changed_line, ui_tree_line, current_events):
        parsed_events = []
        for ev in current_events:
            char = None
            is_backspace = False
            
            if ev.endswith(" pressed"):
                key_part = ev[:-8]
                if len(key_part) == 3 and key_part.startswith("'") and key_part.endswith("'"):
                    char = key_part[1]
                elif key_part == 'Key.space': char = ' '
                elif key_part == 'Key.tab': char = '\t'
                elif key_part == 'Key.enter': char = '\n'
                elif key_part == 'Key.backspace': is_backspace = True
                    
            parsed_events.append({
                "raw": ev,
                "char": char,
                "is_backspace": is_backspace,
                "redacted": False
            })
            
        cycle = {
            "timestamp": timestamp,
            "app_changed": app_changed_line,
            "ui_tree": {"raw": ui_tree_line, "redacted": None} if ui_tree_line else None,
            "events": parsed_events
        }
        self.cycles.append(cycle)
        self._redact_secrets()
        return self._get_ready_to_flush()

    def _redact_secrets(self):
        text_chars = []
        stream_indices = []
        
        for c_idx, cycle in enumerate(self.cycles):
            for e_idx, ev in enumerate(cycle["events"]):
                if ev["is_backspace"]:
                    if text_chars:
                        text_chars.pop()
                        stream_indices.pop()
                elif ev["char"] is not None:
                    text_chars.append(ev["char"])
                    stream_indices.append((c_idx, e_idx))
                    
        text = "".join(text_chars)
        
        for pattern in self.patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                secret_val = text[start:end]
                
                for idx in range(start, end):
                    c_idx, e_idx = stream_indices[idx]
                    char = self.cycles[c_idx]["events"][e_idx]["char"]
                    if char and (char.isalnum() or char in "+/=-"):
                        self.cycles[c_idx]["events"][e_idx]["redacted"] = True
                        
                for cycle in self.cycles:
                    if cycle["ui_tree"]:
                        target = cycle["ui_tree"]["redacted"] or cycle["ui_tree"]["raw"]
                        
                        if secret_val in target:
                            target = target.replace(secret_val, "[REDACTED]")
                            
                        clean_val = secret_val.replace(" ", "").replace("-", "")
                        if len(clean_val) > 4 and clean_val in target:
                            target = target.replace(clean_val, "[REDACTED]")
                            
                        cycle["ui_tree"]["redacted"] = target

    def _get_ready_to_flush(self):
        char_count = sum(1 for cycle in self.cycles for ev in cycle["events"] if ev["char"] is not None)
        lines_to_write = []
        
        while char_count > self.buffer_chars and self.cycles:
            cycle = self.cycles[0]
            for ev in cycle["events"]:
                if ev["char"] is not None:
                    char_count -= 1
            lines_to_write.extend(self._format_cycle(cycle))
            self.cycles.popleft()
            
        return lines_to_write

    def flush_all(self):
        lines_to_write = []
        while self.cycles:
            lines_to_write.extend(self._format_cycle(self.cycles.popleft()))
        return lines_to_write

    def _format_cycle(self, cycle):
        lines = []
        if cycle["app_changed"]:
            lines.append(cycle["app_changed"])
        if cycle["ui_tree"]:
            lines.append(cycle["ui_tree"]["redacted"] or cycle["ui_tree"]["raw"])
        if cycle["events"]:
            ev_strings = []
            for ev in cycle["events"]:
                out_str = ev["raw"]
                if ev["redacted"] and out_str.startswith("'") and " pressed" in out_str:
                    out_str = "'[REDACTED]' pressed"
                ev_strings.append(out_str)
            lines.append(f"[{cycle['timestamp']}] User Inputs: {ev_strings}")
        return lines
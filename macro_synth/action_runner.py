"""Validate and execute synthesized macro actions."""

import re

from infrastructure.debugging import debug_print
from command_executors import zsh_exec
from . import input_events
from .runtime import ACTION_BUFFER_TIME_MS, abort_event


def format_action_label(tag: str, attrs: dict, body: str) -> str:
    if tag == "Zsh":
        if isinstance(body, dict):
            body = body.get("Command", "")
        preview = str(body)[:60] + "..." if len(str(body)) > 60 else str(body)
        return f"terminal: {preview}"
    if tag == "KeyCombo":
        return body
    if tag == "KeyPress":
        count = int(attrs.get("count", 1))
        return f"{body} (x{count})" if count > 1 else body
    if tag == "TypeText":
        preview = body[:30] + "..." if len(body) > 30 else body
        return f"type '{preview}'"
    if tag == "MouseClick":
        return f"{attrs.get('button', 'left')} click ({attrs.get('x')}, {attrs.get('y')}) x{int(attrs.get('count', 1))}"
    if tag == "Scroll":
        return f"scroll dx={attrs.get('dx', 0)} dy={attrs.get('dy', 0)}"
    if tag == "Wait":
        return f"wait {attrs.get('ms', 50)}ms"
    return f"{tag} {body}"


def unoptimized_action_warnings(action_cmds: list) -> list[str]:
    warnings = []
    normalized_combos = {
        re.sub(r"\s+", "", str(cmd.content).strip().lower())
        for cmd in action_cmds
        if cmd.command == "KeyCombo"
    }
    if normalized_combos & {"cmd+tab", "command+tab"}:
        warnings.append("Application switching was used instead of context memory.")
    if "cmd+c" in normalized_combos and "cmd+v" in normalized_combos and any(
        cmd.command == "MouseClick" for cmd in action_cmds
    ):
        warnings.append("Mouse selection was combined with a copy/paste loop.")
    return warnings


def execute_macro_commands(commands: list, hud) -> bool:
    analysis = None
    action_cmds = []
    for cmd in commands:
        if cmd.command == "MacroAnalysis" and isinstance(cmd.content, dict):
            analysis = cmd.content
        else:
            action_cmds.append(cmd)

    for warning in unoptimized_action_warnings(action_cmds):
        debug_print(f"[MacroSynth] Optimization warning: {warning}", "warning")

    hud_actions = []
    for cmd in action_cmds:
        body = cmd.content if isinstance(cmd.content, str) else ""
        hud_actions.append({
            "label": format_action_label(cmd.command, cmd.attributes, body),
            "reasoning": cmd.attributes.get("reasoning", "No reasoning provided"),
            "state": "pending",
        })
    hud.update(status_text=f"Executing {len(action_cmds)} actions...", actions=hud_actions, analysis=analysis)
    if not action_cmds:
        hud.update(status_text="No executable actions returned.")
        return False

    for index, cmd in enumerate(action_cmds):
        if abort_event.is_set():
            return False
        hud_actions[index]["state"] = "active"
        hud.update(status_text=f"Running step {index + 1}/{len(action_cmds)}...", actions=hud_actions)
        tag = cmd.command
        attrs = cmd.attributes
        body = cmd.content if isinstance(cmd.content, str) else ""
        if tag == "KeyCombo":
            input_events.press_key_combo(body)
        elif tag == "KeyPress":
            input_events.press_single_key(body, count=int(attrs.get("count", 1)))
        elif tag == "TypeText":
            input_events.type_unicode_string(body)
        elif tag == "MouseClick":
            posted = input_events.click_mouse(
                float(attrs["x"]), float(attrs["y"]), attrs.get("button", "left"), int(attrs.get("count", 1))
            )
            debug_print(
                f"[MacroSynth] Mouse event {'posted' if posted else 'not posted'} at ({attrs['x']}, {attrs['y']}).",
                "debug" if posted else "error",
            )
        elif tag == "Scroll":
            input_events.scroll_mouse(
                int(attrs.get("dx", 0)), int(attrs.get("dy", 0)),
                float(attrs["x"]) if "x" in attrs else None,
                float(attrs["y"]) if "y" in attrs else None,
            )
        elif tag == "Wait":
            input_events.interruptible_wait(int(attrs.get("ms", 50)))
        elif tag == "Zsh":
            result = zsh_exec.execute(attrs, cmd.content, {})
            debug_print(f"[MacroSynth] Terminal command result:\n{result}", "data")
        input_events.interruptible_wait(ACTION_BUFFER_TIME_MS)
        if abort_event.is_set():
            return False
        hud_actions[index]["state"] = "done"
        hud.update(actions=hud_actions)
    return True

# Command: WriteFile

**Description:**
Writes, overwrites, or surgically edits a file on the local file system. Supports full-file writes, single line-based inserts/replacements, and multi-edit batches combining inserts and replacements in a single call.
*Note:* The system automatically intercepts this command, applies the changes, and only passes the `<Summary>` back up the context chain to prevent context window saturation.

**Attributes:**
- `path` (required): The absolute filepath (or path relative to workspace root) of the file to write or edit.
- `mode` (optional): `"overwrite"` (default), `"insert"`, or `"replace"`. Ignored if `<Edits>` is provided.
- `line` (optional): Required for single-edit `mode="insert"`. 1-based line number where new lines will be inserted *before* the existing line at that number (use `total_lines + 1` to append to the end).
- `start_line` (optional): Required for single-edit `mode="replace"`. 1-based starting line number (inclusive).
- `end_line` (optional): Optional for `mode="replace"`. 1-based ending line number (inclusive; defaults to `start_line`).

**Child Tags:**
- `<Content>`: Full file text (for `overwrite`) or replacement/inserted lines (for single-edit `insert`/`replace`).
- `<Edits>`: Optional container of one or more `<Edit>` blocks to perform multiple inserts and/or replacements in one call. All line numbers refer to the file **before** any edits in the batch are applied.
  - `<Edit>` child tags:
    - `<Action>`: `"insert"` or `"replace"`.
    - `<Line>`: 1-based line number (for `insert`).
    - `<StartLine>`: 1-based start line, inclusive (for `replace`).
    - `<EndLine>`: 1-based end line, inclusive (for `replace`; defaults to `StartLine`).
    - `<Content>`: The text/lines to insert or replace with.
- `<Summary>`: A brief summary of what was written/changed. This is what parent agents will see.

**Example Usage (Full Overwrite):**
<WriteFile path="/Users/davidthele/Documents/project/src/utils.py">
    <Content>
def calculate_sum(a, b):
    return a + b
    </Content>
    <Summary>Created utils.py and added calculate_sum function.</Summary>
</WriteFile>

**Example Usage (Single Insert at Line 12):**
<WriteFile path="/Users/davidthele/Documents/project/src/utils.py" mode="insert" line="12">
    <Content>
import logging
logger = logging.getLogger(__name__)
    </Content>
    <Summary>Inserted logger import at line 12.</Summary>
</WriteFile>

**Example Usage (Single Replace Lines 20-24):**
<WriteFile path="/Users/davidthele/Documents/project/src/utils.py" mode="replace" start_line="20" end_line="24">
    <Content>
def calculate_sum(a: float, b: float) -> float:
    return a + b
    </Content>
    <Summary>Added type annotations to calculate_sum (lines 20-24).</Summary>
</WriteFile>

**Example Usage (Multiple Combined Inserts & Replacements):**
<WriteFile path="/Users/davidthele/Documents/project/src/utils.py">
    <Edits>
        <Edit>
            <Action>insert</Action>
            <Line>1</Line>
            <Content>from typing import Iterable</Content>
        </Edit>
        <Edit>
            <Action>replace</Action>
            <StartLine>10</StartLine>
            <EndLine>12</EndLine>
            <Content>def calculate_sum(values: Iterable[float]) -> float:
    return sum(values)</Content>
        </Edit>
    </Edits>
    <Summary>Added Iterable import at line 1 and updated calculate_sum at lines 10-12.</Summary>
</WriteFile>
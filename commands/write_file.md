# Command: WriteFile

**Description:**
Writes, overwrites, or surgically edits a file on the local file system. Supports full-file writes, line-based inserts/replacements, exact search-and-replace blocks, and multi-edit batches combining them in a single call.
*Note:* The system automatically intercepts this command, applies the changes, and only passes the `<Summary>` back up the context chain to prevent context window saturation.

**Attributes:**
- `path` (required): The absolute filepath (or path relative to workspace root) of the file to write or edit.
- `mode` (optional): `"overwrite"` (default), `"insert"`, `"replace"`, or `"search_replace"`. Ignored if `<Edits>` is provided.
- `line` (optional): Required for single-edit `mode="insert"`. 1-based line number where new lines will be inserted *before* the existing line at that number (use `total_lines + 1` to append to the end).
- `start_line` (optional): Required for single-edit `mode="replace"`. 1-based starting line number (inclusive).
- `end_line` (optional): Optional for `mode="replace"`. 1-based ending line number (inclusive; defaults to `start_line`).
- `replace_all` (optional): For `mode="search_replace"`. `"true"` or `"false"` (default `"false"`). When `"false"`, `<Search>` must match **exactly once** or the edit fails with an error.

**Child Tags:**
- `<Content>`: Full file text (for `overwrite`) or replacement/inserted lines (for single-edit `insert`/`replace`).
- `<Search>` / `<Replace>`: Required for single-edit `mode="search_replace"`. `<Search>` is the exact text to find; `<Replace>` is the replacement text (may be empty to delete).
- `<Edits>`: Optional container of one or more `<Edit>` blocks to perform multiple edits in one call. All line-based edits (`insert`/`replace`) are applied **first** using original pre-edit line numbers (bottom-up so earlier inserts never shift later line numbers), followed by `search_replace` edits sequentially.
  - `<Edit>` child tags:
    - `<Action>`: `"insert"`, `"replace"`, or `"search_replace"`.
    - `<Line>`: 1-based line number (for `insert`).
    - `<StartLine>`: 1-based start line, inclusive (for `replace`).
    - `<EndLine>`: 1-based end line, inclusive (for `replace`; defaults to `StartLine`).
    - `<Content>`: The text/lines to insert or replace with (for `insert`/`replace`).
    - `<Search>`: Exact text to match (for `search_replace`).
    - `<Replace>`: Replacement text (for `search_replace`).
    - `<ReplaceAll>`: Optional `"true"` or `"false"` (defaults to `"false"`, for `search_replace`).
- `<Summary>`: A brief summary of what was written/changed. This is what parent agents will see.

**Example Usage (Full Overwrite):**
<WriteFile path="/Users/davidthele/Documents/project/src/utils.py">
    <Content>
def calculate_sum(a, b):
    return a + b
    </Content>
    <Summary>Created utils.py and added calculate_sum function.</Summary>
</WriteFile>

**Example Usage (Single Search & Replace):**
<WriteFile path="/Users/davidthele/Documents/project/src/utils.py" mode="search_replace">
    <Search>def calculate_sum(a, b):
    return a + b</Search>
    <Replace>def calculate_sum(a: float, b: float) -> float:
    return a + b</Replace>
    <Summary>Added type annotations to calculate_sum.</Summary>
</WriteFile>

**Example Usage (Search & Replace All Occurrences):**
<WriteFile path="/Users/davidthele/Documents/project/src/utils.py" mode="search_replace" replace_all="true">
    <Search>old_helper</Search>
    <Replace>new_helper</Replace>
    <Summary>Renamed all occurrences of old_helper to new_helper.</Summary>
</WriteFile>

**Example Usage (Single Insert at Line 12):**
<WriteFile path="/Users/davidthele/Documents/project/src/utils.py" mode="insert" line="12">
    <Content>
import logging
logger = logging.getLogger(__name__)
    </Content>
    <Summary>Inserted logger import at line 12.</Summary>
</WriteFile>

**Example Usage (Multiple Combined Line Edits & Search/Replace):**
<WriteFile path="/Users/davidthele/Documents/project/src/utils.py">
    <Edits>
        <Edit>
            <Action>insert</Action>
            <Line>9</Line>
            <Content># Added header comment</Content>
        </Edit>
        <Edit>
            <Action>insert</Action>
            <Line>14</Line>
            <Content># Inserted at original line 14 (unshifted by line 9 insert)</Content>
        </Edit>
        <Edit>
            <Action>search_replace</Action>
            <Search>return a + b</Search>
            <Replace>return float(a + b)</Replace>
        </Edit>
    </Edits>
    <Summary>Inserted comments at original lines 9 and 14 and cast return value to float.</Summary>
</WriteFile>

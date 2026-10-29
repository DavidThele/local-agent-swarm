# Command: ListDirectory

**Description:**
Lists the contents of a directory. Prefer this over using `<Zsh>` with `ls` as it is computationally cheaper and returns formatted JSON/paths that are easier for agents to read.

**Attributes:**
- `path` (required): The absolute filepath of the directory to list.
- `depth` (optional): Specify the maxdepth to recursively list files through. Default is 1 (current directory only).

**Example Usage:**
<ListDirectory path="/Users/davidthele/Documents/project/src" depth="3" />
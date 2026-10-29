# Command: WriteFile

**Description:**
Writes or overwrites a file on the local file system. 
*Note:* The system automatically intercepts this command, writes the full file, and only passes the `<Summary>` back up the context chain to prevent context window saturation.

**Attributes:**
- `path` (required): The absolute filepath of the file to write.

**Child Tags:**
- `<Content>`: The exact, complete text or code to write to the file.
- `<Summary>`: A brief summary of what was written/changed. This is what parent agents will see.

**Example Usage:**
<WriteFile path="/Users/davidthele/Documents/project/src/utils.py">
    <Content>
def calculate_sum(a, b):
    return a + b
    </Content>
    <Summary>Created utils.py and added calculate_sum function.</Summary>
</WriteFile>
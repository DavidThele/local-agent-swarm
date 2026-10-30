import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Dict, Any, Union
from infrastructure.debug_colors import debug_print

# Leaf tags that frequently contain raw code, shell operators (&&, <, >), or nested example tags
RAW_TEXT_TAGS = (
    "Content", "Summary", "Command", "Instructions", 
    "Context", "DoD", "Result", "Query", "Text", "New", "Existing",
    "Bottlenecks", "Recommendations", "EfficiencyScore"
)

@dataclass
class ParsedCommand:
    command: str                         # The root tag name (e.g., "SpawnAgent")
    attributes: Dict[str, str]           # Tag attributes (e.g., {"type": "WORKER"})
    content: Union[str, Dict[str, Any]]  # Text content, or a dictionary of nested tags
    raw: str                             # The raw XML string

def _wrap_leaf_tags_in_cdata(xml_str: str) -> str:
    """
    Wraps the inner content of known leaf tags in <![CDATA[...]]> if not already wrapped,
    preventing unescaped '<', '>', '&', or example XML tags in code/instructions from breaking ElementTree.
    """
    for tag in RAW_TEXT_TAGS:
        pattern = re.compile(rf"(<{tag}(?:\s+[^>]*)?>)(.*?)(</{tag}>)", re.DOTALL)

        def replacer(match):
            open_tag, body, close_tag = match.group(1), match.group(2), match.group(3)
            if "<![CDATA[" in body:
                return match.group(0)
            safe_body = body.replace("]]>", "]]]]><![CDATA[>")
            return f"{open_tag}<![CDATA[{safe_body}]]>{close_tag}"

        xml_str = pattern.sub(replacer, xml_str)
    return xml_str

def _extract_top_level_xml_blocks(text: str) -> List[str]:
    """
    Extracts top-level XML blocks while respecting nested tags of the same name.
    First masks leaf tags in CDATA so inner example tags don't confuse tag depth.
    """
    # Temporarily wrap leaf tags so example tags inside <Instructions> or <Content> are ignored
    masked_text = _wrap_leaf_tags_in_cdata(text)
    
    # Match any XML tag (opening, closing, or self-closing) outside of CDATA sections
    token_re = re.compile(
        r'<!\[CDATA\[.*?\]\]>|<(/?)([a-zA-Z0-9_]+)(?:\s+[^<>]*?)?(/?)>',
        re.DOTALL
    )
    
    blocks = []
    root_tag = None
    depth = 0
    start_idx = None

    for match in token_re.finditer(masked_text):
        full_token = match.group(0)
        if full_token.startswith("<![CDATA["):
            continue

        is_closing = bool(match.group(1))
        tag_name = match.group(2)
        is_self_closing = bool(match.group(3))

        if root_tag is None:
            if not is_closing:
                if is_self_closing:
                    blocks.append(full_token)
                else:
                    root_tag = tag_name
                    depth = 1
                    start_idx = match.start()
        else:
            if tag_name == root_tag:
                if not is_closing and not is_self_closing:
                    depth += 1
                elif is_closing:
                    depth -= 1
                    if depth == 0:
                        blocks.append(masked_text[start_idx:match.end()])
                        root_tag = None
                        start_idx = None

    return blocks

def parse_element(element: ET.Element) -> Union[str, Dict[str, Any]]:
    """
    Recursively parses an XML element.
    - If it has no children, returns the text string (preserving internal indentation).
    - If it has children, returns a dictionary.
    - If it has multiple children with the same tag name, groups them into a list.
    """
    if len(element) > 0:
        result = {}
        for child in element:
            parsed_child = parse_element(child)

            if child.tag in result:
                if not isinstance(result[child.tag], list):
                    result[child.tag] = [result[child.tag]]
                result[child.tag].append(parsed_child)
            else:
                result[child.tag] = parsed_child

        return result
    else:
        if not element.text:
            return ""
        # Strip leading/trailing blank newlines without destroying leading indentation on code lines
        return element.text.strip("\r\n") if "\n" in element.text else element.text.strip()

def parse_llm_output(text: str) -> List[ParsedCommand]:
    """
    Scans LLM output for XML blocks, ignoring conversational text.
    Handles standard <Tag>...</Tag>, self-closing <Tag />, and nested tags.
    """
    if not text:
        return []

    commands = []
    for safe_block in _extract_top_level_xml_blocks(text):
        try:
            root = ET.fromstring(safe_block)
            content = parse_element(root)

            commands.append(ParsedCommand(
                command=root.tag,
                attributes=root.attrib,
                content=content,
                raw=safe_block
            ))

        except ET.ParseError as e:
            debug_print(f"[Parser] Malformed XML block skipped: {e}", "warning")
            debug_print(f"[Parser] Failed block snippet: {safe_block[:50]}...", "data")

    return commands
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Dict, Any, Union
from infrastructure.debug_colors import debug_print

# Leaf tags that frequently contain raw code, shell operators (&&, <, >), or arbitrary text
RAW_TEXT_TAGS = (
    "Content", "Summary", "Command", "Instructions", 
    "Context", "DoD", "Result", "Query", "Text", "New", "Existing"
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
    preventing unescaped '<', '>', and '&' in code or shell commands from breaking ElementTree.
    """
    for tag in RAW_TEXT_TAGS:
        pattern = re.compile(rf"(<{tag}(?:\s+[^>]*)?>)(.*?)(</{tag}>)", re.DOTALL)
        
        def replacer(match):
            open_tag, body, close_tag = match.group(1), match.group(2), match.group(3)
            if "<![CDATA[" in body:
                return match.group(0)
            # Escape any literal ']]>' sequences inside the body so CDATA doesn't terminate early
            safe_body = body.replace("]]>", "]]]]><![CDATA[>")
            return f"{open_tag}<![CDATA[{safe_body}]]>{close_tag}"
            
        xml_str = pattern.sub(replacer, xml_str)
    return xml_str

def parse_element(element: ET.Element) -> Union[str, Dict[str, Any]]:
    """
    Recursively parses an XML element.
    - If it has no children, returns the text string.
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
        return element.text.strip() if element.text else ""

def parse_llm_output(text: str) -> List[ParsedCommand]:
    """
    Scans LLM output for XML blocks, ignoring conversational text.
    Handles both standard <Tag>...</Tag> and self-closing <Tag /> formats.
    """
    if not text:
        return []
        
    commands = []
    pattern = r'(<([a-zA-Z0-9_]+)(?:\s+[^>]*)?>.*?</\2>|<([a-zA-Z0-9_]+)(?:\s+[^>]*)?/>)'
    
    for match in re.finditer(pattern, text, re.DOTALL):
        raw_block = match.group(0)
        
        try:
            safe_xml = _wrap_leaf_tags_in_cdata(raw_block)
            root = ET.fromstring(safe_xml)
            content = parse_element(root)
            
            commands.append(ParsedCommand(
                command=root.tag,
                attributes=root.attrib,
                content=content,
                raw=raw_block
            ))
            
        except ET.ParseError as e:
            debug_print(f"[Parser] Malformed XML block skipped: {e}", "warning")
            debug_print(f"[Parser] Failed block snippet: {raw_block[:50]}...", "data")
            
    return commands
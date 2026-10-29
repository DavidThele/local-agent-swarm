import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Dict, Any, Union
from infrastructure.debug_colors import debug_print

@dataclass
class ParsedCommand:
    command: str                         # The root tag name (e.g., "SpawnAgent")
    attributes: Dict[str, str]           # Tag attributes (e.g., {"type": "WORKER"})
    content: Union[str, Dict[str, Any]]  # Text content, or a dictionary of nested tags
    raw: str                             # The raw XML string

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
                # If we've already seen this tag, convert it to a list
                if not isinstance(result[child.tag], list):
                    result[child.tag] = [result[child.tag]]
                result[child.tag].append(parsed_child)
            else:
                result[child.tag] = parsed_child
                
        return result
    else:
        # No children, just return the stripped text
        return element.text.strip() if element.text else ""

def parse_llm_output(text: str) -> List[ParsedCommand]:
    """
    Scans LLM output for XML blocks, ignoring conversational text.
    Handles both standard <Tag>...</Tag> and self-closing <Tag /> formats.
    """
    commands = []
    
    # Regex matches <TagName ...> ... </TagName> OR <TagName ... />
    # Uses re.DOTALL to capture multiline content across newlines
    pattern = r'(<([a-zA-Z0-9_]+)[^>]*>.*?</\2>|<([a-zA-Z0-9_]+)[^>]*/>)'
    
    for match in re.finditer(pattern, text, re.DOTALL):
        raw_block = match.group(0)
        
        try:
            # Parse the extracted block into an XML tree
            root = ET.fromstring(raw_block)
            
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


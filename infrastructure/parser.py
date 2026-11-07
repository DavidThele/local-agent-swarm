import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Dict, Any, Union, Sequence, Tuple
from infrastructure.debugging import debug_print

# Leaf tags that frequently contain raw code, shell operators (&&, <, >), or nested example tags
RAW_TEXT_TAGS = (
    "Content", "Summary", "Command", "Instructions", 
    "Context", "DoD", "Result", "Query", "Text", "New", "Existing",
    "Bottlenecks", "Recommendations", "EfficiencyScore",
    "EndGoal", "CurrentState", "GeneralSteps", "WorkingMemory",
    "TypeText", "KeyCombo", "KeyPress",
    "UserPromptIntent", "ObservedVideoExecution", 
    "AlignmentComparison", "SuccessReasoning", "Verdict"
)

@dataclass
class ParsedCommand:
    command: str                         # The root tag name (e.g., "SpawnAgent")
    attributes: Dict[str, str]           # Tag attributes (e.g., {"type": "worker"})
    content: Union[str, Dict[str, Any]]  # Text content, or a dictionary of nested tags
    raw: str                             # The raw XML string

def _mask_markdown_code_spans(text: str) -> Tuple[str, Dict[str, str]]:
    """
    Replaces all backtick spans (`...`, ```...```, ````...````) with unique tokens
    so backtick-enclosed pseudo-tags (e.g., `<WorkingMemory>`) are completely ignored
    by XML tag extractors and CDATA wrappers.
    """
    code_map: Dict[str, str] = {}
    counter = 0

    # Matches backtick runs of any length (1, 2, 3, 4+) and everything up to the matching run
    code_pattern = re.compile(r"(`+)(.+?)\1", re.DOTALL)

    def replacer(match: re.Match) -> str:
        nonlocal counter
        token = f"__MD_CODE_SPAN_{counter}__"
        code_map[token] = match.group(0)
        counter += 1
        return token

    masked_text = code_pattern.sub(replacer, text)
    return masked_text, code_map

def _unmask_markdown_code_spans(text: str, code_map: Dict[str, str]) -> str:
    """
    Restores original code spans back into text after XML block extraction and parsing.
    """
    for token, original in code_map.items():
        text = text.replace(token, original)
    return text

def _wrap_leaf_tags_in_cdata(xml_str: str) -> str:
    """
    Wraps the inner content of known leaf/text tags in <![CDATA[...]]> if not already wrapped,
    preventing unescaped '<', '>', '&', or nested example XML tags from breaking ElementTree.
    """
    CONTAINER_TEXT_TAGS = ["Content", "Instructions"]
    LEAF_TAGS = [t for t in RAW_TEXT_TAGS if t not in CONTAINER_TEXT_TAGS]

    def wrap_tag_list(text: str, tags: Sequence[str]) -> str:
        for tag in tags:
            pattern = re.compile(rf"(<{tag}(?:\s+[^>]*)?>)(.*?)(</{tag}>)", re.DOTALL)

            def replacer(match: re.Match) -> str:
                open_tag, body, close_tag = match.group(1), match.group(2), match.group(3)
                stripped = body.strip()
                
                if stripped.startswith("<![CDATA[") and stripped.endswith("]]>"):
                    return match.group(0)
                
                safe_body = body.replace("]]>", "]]]]><![CDATA[>")
                return f"{open_tag}<![CDATA[{safe_body}]]>{close_tag}"

            text = pattern.sub(replacer, text)
        return text

    xml_str = wrap_tag_list(xml_str, CONTAINER_TEXT_TAGS)
    xml_str = wrap_tag_list(xml_str, LEAF_TAGS)

    return xml_str

def _extract_top_level_xml_blocks(text: str) -> List[str]:
    """
    Extracts top-level XML blocks while respecting nested tags of the same name.
    Ignores pseudo-tags within backticks and masks leaf tags in CDATA.
    """
    # 1. Mask all markdown inline/fenced code spans
    masked_text, code_map = _mask_markdown_code_spans(text)
    
    # 2. Wrap known leaf tags in CDATA so inner tags don't confuse tag depth
    cdata_text = _wrap_leaf_tags_in_cdata(masked_text)
    
    # Match XML tags outside of CDATA sections
    token_re = re.compile(
        r'<!\[CDATA\[.*?\]\]>|<(/?)([a-zA-Z0-9_]+)(?:\s+[^<>]*?)?(/?)>',
        re.DOTALL
    )
    
    blocks = []
    root_tag = None
    depth = 0
    start_idx = None

    for match in token_re.finditer(cdata_text):
        full_token = match.group(0)
        if full_token.startswith("<![CDATA["):
            continue

        is_closing = bool(match.group(1))
        tag_name = match.group(2)
        is_self_closing = bool(match.group(3))

        if root_tag is None:
            if not is_closing:
                if is_self_closing:
                    block = _unmask_markdown_code_spans(full_token, code_map)
                    blocks.append(block)
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
                    if depth == 0 and start_idx is not None:
                        block = cdata_text[start_idx:match.end()]
                        # Unmask original code blocks back into the extracted block
                        blocks.append(_unmask_markdown_code_spans(block, code_map))
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
        result: Dict[str, Any] = {}
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
        return element.text.strip("\r\n") if "\n" in element.text else element.text.strip()

def parse_llm_output(text: str) -> List[ParsedCommand]:
    """
    Scans LLM output for XML blocks, ignoring conversational text and code spans.
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
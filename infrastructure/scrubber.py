import re
import unicodedata

# Regex to strip null bytes, ASCII control characters (keeping \t, \n, \r), and the DEL character
CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')

SCRUB_PATTERNS = {
    # Credit Cards (13-19 digits, optional dashes/spaces)
    r'(?:\d[ -]*?){13,16}': '[REDACTED_CREDIT_CARD]',
    
    # Social Security Numbers
    r'\b\d{3}-\d{2}-\d{4}\b': '[REDACTED_SSN]',
    
    # Standard Bearer Tokens / Authorization Headers
    r'Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*': 'Bearer [REDACTED_TOKEN]',
    
    # JWT Tokens (ey... pattern)
    r'ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}': '[REDACTED_JWT]',
    
    # AWS Access Key IDs
    r'\b(?:A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}\b': '[REDACTED_AWS_KEY]',
    
    # GitHub Access Tokens (Classic and Fine-grained)
    r'\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[a-zA-Z0-9_]{36,255}\b': '[REDACTED_GITHUB_TOKEN]',
    
    # OpenAI API Keys
    r'\bsk-[a-zA-Z0-9]{48}\b': '[REDACTED_OPENAI_KEY]',
    
    # Anthropic API Keys
    r'\bsk-ant-api03-[a-zA-Z0-9\-_]{80,90}\b': '[REDACTED_ANTHROPIC_KEY]',
    
    # Explicit secret assignments (e.g., api_key="...", password=...). 
    # Requires an equal sign or colon to avoid matching casual text or window titles.
    r'(?i)(?:password|secret|api_key|access_token|auth_token|client_secret)[\s]*[:=][\s]*[\'"]?([^\'"\s\n]+)[\'"]?': r'\g<0> [REDACTED_SECRET]',
}

def compile_scrubber():
    compiled = []
    for pattern, replacement in SCRUB_PATTERNS.items():
        compiled.append((re.compile(pattern), replacement))
    return compiled

COMPILED_PATTERNS = compile_scrubber()

def sanitize_text(text: str) -> str:
    """
    Cleans raw telemetry text to prevent 400 INVALID_ARGUMENT errors in downstream LLM APIs:
    - Strips null bytes (\x00) and unprintable ASCII control characters.
    - Resolves lone Unicode surrogate code points.
    - Normalizes Unicode composition.
    """
    if not text:
        return text

    # 1. Remove null bytes and control chars (preserves tabs, newlines, and carriage returns)
    clean = CONTROL_CHAR_RE.sub('', text)

    # 2. Encode and decode to discard unpairable surrogate characters (e.g. \uD800-\uDFFF)
    clean = clean.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')

    # 3. Normalize Unicode forms
    return unicodedata.normalize('NFC', clean)

def scrub_text(text: str) -> str:
    if not text:
        return text

    # Step 1: Sanitize invalid/dangerous characters first
    scrubbed_text = sanitize_text(text)
        
    # Step 2: Redact sensitive secrets and credentials
    for regex, replacement in COMPILED_PATTERNS:
        if 'REDACTED_SECRET' in replacement:
            # Dynamically replace only the captured group (the actual secret value)
            scrubbed_text = regex.sub(lambda m: m.group().replace(m.group(1), '[REDACTED]'), scrubbed_text)
        else:
            scrubbed_text = regex.sub(replacement, scrubbed_text)
            
    return scrubbed_text
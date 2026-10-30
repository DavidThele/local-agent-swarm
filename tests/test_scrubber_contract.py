from infrastructure.scrubber import scrub_text, sanitize_text

def test_sanitize_strips_null_bytes_and_control_chars_while_keeping_whitespace():
    raw = "Line 1\x00\x07\x1b\nLine 2\tTabbed"
    cleaned = sanitize_text(raw)
    assert "\x00" not in cleaned
    assert "\x07" not in cleaned
    assert "Line 1\nLine 2\tTabbed" == cleaned

def test_scrubs_all_high_risk_credentials_and_preserves_window_titles():
    log = (
        "[Window Title: 1Password - Vault]\n"
        "GITHUB_TOKEN=ghp_1234567890abcdef1234567890abcdef1234\n"
        "OPENAI=sk-abcdef1234567890abcdef1234567890abcdef1234567890\n"
        "AWS=AKIAIOSFODNN7EXAMPLE\n"
        "SSN: 123-45-6789\n"
        "CC: 4111-2222-3333-4444\n"
        "db_password=MySuperSecretPassword123!\n"
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZS.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    scrubbed = scrub_text(log)
    
    # Window title must remain untouched
    assert "[Window Title: 1Password - Vault]" in scrubbed
    
    # Secrets must be completely removed
    assert "ghp_1234567890abcdef1234567890abcdef1234" not in scrubbed
    assert "sk-abcdef1234567890abcdef1234567890abcdef1234567890" not in scrubbed
    assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed
    assert "123-45-6789" not in scrubbed
    assert "4111-2222-3333-4444" not in scrubbed
    assert "MySuperSecretPassword123!" not in scrubbed
    assert "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c" not in scrubbed
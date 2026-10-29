from pathlib import Path
from datetime import datetime
from infrastructure.prompt_router import send_prompt, GEMINI_3_1_FLASH_LITE
from db.db_manager import add_chunk, delete_chunk, search_similar_chunks, clear
from infrastructure.parser import parse_llm_output
from infrastructure.debug_colors import debug_print

N_SEARCH_RESULTS = 5

def load_system_prompt() -> str:
    """Loads the static Ingestor instructions from the global workspace."""
    prompt_path = Path.home() / ".agents" / "prompts" / "ingestor_instructions.md"
    
    if not prompt_path.exists():
        raise FileNotFoundError(f"Ingestor instructions not found at {prompt_path}")
        
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()

def process_telemetry(raw_log: str):
    """
    Executes the two-phase memory ingestion pipeline.
    """
    sys_prompt = load_system_prompt()
    
    # ==========================================
    # PHASE 1: Extraction
    # ==========================================
    debug_print("[Ingestor] Starting Phase 1: Extracting raw facts...", "info")
    
    phase1_prompt = f"{sys_prompt}\n\n=== RAW TELEMETRY LOG ===\n{raw_log}\n\nExecute Phase 1."
    
    # Call the router
    output1, history1, _ = send_prompt(prompt_text=phase1_prompt, model=GEMINI_3_1_FLASH_LITE)

    debug_print(f"[Ingestor] Phase 1 output: {output1}\n", "data")

    # Parse the LLM's XML output
    commands1 = parse_llm_output(output1)
    
    new_chunks = []
    for cmd in commands1:
        if cmd.command == "ExtractChunk":
            # Safely extract text whether the LLM nested it in <Text> tags or not
            if isinstance(cmd.content, dict) and "Text" in cmd.content:
                # Handle cases where multiple <Text> tags might be parsed as a list
                text_val = cmd.content["Text"]
                chunk_str = text_val[0] if isinstance(text_val, list) else text_val
                new_chunks.append(chunk_str)
            elif isinstance(cmd.content, str):
                new_chunks.append(cmd.content)
                
    if not new_chunks:
        debug_print("[Ingestor] No actionable chunks extracted from log. Exiting.", "warning")
        return
        
    debug_print(f"[Ingestor] Extracted {len(new_chunks)} distinct chunks. Querying database for context...", "info")

    # ==========================================
    # PHASE 2: Semantic Synthesis
    # ==========================================
    # Build the <Compare> blocks for the LLM
    comparisons_xml = ""
    for chunk_text in new_chunks:
        # Fetch the N_SEARCH_RESULTS most semantically similar existing chunks
        similar_chunks = search_similar_chunks(chunk_text, n_results=N_SEARCH_RESULTS)
        
        comparisons_xml += "<Compare>\n"
        comparisons_xml += f"    <New>{chunk_text}</New>\n"
        for sim in similar_chunks:
            comparisons_xml += f"    <Existing id=\"{sim['id']}\">{sim['text']}</Existing>\n"
        comparisons_xml += "</Compare>\n\n"
        
    debug_print("[Ingestor] Starting Phase 2: Synthesizing memory constraints...", "info")
    
    phase2_prompt = (
        "Execute Phase 2 (Synthesis & Database Management) on the following comparisons:\n\n"
        f"{comparisons_xml}"
    )
    
    # Re-use the conversation_id so the LLM retains the context of its Phase 1 outputs
    output2, _, _ = send_prompt(prompt_text=phase2_prompt, model=GEMINI_3_1_FLASH_LITE, chat_history=history1)

    debug_print(f"[Ingestor] Phase 2 output: {output2}\n", "data")
    
    commands2 = parse_llm_output(output2)
    
    # ==========================================
    # EXECUTION: Database Modifcations
    # ==========================================
    deleted_count = 0
    added_count = 0
    
    for cmd in commands2:
        if cmd.command == "DeleteChunk":
            chunk_id = cmd.attributes.get("id")
            if chunk_id:
                try:
                    delete_chunk(chunk_id)
                    deleted_count += 1
                    debug_print(f"[Ingestor] Deleted old chunk: {chunk_id}", "success")
                except Exception as e:
                    debug_print(f"[Ingestor] Failed to delete chunk {chunk_id}: {e}", "error")
                    
        elif cmd.command == "CommitChunk":
            text = ""
            # Inject a true system timestamp directly through Python for accuracy
            metadata = {"timestamp": datetime.now().isoformat()}
            
            if isinstance(cmd.content, dict) and "Text" in cmd.content:
                text_val = cmd.content["Text"]
                text = text_val[0] if isinstance(text_val, list) else text_val
            elif isinstance(cmd.content, str):
                text = cmd.content
                
            if text:
                try:
                    new_id = add_chunk(text, metadata)
                    added_count += 1
                    debug_print(f"[Ingestor] Added new synthesized chunk: {new_id}", "success")
                except Exception as e:
                    debug_print(f"[Ingestor] Failed to add chunk: {e}", "error")
                    
    debug_print(f"\n[Ingestor] Pipeline complete. Added: {added_count} | Deleted: {deleted_count}", "success")

if __name__ == "__main__":
    # Example test run
    sample_scrubbed_log = """
    User navigated to https://github.com/JumboCode/jumbocode-ui
    User opened terminal.
    Type: git checkout -b feature/ticket-123
    Type: npm install tailwindcss
    User opened VSCode.
    """
    
    process_telemetry(sample_scrubbed_log)
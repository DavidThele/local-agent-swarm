from pathlib import Path
from pipelines import ingestor_pipeline, log_ingestor_wrapper

def test_ingestor_pipeline_two_phase_execution(monkeypatch):
    # Mock system prompt loader
    monkeypatch.setattr(ingestor_pipeline, "load_system_prompt", lambda: "SYSTEM_PROMPT")
    
    # Mock LLM router for Turn 1 (ExtractChunk) and Turn 2 (DeleteChunk + CommitChunk)
    prompts_received = []
    def fake_send_prompt(prompt_text, model=None, chat_history=None, print_cost=False):
        prompts_received.append(prompt_text)
        if len(prompts_received) == 1:
            return (
                "<ExtractChunk><Text>User uses React on JumboCode.</Text></ExtractChunk>",
                ["turn1_history"],
                {}
            )
        else:
            return (
                '<DeleteChunk id="chunk_old_1" />\n'
                '<CommitChunk><Text>User uses React on JumboCode as of Oct 2026.</Text></CommitChunk>',
                ["turn1_history", "turn2_history"],
                {}
            )
            
    monkeypatch.setattr(ingestor_pipeline, "send_prompt", fake_send_prompt)
    monkeypatch.setattr(
        ingestor_pipeline,
        "search_similar_chunks",
        lambda q, n_results=5: [{"id": "chunk_old_1", "text": "User uses React."}]
    )
    
    deleted_ids = []
    added_chunks = []
    monkeypatch.setattr(ingestor_pipeline, "delete_chunk", lambda cid: deleted_ids.append(cid))
    monkeypatch.setattr(ingestor_pipeline, "add_chunk", lambda txt, meta: added_chunks.append((txt, meta)) or "chunk_new_1")
    
    # Execute pipeline
    ingestor_pipeline.process_telemetry("Raw log text here")
    
    assert len(prompts_received) == 2
    assert '<Existing id="chunk_old_1">User uses React.</Existing>' in prompts_received[1]
    assert deleted_ids == ["chunk_old_1"]
    assert len(added_chunks) == 1
    assert added_chunks[0][0] == "User uses React on JumboCode as of Oct 2026."
    assert "timestamp" in added_chunks[0][1]

def test_log_wrapper_tracks_line_state_and_resumes(tmp_path, monkeypatch):
    log_dir = tmp_path / "moniter_data"
    day_dir = log_dir / "2026-10-20"
    day_dir.mkdir(parents=True)
    log_file = day_dir / "activity.log"
    
    # Write 10 lines, set chunk size to 4 lines
    log_file.write_text("\n".join([f"log line {i}" for i in range(1, 11)]) + "\n", encoding="utf-8")
    
    state_file = tmp_path / "ingestion_state.json"
    monkeypatch.setattr(log_ingestor_wrapper, "LOG_DIR", log_dir)
    monkeypatch.setattr(log_ingestor_wrapper, "STATE_FILE", state_file)
    monkeypatch.setattr(log_ingestor_wrapper, "LINES_PER_CHUNK", 4)
    
    batches = []
    monkeypatch.setattr(log_ingestor_wrapper, "process_telemetry", lambda text: batches.append(text))
    
    log_ingestor_wrapper.process_log_file("2026-10-20")
    assert len(batches) == 3  # 4 lines + 4 lines + 2 lines
    assert log_ingestor_wrapper.load_state()["2026-10-20/activity.log"] == 10
    
    # Running again on the same file should process 0 new batches since line offset is already 10
    batches.clear()
    log_ingestor_wrapper.process_log_file("2026-10-20")
    assert len(batches) == 0
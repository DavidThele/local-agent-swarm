from pathlib import Path
from infrastructure.workspace import init_global_workspace, create_chat_instance
from db import db_manager

def test_workspace_initialization_and_chat_symlink(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_cwd = tmp_path / "project_repo"
    fake_home.mkdir()
    fake_cwd.mkdir()
    
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(Path, "cwd", lambda: fake_cwd)
    
    global_root = init_global_workspace()
    assert (global_root / "AGENTS.md").exists()
    assert (global_root / "tools").is_dir()
    assert (global_root / "skills").is_dir()
    assert (global_root / "chats").is_dir()
    
    chat_id, local_chat_dir = create_chat_instance("test_session_01")
    assert chat_id == "test_session_01"
    assert local_chat_dir.exists()
    
    global_symlink = global_root / "chats" / "test_session_01"
    assert global_symlink.is_symlink()
    assert global_symlink.resolve() == local_chat_dir.resolve()

def test_db_manager_lifecycle(tmp_path, monkeypatch):
    # Redirect default global_dir to tmp_path
    orig_get_db_client = db_manager.get_db_client
    monkeypatch.setattr(db_manager, "get_db_client", lambda global_dir=str(tmp_path): orig_get_db_client(global_dir))
    
    db_manager.clear()
    assert db_manager.search_similar_chunks("React") == []
    
    c1 = db_manager.add_chunk("User uses React and TypeScript for frontend.", {"timestamp": "2026-10-20"})
    c2 = db_manager.add_chunk("User rides mountain bikes in Vermont.", {"timestamp": "2026-10-21"})
    
    results = db_manager.search_similar_chunks("What frontend framework is used?", n_results=1)
    assert len(results) == 1
    assert results[0]["id"] == c1
    assert "React" in results[0]["text"]
    assert results[0]["metadata"]["timestamp"] == "2026-10-20"
    
    db_manager.delete_chunk(c1)
    remaining = db_manager.search_similar_chunks("React", n_results=5)
    assert all(r["id"] != c1 for r in remaining)
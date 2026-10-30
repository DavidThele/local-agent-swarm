import time
import queue
from infrastructure import agent_loop

def test_parent_is_not_blocked_by_active_child_when_running_other_commands(monkeypatch):
    """
    Contract: If MAIN_ORCHESTRATOR spawns a slow SUB_ORCHESTRATOR and runs SearchDB in Turn 1,
    Turn 2 must start immediately with the SearchDB results WITHOUT blocking on the slow child,
    and the parent must be blocked from calling <MarkDone> until it waits for the child.
    """
    monkeypatch.setattr(agent_loop, "load_prompt", lambda role: f"PROMPT_{role}")
    
    # Track timing and turn prompts
    parent_prompts = []
    
    def fake_send_prompt(prompt_text, model=None, chat_history=None):
        if "PROMPT_worker" in prompt_text:
            # Simulate a child agent taking 0.4s to finish
            time.sleep(0.4)
            return ("<MarkDone><Result>Child finished work</Result><Summary>Done</Summary></MarkDone>", [], {})
            
        # Parent turns
        parent_prompts.append((time.monotonic(), prompt_text))
        turn_num = len(parent_prompts)
        
        if turn_num == 1:
            # Turn 1: Spawn a background worker AND run a fast command (WaitForAgents not called yet)
            return (
                '<SpawnAgent type="WORKER"><Instructions>Do slow task</Instructions></SpawnAgent>\n'
                '<MarkDone><Result>Trying to finish early!</Result><Summary>Early</Summary></MarkDone>',
                [],
                {}
            )
        elif turn_num == 2:
            # Turn 2: Parent should see the error that it cannot MarkDone while child is active, so it calls WaitForAgents
            return ('<WaitForAgents mode="all" />', [], {})
        else:
            # Turn 3: Child is now complete, parent can legally MarkDone
            return ('<MarkDone><Result>All done properly</Result><Summary>Complete</Summary></MarkDone>', [], {})

    monkeypatch.setattr(agent_loop, "send_prompt", fake_send_prompt)
    
    ctx = {
        "local_chat_dir": "/tmp/test_chat",
        "worker_id": "main",
        "notification_queue": queue.Queue(),
        "active_children": {}
    }
    
    start_t = time.monotonic()
    res = agent_loop.run_agent(
        agent_type="MAIN_ORCHESTRATOR",
        instructions="Test parallel execution",
        context="None",
        dod="Complete",
        chat_context_state=ctx,
        agent_id="main"
    )
    
    assert res["status"] == "success"
    assert "All done properly" in res["result"]
    assert len(parent_prompts) == 3
    
    # Verify Turn 2 started BEFORE the 0.4s child finished (i.e. top of loop did NOT block!)
    turn1_time, _ = parent_prompts[0]
    turn2_time, turn2_prompt = parent_prompts[1]
    assert (turn2_time - turn1_time) < 0.25, "Top of agent_loop blocked on active child instead of continuing immediately!"
    
    # Verify guardrail prevented premature MarkDone on Turn 1
    assert "Cannot <MarkDone> while child agents are still running" in turn2_prompt
    
    # Verify Turn 3 received the child's async completion notification after <WaitForAgents mode="all" />
    _, turn3_prompt = parent_prompts[2]
    assert "ASYNC CHILD AGENT COMPLETED" in turn3_prompt
    assert "Child finished work" in turn3_prompt
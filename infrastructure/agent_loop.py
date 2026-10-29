import importlib
from pathlib import Path
from infrastructure.prompt_router import send_prompt, GEMINI_3_8_FLASH, GEMINI_3_1_FLASH_LITE
from infrastructure.parser import parse_llm_output

# Maximum times an agent can loop (action -> observe) before being forced to fail.
MAX_ITERATIONS = 32

def load_prompt(role: str) -> str:
    path = Path.home() / ".agents" / "prompts" / f"{role}.md"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def run_agent(agent_type: str, instructions: str, context: str, dod: str, chat_context_state: dict) -> dict:
    """
    The core execution loop for a single agent.
    """
    print(f"\n[Swarm] Booting {agent_type.upper()}...")
    
    system_prompt = load_prompt(agent_type.lower())
    
    # Initialize the agent's first prompt with its assignment
    current_prompt = f"{system_prompt}\n\n"
    current_prompt += f"=== YOUR ASSIGNMENT ===\n"
    current_prompt += f"<Instructions>{instructions}</Instructions>\n"
    current_prompt += f"<Context>{context}</Context>\n"
    if dod:
        current_prompt += f"<DoD>{dod}</DoD>\n"
        
    model_to_use = GEMINI_3_8_FLASH if agent_type.upper() == "MAIN_ORCHESTRATOR" else GEMINI_3_1_FLASH_LITE
    
    # The new router natively manages the conversation state array
    chat_history = []
    
    for iteration in range(MAX_ITERATIONS):
        print(f"[{agent_type}] Iteration {iteration + 1}/{MAX_ITERATIONS} - Thinking...")
        
        # 1. Get LLM Output (Router automatically appends the current_prompt and model response to chat_history)
        llm_output, chat_history, cost = send_prompt(
            prompt_text=current_prompt, 
            model=model_to_use, 
            chat_history=chat_history
        )
        
        # 2. Parse Commands
        commands = parse_llm_output(llm_output)
        
        if not commands:
            # If the LLM didn't output any valid XML commands, set the next prompt to force a correction
            current_prompt = "[System Error] No valid XML commands found in your last output. You must use a command or <MarkDone>."
            continue
            
        # 3. Execute Commands
        results_string = "\n[System Environment Results]\n"
        is_done = False
        final_result = None
        
        for cmd in commands:
            print(f"  -> Executing <{cmd.command}>...")
            
            try:
                # Dynamically load the executor file from command_executors/
                module_name = ''.join(['_'+c.lower() if c.isupper() else c for c in cmd.command]).lstrip('_') + "_exec"
                executor = importlib.import_module(f"command_executors.{module_name}")
                
                # Execute
                cmd_result = executor.execute(cmd.attributes, cmd.content, chat_context_state)
                
                # Check if the agent called MarkDone
                if cmd_result.startswith("[STATUS_DONE]"):
                    is_done = True
                    final_result = cmd_result
                    break
                    
                results_string += f"--- Result of <{cmd.command}> ---\n{cmd_result}\n\n"
                
            except ModuleNotFoundError:
                results_string += f"[Error] Command <{cmd.command}> does not exist or has no executor.\n"
            except Exception as e:
                results_string += f"[Error] Failed to execute <{cmd.command}>: {str(e)}\n"
                
        if is_done:
            print(f"[{agent_type}] Task Completed Successfully.")
            return {"status": "success", "result": final_result}
            
        # Set the next prompt to the environment results so the LLM can observe the impact of its commands
        current_prompt = results_string
        
    print(f"[{agent_type}] HIT HARD ITERATION CAP ({MAX_ITERATIONS}). Terminating loop.")
    return {"status": "failed", "result": "[System Error] Agent hit the maximum iteration limit without completing the DoD."}
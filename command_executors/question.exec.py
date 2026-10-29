def execute(attributes: dict, content: dict, context_state: dict) -> str:
    text = content.get("Text", "No question text provided.")
    options = content.get("Options", {}).get("Option", [])
    
    print(f"\n[Agent Question] {text}")
    if isinstance(options, list):
        for i, opt in enumerate(options):
            print(f"  {i + 1}. {opt}")
    elif options:
         print(f"  1. {options}") # Handle single option case
         
    user_response = input("Your answer: ")
    return f"[User Reply] {user_response}"
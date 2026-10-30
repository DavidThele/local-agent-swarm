import pytest
from infrastructure.parser import parse_llm_output, ParsedCommand

def test_ignores_conversational_prose_and_extracts_multiple_commands():
    llm_text = """
    I will first search the database and then check the directory.
    <SearchDB n_results="3">
        <Query>What is the repo structure?</Query>
    </SearchDB>
    Let's also list the files:
    <ListDirectory path="/tmp/project" depth="2" />
    """
    cmds = parse_llm_output(llm_text)
    assert len(cmds) == 2
    assert cmds[0].command == "SearchDB"
    assert cmds[0].attributes == {"n_results": "3"}
    assert cmds[0].content == {"Query": "What is the repo structure?"}
    
    assert cmds[1].command == "ListDirectory"
    assert cmds[1].attributes == {"path": "/tmp/project", "depth": "2"}
    assert cmds[1].content == ""

def test_handles_repeated_child_tags_as_list():
    llm_text = """
    <Question>
        <Text>Which environment?</Text>
        <Options>
            <Option>Dev</Option>
            <Option>Prod</Option>
        </Options>
    </Question>
    """
    cmds = parse_llm_output(llm_text)
    assert len(cmds) == 1
    assert cmds[0].content["Text"] == "Which environment?"
    assert cmds[0].content["Options"]["Option"] == ["Dev", "Prod"]

def test_parses_code_with_angle_brackets_and_ampersands_in_write_file():
    """
    Contract: WriteFile <Content> must support arbitrary source code containing
    '<', '>', and '&&' without failing XML parsing.
    """
    llm_text = """
    <WriteFile path="/tmp/test.ts">
        <Content>
const check = (a: number, b: number): boolean => {
    if (a < b && b > 0) {
        return true;
    }
    return false;
};
        </Content>
        <Summary>Added comparison function with < and && operators.</Summary>
    </WriteFile>
    """
    cmds = parse_llm_output(llm_text)
    assert len(cmds) == 1, "Parser dropped WriteFile block containing '<' and '&&'!"
    assert cmds[0].command == "WriteFile"
    assert "if (a < b && b > 0)" in cmds[0].content["Content"]

def test_parses_shell_operators_in_zsh_command():
    """
    Contract: Zsh <Command> must parse even if the LLM includes pipes, redirects, or &&.
    """
    llm_text = """
    <Zsh timeout="10">
        <Command>cat file.txt | grep "error" > output.log && echo "done"</Command>
    </Zsh>
    """
    cmds = parse_llm_output(llm_text)
    assert len(cmds) == 1, "Parser failed to extract Zsh block containing '>' and '&&'!"
    assert cmds[0].content["Command"] == 'cat file.txt | grep "error" > output.log && echo "done"'
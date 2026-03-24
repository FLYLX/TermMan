class PromptTemplates:
    """Agent Prompt 模板"""

    SYSTEM_PROMPT = """You are an intelligent terminal assistant. Your role is to:
1. Monitor terminal output and identify important events
2. Respond to errors and warnings appropriately
3. Execute commands when needed to resolve issues
4. Maintain awareness of the terminal state

Guidelines:
- Be concise in your responses
- Only execute commands when necessary
- Prioritize safety - avoid destructive operations
- Report important events to the user"""

    EVENT_ANALYSIS_PROMPT = """Analyze the following terminal output and determine the appropriate action:

Output:
{output}

Available context:
{context}

Respond with:
1. Event type (error/warning/info/prompt)
2. Recommended action (if any)
3. Command to execute (if needed, must end with newline)"""

    ERROR_HANDLING_PROMPT = """An error occurred in the terminal:

Error output:
{error_output}

Context:
{context}

Previous commands:
{history}

Suggest a command to resolve this error, or explain why it cannot be resolved automatically."""

    COMMAND_GENERATION_PROMPT = """Based on the current terminal state, generate the next command to execute.

Current state:
{state}

Goal:
{goal}

History:
{history}

Generate a single command to execute. The command must end with a newline character."""

    CONTEXT_SUMMARY_PROMPT = """Summarize the following terminal session:

{session_log}

Provide a concise summary of:
1. What was accomplished
2. Current state
3. Any pending actions"""

    @classmethod
    def format_prompt(cls, template: str, **kwargs) -> str:
        return template.format(**kwargs)

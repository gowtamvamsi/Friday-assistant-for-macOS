import os
import logging
import json
import re
from typing import Dict, List, Any, Tuple, Callable, TYPE_CHECKING
from engine.mlx_runtime import MLXRuntime

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

logger = logging.getLogger("friday.orchestrator")

SYSTEM_PROMPT_TEMPLATE = """You are Friday, a highly efficient, local macOS assistant. You control the user's system natively.
For every interaction, you must follow a strict ReAct (Thought-Action-Observation) loop to decide if and which tools to run.

You must output your thoughts and actions in this exact format:
Thought: <reasoning explaining why you need specific tools to address the user's request>
Action: {{"name": "tool_name", "arguments": {{"parameter_name": parameter_value}}}}

If no tools are required to answer the user's request (e.g. conversational chit-chat, greetings, or general knowledge questions), do NOT generate any Action block. Instead, output:
Thought: <reasoning explaining that no tools are needed>
Answer: <your direct conversational response>

Example 1 (Opening an application):
User: Open Safari
Thought: The user wants to launch Safari. I need to call the open_application tool.
Action: {{"name": "open_application", "arguments": {{"app_name": "Safari"}}}}

Example 2 (Greetings / Conversational):
User: Hello, how are you?
Thought: The user is greeting me. No system tools are needed. I will respond conversationally.
Answer: Hello! I'm Friday, your assistant. How can I help you today?

Example 3 (Building a project):
User: Build me a Flask todo REST API project
Thought: The user wants to scaffold a new project. I will use the architect_mode tool to create it.
Action: {{"name": "architect_mode", "arguments": {{"prompt": "A Flask REST API for a todo app", "project_name": "flask_todo"}}}}

Example 4 (Listing directory):
User: Show me my downloads folder
Thought: The user wants to see the files inside their downloads directory. I need to call the list_directory tool.
Action: {{"name": "list_directory", "arguments": {{"directory": "Downloads"}}}}

Example 5 (Volume control):
User: Is my system muted?
Thought: The user is asking about the mute status. I need to get the current system volume settings.
Action: {{"name": "get_volume_status", "arguments": {{}}}}

CRITICAL RULES:
- ONLY use the exact parameter names listed in the tool's schema. Never invent new parameters.
- If a tool has NO parameters, use an empty arguments dict: {{"arguments": {{}}}}
- Stop generating immediately after your Action block.
- For commands/actions that change the system state, output only one Action block at a time.

Available tools and their JSON schemas:
{tools_schemas}
"""

SYNTHESIS_SYSTEM_PROMPT = """You are Friday, a highly efficient and friendly local macOS assistant.
You have gathered the following information from running system tools:
{observations}

Now, present this gathered information to the user in a natural, pleasing, and conversational manner.
Do not mention raw JSON keys, data structures, status messages, or tool names. Summarize the facts and address the user directly as a helpful assistant.
Your entire response will be spoken aloud to the user, so write it to be read naturally.
"""

CONVERSATIONAL_SYSTEM_PROMPT = """You are Friday, a friendly, concise, and helpful macOS voice assistant. 
Answer the user's conversational query directly and concisely. 
Do NOT attempt to use any tools, and do NOT output any "Thought:", "Action:", or "Answer:" tags. Just output your direct conversational response."""


def parse_all_actions(text: str) -> List[Dict[str, Any]]:
    """Parses LLM output for all Action blocks and extracts their JSON payloads."""
    actions = []
    for match in re.finditer(r"Action:\s*", text, re.IGNORECASE):
        start_search = match.end()
        start_brace = text.find("{", start_search)
        if start_brace == -1:
            continue

        # Track brace balance to find the matching closing brace
        brace_count = 0
        end_brace = -1
        for i in range(start_brace, len(text)):
            char = text[i]
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    end_brace = i
                    break

        if end_brace != -1:
            json_str = text[start_brace:end_brace + 1]
            try:
                data = json.loads(json_str)
                if isinstance(data, dict):
                    actions.append(data)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse extracted JSON object: {json_str}. Error: {e}")

    return actions


class Orchestrator:
    """Orchestrates the cognitive loop (Thought-Action-Observation-Synthesis) for Friday."""

    # Tools that require biometric verification before execution
    SECURE_TOOLS = {
        "mute_volume",
        "unmute_volume",
        "set_volume",
        "close_application",
        "dead_drop",
    }

    # Aliases for tool names the small LLM commonly hallucinates.
    TOOL_ALIASES = {
        "create_project":       "architect_mode",
        "build_project":        "architect_mode",
        "scaffold_project":     "architect_mode",
        "generate_project":     "architect_mode",
        "make_project":         "architect_mode",
        "summarize_video":      "content_assassin",
        "youtube_notes":        "content_assassin",
        "get_video_notes":      "content_assassin",
        "transcribe_video":     "content_assassin",
        "share_file":           "dead_drop",
        "upload_file":          "dead_drop",
        "send_file":            "dead_drop",
        "launch_app":           "open_application",
        "launch_application":   "open_application",
        "start_app":            "open_application",
        "quit_application":     "close_application",
        "kill_application":     "close_application",
        "volume_up":            "set_volume",
        "volume_down":          "set_volume",
        "change_volume":        "set_volume",
        "adjust_volume":        "set_volume",
        "open_recent_file":     "find_recent_file",
        "recent_file":          "find_recent_file",
        "latest_file":          "find_recent_file",
        "newest_file":          "find_recent_file",
        "open_recent":          "find_recent_file",
        "open_latest":          "find_recent_file",
        "open_document":        "open_file",
        "open_folder":          "open_file",
        "list_files":           "list_directory",
        "show_files":           "list_directory",
        "list_folder":          "list_directory",
        "show_downloads":       "list_directory",
        "morning_digest":       "trigger_morning_digest",
        "morning_briefing":     "trigger_morning_digest",
        "get_morning_digest":   "trigger_morning_digest",
        "read_briefing":        "trigger_morning_digest",
        # Directory Analyst
        "directory_analyst":    "generate_feasibility_report",
        "feasibility_report":   "generate_feasibility_report",
        "project_feasibility":  "generate_feasibility_report",
    }

    def __init__(self, runtime: MLXRuntime, registry: "ToolRegistry", max_steps: int = 5):
        self.runtime = runtime
        self.registry = registry
        self.max_steps = max_steps
        self.on_security_failed: Callable[[str], None] | None = None
        self._biometrics_enabled: bool | None = None

    def _get_system_prompt(self) -> str:
        """Dynamically builds the system prompt with up-to-date tool schemas."""
        schemas = self.registry.generate_all_schemas()
        schemas_str = json.dumps(schemas, indent=2)
        return SYSTEM_PROMPT_TEMPLATE.format(tools_schemas=schemas_str)

    def _is_conversational(self, query: str) -> bool:
        """Determines if a query is purely conversational and does not require system tools."""
        q = query.lower().strip()
        conversational_phrases = [
            r"\bhello\b", r"\bhi\b", r"\bhey\b", r"\bhowdy\b", r"\bgreetings\b",
            r"how are you", r"how is it going", r"how's it going", r"how are you doing",
            r"who are you", r"what is your name", r"what's your name", r"are you there",
            r"thank you", r"thanks", r"nice to meet you", r"good morning", r"good afternoon",
            r"good evening", r"bye", r"goodbye", r"tell me a joke", r"status report"
        ]
        for pattern in conversational_phrases:
            if re.search(pattern, q):
                return True
        action_keywords = [
            "open", "launch", "close", "quit", "exit", "volume", "mute", "unmute", "app", "file", "list", "show", "build", "digest", "briefing", "report", "feasibility", "budget", "analyst"
        ]
        if not any(kw in q for kw in action_keywords):
            return True
        return False

    def _run_biometric_check(self, tool_name: str, stream_callback=None) -> bool:
        if self._biometrics_enabled is None:
            ref_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "data", "me.jpg"
            )
            self._biometrics_enabled = os.path.exists(ref_path)
            if not self._biometrics_enabled:
                logger.info("Biometric reference photo (data/me.jpg) not found — security gate disabled.")

        if not self._biometrics_enabled:
            return True

        if stream_callback:
            stream_callback("🔐 [Security: Running biometric check...]\n")

        from tools.security import capture_and_verify
        verified = capture_and_verify()

        if not verified and self.on_security_failed is not None:
            try:
                self.on_security_failed(tool_name)
            except Exception as cb_err:
                logger.warning(f"on_security_failed callback raised: {cb_err}")

        return verified

    def _split_query(self, query: str) -> List[str]:
        q_lower = query.lower()
        if " and " not in q_lower and " then " not in q_lower and "," not in q_lower:
            return [query]

        try:
            messages = [
                {"role": "system", "content": "You are a command splitter. Split compound user requests into a JSON list of independent simple commands. Return ONLY a valid JSON list of strings. Do not explain or include other text."},
                {"role": "user", "content": "Set volume to 100% and open Safari"},
                {"role": "assistant", "content": '["set volume to 100%", "open Safari"]'},
                {"role": "user", "content": "close notes then mute volume"},
                {"role": "assistant", "content": '["close notes", "mute volume"]'},
                {"role": "user", "content": query}
            ]
            response_chunks = []
            for chunk in self.runtime.generate_stream(messages):
                response_chunks.append(chunk)
            response_text = "".join(response_chunks).strip()
            # Extract JSON list
            match = re.search(r'\[.*\]', response_text, re.DOTALL)
            if match:
                commands = json.loads(match.group(0))
                if isinstance(commands, list) and all(isinstance(c, str) for c in commands):
                    logger.info(f"Split compound query '{query}' into: {commands}")
                    return commands
        except Exception as e:
            logger.warning(f"Failed to split query via LLM: {e}")

        return [query]

    def _strip_salutation(self, query: str) -> str:
        import re
        salutation_pattern = re.compile(
            r'^(?:hey|ok|okay|hi|hello)?\s*friday[,.]?\s*',
            re.IGNORECASE
        )
        stripped = salutation_pattern.sub('', query).strip()
        if stripped != query:
            logger.debug(f"Stripped salutation: '{query}' → '{stripped}'")
        return stripped if stripped else query

    def run_turn(
        self,
        user_input: str,
        history: List[Dict[str, str]],
        stream_callback: Callable[[str], None] | None = None
    ) -> Tuple[str, List[Dict[str, str]]]:
        """Runs a complete conversational turn, handling compound query splitting and sequential execution."""
        user_input = self._strip_salutation(user_input)
        sub_queries = self._split_query(user_input)
        
        current_history = list(history)
        last_answer = ""
        
        for i, sub_query in enumerate(sub_queries):
            if len(sub_queries) > 1 and stream_callback:
                stream_callback(f"\n\n👉 [Executing sub-command {i+1}/{len(sub_queries)}: '{sub_query}']\n")
            
            last_answer, current_history = self._run_single_query_turn(
                sub_query, current_history, stream_callback
            )
            
        return last_answer, current_history

    def _run_single_query_turn(
        self,
        user_input: str,
        history: List[Dict[str, str]],
        stream_callback: Callable[[str], None] | None = None
    ) -> Tuple[str, List[Dict[str, str]]]:
        """Runs a single ReAct loop turn with automated two-pass observation synthesis."""
        turn_history = list(history)

        if not turn_history or turn_history[-1].get("content") != user_input:
            turn_history.append({"role": "user", "content": user_input})

        # Check if query is conversational
        if self._is_conversational(user_input):
            system_msg = {"role": "system", "content": CONVERSATIONAL_SYSTEM_PROMPT}
            messages = [system_msg] + turn_history
            logger.info("Conversational Query - Bypassing tool checks")
            
            response_chunks = []
            for chunk in self.runtime.generate_stream(messages):
                response_chunks.append(chunk)
                if stream_callback:
                    stream_callback(chunk)
            final_response = "".join(response_chunks).strip()
            turn_history.append({"role": "assistant", "content": final_response})
            return final_response, turn_history

        # ── Reasoning and Execution Pass ──
        system_msg = {"role": "system", "content": self._get_system_prompt()}
        
        logger.info("Reasoning Phase: evaluating prompt against tool schemas...")
        react_prompt_history = list(turn_history)
        
        # We output thoughts to stream_callback so it shows in the Developer Console / GUI text
        # But we do it inside bracket tags to allow TTS engine or downstream listeners to omit them if desired.
        response_chunks = []
        for chunk in self.runtime.generate_stream([system_msg] + react_prompt_history):
            response_chunks.append(chunk)
            if stream_callback:
                stream_callback(chunk)
                
        response_text = "".join(response_chunks).strip()
        logger.debug(f"LLM Reasoning Output:\n{response_text}")
        
        actions = parse_all_actions(response_text)
        
        if not actions:
            # Fallback if the LLM produced no Action block (acts like conversational response)
            logger.info("No actions parsed. Directing to fallback response.")
            answer_match = re.search(r"Answer:\s*(.*)", response_text, re.DOTALL | re.IGNORECASE)
            final_answer = answer_match.group(1).strip() if answer_match else response_text
            turn_history.append({"role": "assistant", "content": response_text})
            return final_answer, turn_history

        # Execute actions
        observations = []
        for action_data in actions:
            tool_name = action_data.get("name")
            tool_args = action_data.get("arguments", {})

            # Alias resolution
            if tool_name not in self.registry._tools and tool_name in self.TOOL_ALIASES:
                tool_name = self.TOOL_ALIASES[tool_name]

            # Biometrics check
            if tool_name in self.SECURE_TOOLS:
                if not self._run_biometric_check(tool_name, stream_callback):
                    obs = {"status": "error", "message": "Biometric verification failed. Access denied."}
                    observations.append(obs)
                    continue

            logger.info(f"Executing tool '{tool_name}' natively with args: {tool_args}")
            if stream_callback:
                stream_callback(f"\n\n⚙️  [System: Executing tool '{tool_name}'...]\n")
                
            obs = self.registry.execute(tool_name, tool_args)
            logger.info(f"Tool '{tool_name}' returned status: {obs.get('status')}")
            
            if stream_callback:
                status_icon = "✅" if obs.get("status") == "success" else "❌"
                stream_callback(f"{status_icon} [System Observation: {obs.get('message')}]\n\n")
            observations.append(obs)

        # ── Two-Pass Synthesis Phase ──
        # Compile raw observation data
        obs_strings = []
        for i, obs in enumerate(observations):
            prefix = f"Tool {i+1} Output: " if len(observations) > 1 else "Tool Output: "
            obs_strings.append(f"{prefix}{obs.get('message', 'Done.')} | Full Data: {json.dumps(obs.get('data', {}))}")
        observations_block = "\n".join(obs_strings)

        logger.info("Synthesis Phase: Feeding observations back to LLM...")
        synthesis_prompt = SYNTHESIS_SYSTEM_PROMPT.format(observations=observations_block)
        
        # We perform a second LLM call strictly to synthesize the final answer.
        # This keeps tool output / raw JSON from leaking into the voice response.
        synthesis_messages = [
            {"role": "system", "content": synthesis_prompt},
            {"role": "user", "content": f"Please synthesize the final voice response for the query: '{user_input}'"}
        ]
        
        # Prefix answer tag so that main.py / TTS Stream accumulator knows exactly where to extract
        if stream_callback:
            stream_callback("Answer: ")
            
        synthesis_chunks = []
        for chunk in self.runtime.generate_stream(synthesis_messages):
            synthesis_chunks.append(chunk)
            if stream_callback:
                stream_callback(chunk)
                
        final_answer = "".join(synthesis_chunks).strip()
        
        # Record the complete execution state in the actual chat history
        turn_history.append({
            "role": "assistant",
            "content": f"{response_text}\n\nObservation: {observations_block}\n\nAnswer: {final_answer}"
        })
        
        return final_answer, turn_history

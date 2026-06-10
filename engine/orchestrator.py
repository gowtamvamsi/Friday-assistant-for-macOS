import os
import logging
import json
import re
from typing import Dict, List, Any, Tuple, Callable, TYPE_CHECKING
from engine.mlx_runtime import MLXRuntime

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

logger = logging.getLogger("friday.orchestrator")

SYSTEM_PROMPT_TEMPLATE = """You are Friday, a highly efficient, local macOS assistant. You control the user's system natively. Keep your responses concise, action-oriented, and conversational.

To call a tool, respond with a Thought and an Action in this exact format:
Thought: <reasoning>
Action: {{"name": "tool_name", "arguments": {{"parameter_name": parameter_value}}}}

After a tool call runs, you will receive an "Observation:" block. If the tool succeeded and the task is complete, you MUST output your final answer in this exact format:
Thought: <reasoning>
Answer: Done.

Example 1 (Opening an application):
User: Open Safari
Thought: The user wants to open Safari. I will use the open_application tool.
Action: {{"name": "open_application", "arguments": {{"app_name": "Safari"}}}}
Observation: SUCCESS — Successfully opened and focused application 'Safari'.
Thought: Safari has opened successfully. I am done.
Answer: Done.

Example 2 (Greetings / Conversational):
User: Hello, how are you?
Thought: The user is greeting me. I will respond conversationally.
Answer: Hello! I'm Friday, your assistant. How can I help you today?

Example 3 (Building a coding project):
User: Build me a Flask REST API project
Thought: The user wants to scaffold a new coding project. I will use the architect_mode tool.
Action: {{"name": "architect_mode", "arguments": {{"prompt": "A Flask REST API for a todo app", "project_name": "flask_todo"}}}}
Observation: SUCCESS — Project 'flask_todo' scaffolded at scratch/projects/flask_todo.
Thought: The project has been created. I am done.
Answer: Done.

Example 4 (YouTube study notes):
User: Take notes on youtube.com/watch?v=abc123
Thought: The user wants study notes from a YouTube video. I will use the content_assassin tool.
Action: {{"name": "content_assassin", "arguments": {{"youtube_url": "https://www.youtube.com/watch?v=abc123"}}}}
Observation: SUCCESS — Study notes generated and saved to scratch/notes_abc123.md
Thought: The notes have been generated. I am done.
Answer: Done.

Example 5 (Opening a recent file):
User: Open the most recent file in Downloads
Thought: The user wants to open the most recently modified file in their Downloads folder. I will use the find_recent_file tool.
Action: {{"name": "find_recent_file", "arguments": {{"directory": "Downloads"}}}}
Observation: SUCCESS — Opened 'report.pdf' from Downloads (last modified Jun 08 at 02:30 PM).
Thought: The file has been opened successfully. I am done.
Answer: Done.

Example 6 (Listing directory - Question/Query):
User: Show me my documents
Thought: The user wants to see the files in their Documents folder. I will use the list_directory tool.
Action: {{"name": "list_directory", "arguments": {{"directory": "Documents"}}}}
Observation: SUCCESS — Found 12 items in Documents. Most recent: letter.docx, resume.pdf, sheet.xlsx, prep.py, notes.txt
Thought: The user asked to see their documents. I will organize the files list from the observation and answer their question.
Answer: Here are the most recent files in your Documents directory: letter.docx, resume.pdf, sheet.xlsx, prep.py, and notes.txt.

Example 7 (Getting system status - Question/Query):
User: Is the volume muted?
Thought: The user wants to know if the system volume is muted. I will use the get_volume_status tool.
Action: {{"name": "get_volume_status", "arguments": {{}}}}
Observation: SUCCESS — System volume is 50% (state: active).
Thought: I have the volume status. I will answer the user's question.
Answer: No, the volume is not muted. It is currently set to 50%.

CRITICAL RULES:
- ONLY use the exact parameter names listed in the tool's schema. Never invent new parameters.
- If a tool has NO parameters, use an empty arguments dict: {{"arguments": {{}}}}
- After you output the Action block, STOP generating immediately.
- For commands/actions (e.g. "open Safari", "mute volume", "build project"), once the tool has succeeded, output the `Answer: Done.` block immediately.
- For questions/information queries (e.g. "what files are in my downloads?", "what is the volume level?", "list files"), use the tool's observation results to organize and write a helpful summary response in the `Answer:` block.

Available tools and their JSON schemas:
{tools_schemas}
"""

CONVERSATIONAL_SYSTEM_PROMPT = """You are Friday, a friendly, concise, and helpful macOS voice assistant. 
Answer the user's conversational query directly and concisely. 
Do NOT attempt to use any tools, and do NOT output any "Thought:", "Action:", or "Answer:" tags. Just output your direct conversational response."""



def parse_all_actions(text: str) -> List[Dict[str, Any]]:
    """Parses LLM output for all Action blocks and extracts their JSON payloads.

    Uses a brace-counting scanner for each 'Action:' label detected to safely
    isolate each JSON object independently, tolerating multi-line outputs or trailing text.

    Args:
        text (str): The raw text response from the LLM.

    Returns:
        List[Dict[str, Any]]: A list of parsed JSON tool call dictionaries.
    """
    actions = []
    # Locate all occurrences of 'Action:' label case-insensitively
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
    """Orchestrates the cognitive loop (Thought-Action-Observation) for Friday."""

    # Tools that require biometric verification before execution
    SECURE_TOOLS = {
        "mute_volume",
        "unmute_volume",
        "set_volume",
        "close_application",
        "dead_drop",
    }

    # Aliases for tool names the small LLM commonly hallucinates.
    # Maps hallucinated name -> real registered tool name.
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
        # File operations
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
        # Scheduled tasks / digests
        "morning_digest":       "trigger_morning_digest",
        "morning_briefing":     "trigger_morning_digest",
        "get_morning_digest":   "trigger_morning_digest",
        "read_briefing":        "trigger_morning_digest",
    }

    def __init__(self, runtime: MLXRuntime, registry: "ToolRegistry", max_steps: int = 5):
        """Initializes the Orchestrator.

        Args:
            runtime (MLXRuntime): The local MLX model runner.
            registry (ToolRegistry): The Phase 1 automation tools registry.
            max_steps (int): Safety threshold to prevent infinite tool loops.
        """
        self.runtime = runtime
        self.registry = registry
        self.max_steps = max_steps
        # Optional callback: called with tool_name when biometric check fails
        # Set from main.py to broadcast alert and speak "Access Denied"
        self.on_security_failed: Callable[[str], None] | None = None
        # Whether biometric security is active (disabled if data/me.jpg not present)
        self._biometrics_enabled: bool | None = None  # None = not yet checked

    def _get_system_prompt(self) -> str:
        """Dynamically builds the system prompt with up-to-date tool schemas."""
        schemas = self.registry.generate_all_schemas()
        schemas_str = json.dumps(schemas, indent=2)
        return SYSTEM_PROMPT_TEMPLATE.format(tools_schemas=schemas_str)

    def _is_conversational(self, query: str) -> bool:
        """Determines if a query is purely conversational and does not require system tools."""
        q = query.lower().strip()
        
        # Common greetings and simple chat queries
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
                
        # Action-oriented keywords that require tools
        action_keywords = [
            "open", "launch", "close", "quit", "exit", "volume", "mute", "unmute", "app"
        ]
        
        # If none of the action keywords are in the query, treat it as conversational
        if not any(kw in q for kw in action_keywords):
            return True
            
        return False

    def _run_biometric_check(self, tool_name: str, stream_callback=None) -> bool:
        """
        Runs the biometric security verification before executing a secure tool.
        Returns True if the check passed or biometrics are not configured.
        """
        # Lazy-check if biometrics are configured
        if self._biometrics_enabled is None:
            ref_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "data", "me.jpg"
            )
            self._biometrics_enabled = os.path.exists(ref_path)
            if not self._biometrics_enabled:
                logger.info(
                    "Biometric reference photo (data/me.jpg) not found — "
                    "security gate disabled. Run friday_enroll.py to set it up."
                )

        if not self._biometrics_enabled:
            return True  # Graceful pass-through if not enrolled

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
        """Uses the local MLX model to split a compound request into independent simple commands."""
        # Simple heuristic: bypass LLM splitting if the query is clearly a single simple command.
        # Note: commas used in salutations (e.g. "Friday, open Safari") are already stripped
        # by _strip_salutation() before this is called, so we only catch genuine compound commas.
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

            # Find the JSON list bracket
            start = response_text.find("[")
            end = response_text.rfind("]")
            if start != -1 and end != -1:
                json_str = response_text[start:end+1]
                commands = json.loads(json_str)
                if isinstance(commands, list) and all(isinstance(c, str) for c in commands):
                    logger.info(f"Split compound query '{query}' into: {commands}")
                    return commands
        except Exception as e:
            logger.warning(f"Failed to split query via LLM: {e}")

        # Fallback to simple split on " and " if LLM fails
        return [query]

    def _strip_salutation(self, query: str) -> str:
        """
        Removes wake-word salutations from the start of a query so the command
        splitter never sees them as standalone sub-commands.

        Examples:
          "Friday, build me X"   → "build me X"
          "Hey Friday, open X"   → "open X"
          "Ok Friday open X"     → "open X"   (no comma case)
          "build me X"           → "build me X"  (unchanged)
        """
        import re
        # Match optional prefix words (hey, ok, okay, hi) + wake word + optional comma/space
        salutation_pattern = re.compile(
            r'^(?:hey|ok|okay|hi|hello)?\s*friday[,.]?\s*',
            re.IGNORECASE
        )
        stripped = salutation_pattern.sub('', query).strip()
        if stripped != query:
            logger.debug(f"Stripped salutation: '{query}' → '{stripped}'")
        return stripped if stripped else query  # Never return empty string

    def run_turn(
        self,
        user_input: str,
        history: List[Dict[str, str]],
        stream_callback: Callable[[str], None] | None = None
    ) -> Tuple[str, List[Dict[str, str]]]:
        """Runs a complete conversational turn, handling compound query splitting and sequential execution.

        Args:
            user_input (str): The natural language query from the user.
            history (list): List of conversation messages (excluding current user query).
            stream_callback (callable): Optional callback for streaming raw output tokens.

        Returns:
            Tuple[str, List[Dict[str, str]]]: A tuple containing:
                - final_answer (str): The conversational response meant for the user.
                - updated_history (list): The updated chat history including thoughts and observations.
        """
        # Strip wake-word salutations BEFORE splitting so 'Friday, X and Y' splits correctly
        user_input = self._strip_salutation(user_input)

        # Split compound requests
        sub_queries = self._split_query(user_input)
        
        current_history = list(history)
        last_answer = ""
        
        for i, sub_query in enumerate(sub_queries):
            if len(sub_queries) > 1 and stream_callback:
                stream_callback(f"\n\n👉 [Executing sub-command {i+1}/{len(sub_queries)}: '{sub_query}']\n")
            
            # Run standard ReAct loop for this sub-query
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
        """Runs a single ReAct loop turn for one command."""
        # Create a local copy of history to manipulate
        turn_history = list(history)

        # Append the new user input if it is not already the last item
        if not turn_history or turn_history[-1].get("content") != user_input:
            turn_history.append({"role": "user", "content": user_input})

        # Set the system persona at the beginning of context
        if self._is_conversational(user_input):
            system_msg = {"role": "system", "content": CONVERSATIONAL_SYSTEM_PROMPT}
        else:
            system_msg = {"role": "system", "content": self._get_system_prompt()}

        # Keep running the ReAct loop until we reach final Answer or hit safety threshold
        last_failed_call = None  # Tracks (tool_name, args_str) of last failed tool call
        for step in range(self.max_steps):
            messages = [system_msg] + turn_history
            logger.info(f"ReAct Loop - Step {step + 1}/{self.max_steps}")

            # Stream model output
            response_chunks = []
            for chunk in self.runtime.generate_stream(messages):
                response_chunks.append(chunk)
                if stream_callback:
                    stream_callback(chunk)

            response_text = "".join(response_chunks).strip()
            logger.debug(f"LLM Step Output:\n{response_text}")

            # Try to parse all tool calls
            actions = parse_all_actions(response_text)

            if actions:
                # Add the assistant's Thought + Action outputs to history
                turn_history.append({"role": "assistant", "content": response_text})

                observations = []
                for action_data in actions:
                    tool_name = action_data.get("name")
                    tool_args = action_data.get("arguments", {})

                    # Validate tool schema format
                    if not tool_name or not isinstance(tool_args, dict):
                        obs = {
                            "status": "error",
                            "message": f"Malformed Action format: {action_data}. Must be a JSON object with 'name' (str) and 'arguments' (dict)."
                        }
                    else:
                        # Execute tool via the registry
                        logger.info(f"Orchestrator invoking tool '{tool_name}' with arguments: {tool_args}")

                        # ── Alias Resolution: remap hallucinated tool names to real ones ──
                        if tool_name not in self.registry._tools and tool_name in self.TOOL_ALIASES:
                            real_name = self.TOOL_ALIASES[tool_name]
                            logger.info(f"Tool alias resolved: '{tool_name}' → '{real_name}'")
                            if stream_callback:
                                stream_callback(f"\n\n⚙️  [System: Executing tool '{real_name}' (resolved from '{tool_name}')...]\n")
                            tool_name = real_name
                        else:
                            if stream_callback:
                                stream_callback(f"\n\n⚙️  [System: Executing tool '{tool_name}'...]\n")

                        # ── Phase 5: Biometric Security Gate ──────────────────
                        if tool_name in self.SECURE_TOOLS:
                            biometric_passed = self._run_biometric_check(tool_name, stream_callback)
                            if not biometric_passed:
                                obs = {
                                    "status": "error",
                                    "message": "Biometric verification failed. Access denied."
                                }
                                logger.warning(f"Biometric check failed for tool '{tool_name}'. Blocking execution.")
                                if stream_callback:
                                    stream_callback(f"🔒 [Security: Biometric verification FAILED. Access denied for '{tool_name}'.]\n\n")
                                observations.append(obs)
                                continue

                        obs = self.registry.execute(tool_name, tool_args)

                        logger.info(f"Tool '{tool_name}' returned: {obs}")
                        if stream_callback:
                            status_icon = "✅" if obs.get("status") == "success" else "❌"
                            stream_callback(f"{status_icon} [System Observation: {obs.get('message')}]\n\n")

                    observations.append(obs)

                # Build a plain-text observation for the LLM — raw JSON confuses small models
                obs_parts = []
                for i, obs in enumerate(observations):
                    prefix = f"Tool {i+1}: " if len(observations) > 1 else ""
                    if obs.get("status") == "success":
                        obs_parts.append(f"{prefix}SUCCESS — {obs.get('message', 'Done.')}")
                    else:
                        obs_parts.append(f"{prefix}ERROR — {obs.get('message', 'Unknown error.')}")

                observation_content = "Observation: " + " | ".join(obs_parts)
                turn_history.append({"role": "user", "content": observation_content})

                # ── Repeated-failure guard ─────────────────────────────────────
                # If every tool in this step failed, check if it's the same call
                # as last time. If so, break immediately — the model is stuck.
                all_failed = all(o.get("status") != "success" for o in observations)
                if all_failed and len(actions) == 1:
                    current_call = (actions[0].get("name"), json.dumps(actions[0].get("arguments", {}), sort_keys=True))
                    if current_call == last_failed_call:
                        err_msg = observations[0].get("message", "Tool not found.")
                        logger.warning(f"ReAct loop breaking early — repeated identical failure: {current_call}")
                        fail_answer = f"I'm sorry, I couldn't complete that. {err_msg}"
                        turn_history.append({"role": "assistant", "content": f"Answer: {fail_answer}"})
                        return fail_answer, turn_history
                    last_failed_call = current_call
                else:
                    last_failed_call = None  # Reset on success or mixed results

                # Loop again so the LLM processes the tool observation
                continue
            else:
                # No action generated: the LLM is done and ready to answer.
                # Add the assistant's final response to history
                turn_history.append({"role": "assistant", "content": response_text})

                # Try to extract the text after "Answer:" tag if present
                answer_match = re.search(r"Answer:\s*(.*)", response_text, re.DOTALL | re.IGNORECASE)
                if answer_match:
                    final_answer = answer_match.group(1).strip()
                else:
                    # Fallback if the model didn't use the tag
                    final_answer = response_text

                return final_answer, turn_history

        # If we exit the loop without return, we hit the max steps threshold
        timeout_msg = "I attempted to resolve your request but had to stop to prevent an infinite loop of system actions."
        turn_history.append({"role": "assistant", "content": f"Thought: Safety limit reached.\nAnswer: {timeout_msg}"})
        return timeout_msg, turn_history


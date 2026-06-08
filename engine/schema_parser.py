import inspect
import typing
import logging
from typing import Callable, Any, Dict, List, Tuple

logger = logging.getLogger("friday.schema_parser")

def parse_docstring(docstring: str | None) -> Tuple[str, Dict[str, str]]:
    """Parses a Python docstring (Google style) to extract descriptions.

    Args:
        docstring (str | None): The raw docstring from the function.

    Returns:
        Tuple[str, Dict[str, str]]: A tuple containing:
            - main_desc (str): The main descriptive summary of the tool.
            - param_descs (dict): A mapping of parameter names to their descriptions.
    """
    if not docstring:
        return "", {}

    lines = docstring.split("\n")
    main_desc_lines = []
    param_descs = {}
    
    current_param = None
    in_args_section = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Detect the start of the arguments section
        if stripped.lower() in ("args:", "parameters:", "arguments:"):
            in_args_section = True
            continue

        if in_args_section:
            # Check indentation to determine if we are still inside the Args section
            indent = len(line) - len(line.lstrip())
            if indent > 0:
                if ":" in stripped:
                    param_part, desc_part = stripped.split(":", 1)
                    # Extract parameter name (strip any type annotation in parentheses)
                    param_name = param_part.split("(")[0].strip()
                    param_descs[param_name] = desc_part.strip()
                    current_param = param_name
                elif current_param:
                    # Append wrapped lines to the current parameter's description
                    param_descs[current_param] += " " + stripped
            else:
                # End of indented args block; treat as general description
                in_args_section = False
                main_desc_lines.append(stripped)
        else:
            main_desc_lines.append(stripped)

    main_desc = " ".join(main_desc_lines).strip()
    return main_desc, param_descs


def generate_schema(func: Callable[..., Any]) -> Dict[str, Any]:
    """Generates a standard JSON schema for the specified Python function.

    This schema is compatible with modern LLM function calling (OpenAI/Gemini).

    Args:
        func: The Python function.

    Returns:
        dict: The tool's schema.
    """
    func_name = func.__name__
    
    # Inspect parameters and type annotations
    sig = inspect.signature(func)
    type_hints = typing.get_type_hints(func)
    main_desc, param_descs = parse_docstring(func.__doc__)

    properties = {}
    required = []

    # Map Python types to standard JSON schema type strings
    type_mapping = {
        int: "integer",
        float: "number",
        str: "string",
        bool: "boolean",
        dict: "object",
        list: "array"
    }

    for param_name, param in sig.parameters.items():
        # Skip python args/kwargs indicators if any
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        param_type = type_hints.get(param_name, Any)
        json_type = type_mapping.get(param_type, "string")

        # Extract parameter description from docstring, or fall back to a default
        description = param_descs.get(param_name, f"The {param_name} parameter.")

        properties[param_name] = {
            "type": json_type,
            "description": description
        }

        # If parameter has no default value, it is required
        if param.default == inspect.Parameter.empty:
            required.append(param_name)

    return {
        "name": func_name,
        "description": main_desc,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False
        }
    }

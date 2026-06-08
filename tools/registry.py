import inspect
import logging
from typing import Callable, Any, Dict, List
from engine.schema_parser import generate_schema

logger = logging.getLogger("friday.registry")


class ToolRegistry:
    """Manages the registration, introspection, and execution of Friday tools."""

    def __init__(self):
        self._tools: Dict[str, Callable[..., Dict[str, Any]]] = {}

    def register(self, func: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
        """Decorator to register a function as an automation tool.

        Args:
            func: The Python function to register. Must return a dict.

        Returns:
            The original function, unmodified, so it can still be called normally.
        """
        tool_name = func.__name__
        if tool_name in self._tools:
            logger.warning(f"Overwriting already registered tool: {tool_name}")
        
        self._tools[tool_name] = func
        logger.info(f"Registered tool: '{tool_name}'")
        return func

    def get_tool(self, name: str) -> Callable[..., Dict[str, Any]] | None:
        """Retrieves a registered tool by its function name."""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """Returns a list of all registered tool names."""
        return list(self._tools.keys())

    def generate_schema(self, name: str) -> Dict[str, Any] | None:
        """Generates a standard JSON schema for the specified tool.

        This schema is compatible with modern LLM function calling (OpenAI/Gemini).

        Args:
            name (str): The name of the registered tool.

        Returns:
            dict | None: The tool's schema, or None if the tool does not exist.
        """
        func = self.get_tool(name)
        if not func:
            return None
        return generate_schema(func)

    def generate_all_schemas(self) -> List[Dict[str, Any]]:
        """Generates schemas for all registered tools."""
        return [self.generate_schema(name) for name in self.list_tools()]  # type: ignore

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a registered tool by name with the given argument dictionary.

        Args:
            name (str): Name of the tool.
            args (dict): Dictionary of keyword arguments to pass.

        Returns:
            dict: The execution result, containing at minimum "status" and "message".
        """
        func = self.get_tool(name)
        if not func:
            return {
                "status": "error",
                "message": f"Tool '{name}' not found in registry."
            }

        try:
            # Perform a quick signature validation before invoking
            sig = inspect.signature(func)
            # Bind arguments to ensure they match signature
            bound_args = sig.bind(**args)
            bound_args.apply_defaults()
            
            # Execute tool function
            result = func(*bound_args.args, **bound_args.kwargs)
            
            if not isinstance(result, dict):
                return {
                    "status": "success",
                    "message": f"Tool executed, but did not return a dictionary.",
                    "data": {"raw_result": result}
                }
            return result
        except TypeError:
            # Build a helpful corrective message showing the valid signature
            sig_params = {}
            required_params = []
            for p_name, p in inspect.signature(func).parameters.items():
                if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                    continue
                annotation = p.annotation
                type_name = annotation.__name__ if hasattr(annotation, '__name__') else str(annotation)
                sig_params[p_name] = type_name
                if p.default == inspect.Parameter.empty:
                    required_params.append(p_name)
            if sig_params:
                valid_params_str = ', '.join(f'"{k}": {v}' for k, v in sig_params.items())
                required_str = f"Required: {required_params}. " if required_params else "No required parameters. "
                correction = f"{required_str}Valid arguments are: {{{valid_params_str}}}. Do NOT pass any other keys."
            else:
                correction = f'This tool takes NO arguments. Use: Action: {{"name": "{name}", "arguments": {{}}}}'
            return {
                "status": "error",
                "message": f"Wrong arguments for tool '{name}'. {correction}"
            }
        except Exception as e:
            logger.exception(f"Exception executing tool '{name}': {str(e)}")
            return {
                "status": "error",
                "message": f"Execution failed: {str(e)}"
            }


# Singleton registry instance for global import
registry = ToolRegistry()

def register_tool(func: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
    """Decorator for registering tools directly using `@register_tool`."""
    return registry.register(func)

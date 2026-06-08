import os
import logging
from typing import Dict, List, Generator
from mlx_lm import load, stream_generate
from mlx_lm.sample_utils import make_sampler

logger = logging.getLogger("friday.mlx_runtime")

class MLXRuntime:
    """Manages the local Apple MLX LLM runtime for Friday."""

    def __init__(self, model_id: str | None = None):
        """Initializes the MLX Runtime.

        Args:
            model_id (str | None): Hugging Face repo ID or local path of the model.
                                  Defaults to env variable FRIDAY_MODEL or
                                  'mlx-community/gemma-3-12b-it-4bit'.
        """
        # Default to a 12B Gemma-3 model (quantized to 4-bit) as requested.
        # Allow overriding with a smaller model like 'mlx-community/gemma-2-2b-it-4bit'
        # for faster downloads and testing.
        self.model_id = model_id or os.environ.get("FRIDAY_MODEL", "mlx-community/gemma-3-12b-it-4bit")
        self.model = None
        self.tokenizer = None

    def load_model(self):
        """Loads the model and tokenizer into memory.

        Performs a lazy-load on the first request to avoid blocking initialization.
        """
        if self.model is None or self.tokenizer is None:
            logger.info(f"Loading MLX model '{self.model_id}' (downloads model if not cached)...")
            self.model, self.tokenizer = load(self.model_id)
            logger.info(f"Successfully loaded MLX model '{self.model_id}'.")

    def generate(self, messages: List[Dict[str, str]], max_tokens: int = 1000, temp: float = 0.0) -> str:
        """Runs synchronous inference to return the complete response.

        Args:
            messages (list): List of chat message dictionaries (role, content).
            max_tokens (int): Maximum tokens to generate.
            temp (float): Temperature for generation (default 0.0 for deterministic).

        Returns:
            str: The fully generated response text.
        """
        self.load_model()
        # Apply the model's standard chat template to format the prompt correctly
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        sampler = make_sampler(temp)
        chunks = []
        for response in stream_generate(self.model, self.tokenizer, prompt=prompt, max_tokens=max_tokens, sampler=sampler):
            chunks.append(response.text)
            
        return "".join(chunks)

    def generate_stream(self, messages: List[Dict[str, str]], max_tokens: int = 1000, temp: float = 0.0) -> Generator[str, None, None]:
        """Generator that streams response text chunks as they are generated.

        Args:
            messages (list): List of chat message dictionaries (role, content).
            max_tokens (int): Maximum tokens to generate.
            temp (float): Temperature for generation (default 0.0).

        Yields:
            str: Each newly generated text chunk.
        """
        self.load_model()
        # Apply the model's standard chat template
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        sampler = make_sampler(temp)
        for response in stream_generate(self.model, self.tokenizer, prompt=prompt, max_tokens=max_tokens, sampler=sampler):
            yield response.text

import json
import re
from typing import Any


def clean_llm_response(raw_text: str) -> str:
    """Sanitizes LLM responses by unwrapping markdown code blocks and extraction from JSON tool payloads.

    Handles outputs formatted like:
    - ```json {"action": "done", "args": {"response": "..."}} ```
    - {"action": "done", "args": {"response": "..."}}
    - Plain text responses
    """
    if not raw_text or not isinstance(raw_text, str):
        return raw_text or ""

    text = raw_text.strip()

    # 1. Strip markdown code fence blocks (e.g., ```json ... ``` or ```text ... ```)
    if text.startswith("```"):
        # Match leading fence (e.g. ```json or ```) and trailing fence (```)
        fence_match = re.match(r"^```[a-zA-Z0-9_-]*\n?(.*?)\n?```$", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

    # 2. Attempt JSON parsing if text resembles a JSON structure
    if (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    ):
        try:
            data: Any = json.loads(text)
            if isinstance(data, dict):
                # Check for standard action / response wrapper patterns
                args = data.get("args")
                candidate = None
                if isinstance(args, dict):
                    candidate = (
                        args.get("response")
                        or args.get("text")
                        or args.get("answer")
                        or args.get("result")
                    )
                if not candidate:
                    candidate = (
                        data.get("response")
                        or data.get("text")
                        or data.get("answer")
                        or data.get("result")
                    )

                if candidate and isinstance(candidate, str):
                    # Recursively clean candidate in case of nested markdown/JSON wrappers
                    return clean_llm_response(candidate)
            elif isinstance(data, str):
                return clean_llm_response(data)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    return text

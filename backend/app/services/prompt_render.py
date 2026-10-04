"""Render validated prompt templates shared by the prompt stores."""

def render_prompt(prompts: dict[str, str], key: str, **kwargs: object) -> str:
    text = prompts.get(key)
    if text is None or not str(text).strip():
        raise RuntimeError(f"Active configuration is missing prompt '{key}'")
    try:
        return str(text).format(**kwargs)
    except KeyError as exc:
        raise RuntimeError(f"Prompt '{key}' missing placeholder {exc}") from exc

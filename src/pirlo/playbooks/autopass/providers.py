SUPPORTED_PROVIDERS = {
    "dashscope": {
        "env_names": ["DASHSCOPE_API_KEY", "ALIBABA_API_KEY"],
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "gemini": {
        "env_names": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    },
    "openai": {
        "env_names": ["OPENAI_API_KEY"],
        "default_base_url": "https://api.openai.com/v1",
    },
    "anthropic": {
        "env_names": ["ANTHROPIC_API_KEY"],
        "default_base_url": None,
    },
}

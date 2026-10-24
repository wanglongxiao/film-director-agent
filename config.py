"""BytePlus ModelArk configuration loader.

Reads settings from environment variables, falling back to the values in .env
(via python-dotenv). Import this module to access the shared config values.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# Base URL for model invocation
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3")

# API Key (get it from the BytePlus ModelArk console)
ARK_API_KEY = os.getenv("ARK_API_KEY") or os.getenv("API_KEY", "")

# Main agent controls the conversation and story setup independently of writers.
MAIN_AGENT_MODEL = {
    "endpoint": os.environ["MAIN_AGENT_MODEL"],
    "max_tokens": int(os.environ["MAIN_AGENT_MAX_TOKENS"]),
}

# Image generation model (Seedream)
LLM_MODEL_IMAGE = os.environ["LLM_MODEL_IMAGE"]

# Seedream output size, e.g. "2048x1536" for a 4:3 aspect ratio.
IMAGE_SIZE = os.environ["IMAGE_SIZE"]

# Session selections always use these model-specific ceilings.
CHAT_MODELS = {
    "deepseek-1017": {
        "endpoint": os.environ["SCRIPT_DEEPSEEK_1017_MODEL"],
        "max_tokens": int(os.environ["SCRIPT_DEEPSEEK_1017_MAX_TOKENS"]),
    },
    "seed-sc-0215": {
        "endpoint": os.environ["SCRIPT_SEED_SC_0215_MODEL"],
        "max_tokens": int(os.environ["SCRIPT_SEED_SC_0215_MAX_TOKENS"]),
    },
}
DEFAULT_TEXT_MODEL = "deepseek-1017"

# Compatibility aliases for existing tools.
LLM_MODEL_CHAT = MAIN_AGENT_MODEL["endpoint"]
LLM_MAX_TOKENS = MAIN_AGENT_MODEL["max_tokens"]
NOVEL_CHAPTER_MAX_TOKENS = CHAT_MODELS[DEFAULT_TEXT_MODEL]["max_tokens"]


def normalize_text_model(value):
    """Keep previously saved model selections readable."""
    if isinstance(value, str):
        return {
            "deepseek": "deepseek-1017",
            "deepseek-0910": "deepseek-1017",
            "seed-sc": "seed-sc-0215",
        }.get(value, value)
    return value

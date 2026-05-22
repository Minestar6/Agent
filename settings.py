import os
from pathlib import Path

import dotenv


dotenv.load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UTILS_DIR = PROJECT_ROOT / "utils"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
TOKEN_CONFIG_DIR = Path(os.getenv("TOKEN_CONFIG_DIR", PROJECT_ROOT / "token_config"))


def get_env(name: str, default=None):
    return os.getenv(name, default)


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value

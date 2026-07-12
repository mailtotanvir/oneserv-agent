import os
from dotenv import load_dotenv

load_dotenv()

class OneServConfig:
    APP_NAME: str = "oneserv-agent"
    VERSION: str = "1.0.0"
    HOST: str = os.getenv("ONESERV_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("ONESERV_PORT", 8002))
    
    # DB Configuration
    DB_PATH: str = os.getenv("ONESERV_DB_PATH", os.path.join(os.path.dirname(__file__), "oneserv.db"))
    
    # Provider options
    PROVIDER_MODE: str = os.getenv("ONESERV_PROVIDER_MODE", "mock")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

config = OneServConfig()

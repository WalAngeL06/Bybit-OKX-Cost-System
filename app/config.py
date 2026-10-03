import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# Load existing .env
load_dotenv(dotenv_path=ENV_PATH)

class Settings:
    # Bybit
    BYBIT_API_KEY: str = os.getenv("BYBIT_API_KEY", "")
    BYBIT_API_SECRET: str = os.getenv("BYBIT_API_SECRET", "")
    BYBIT_TESTNET: bool = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

    # OKX
    OKX_API_KEY: str = os.getenv("OKX_API_KEY", "")
    OKX_API_SECRET: str = os.getenv("OKX_API_SECRET", "")
    OKX_PASSPHRASE: str = os.getenv("OKX_PASSPHRASE", "")
    OKX_IS_SIMULATED: bool = os.getenv("OKX_IS_SIMULATED", "false").lower() == "true"

    # AI
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Storage
    EXCEL_FILE_PATH: str = os.getenv("EXCEL_FILE_PATH", "bybit-okx_maliyet.xlsx")
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    AUTO_SYNC_INTERVAL_MINUTES: int = int(os.getenv("AUTO_SYNC_INTERVAL_MINUTES", "15"))

    @classmethod
    def get_excel_absolute_path(cls) -> Path:
        p = Path(cls.EXCEL_FILE_PATH)
        if not p.is_absolute():
            p = BASE_DIR / p
        if not p.exists():
            template_p = BASE_DIR / "bybit-okx_maliyet_template.xlsx"
            if template_p.exists():
                import shutil
                shutil.copyfile(template_p, p)
        return p

    @classmethod
    def reload(cls):
        load_dotenv(dotenv_path=ENV_PATH, override=True)
        cls.BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
        cls.BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
        cls.BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

        cls.OKX_API_KEY = os.getenv("OKX_API_KEY", "")
        cls.OKX_API_SECRET = os.getenv("OKX_API_SECRET", "")
        cls.OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE", "")
        cls.OKX_IS_SIMULATED = os.getenv("OKX_IS_SIMULATED", "false").lower() == "true"

        cls.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        cls.EXCEL_FILE_PATH = os.getenv("EXCEL_FILE_PATH", "bybit-okx_maliyet.xlsx")
        cls.HOST = os.getenv("HOST", "127.0.0.1")
        cls.PORT = int(os.getenv("PORT", "8000"))
        cls.AUTO_SYNC_INTERVAL_MINUTES = int(os.getenv("AUTO_SYNC_INTERVAL_MINUTES", "15"))

    @classmethod
    def save_to_env(cls, new_settings: dict):
        """Update .env file with given dictionary."""
        lines = []
        if ENV_PATH.exists():
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()

        existing_keys = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                existing_keys.add(k)
                if k in new_settings:
                    new_lines.append(f"{k}={new_settings[k]}\n")
                    continue
            new_lines.append(line)

        # Append any new keys not yet in .env
        for k, v in new_settings.items():
            if k not in existing_keys:
                new_lines.append(f"{k}={v}\n")

        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        cls.reload()

settings = Settings()

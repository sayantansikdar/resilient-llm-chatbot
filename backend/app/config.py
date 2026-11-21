import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "gemini/gemini-3.5-flash-lite"
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Keep answers clear and concise."


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        return default


def sqlite_path_from_url(url: str) -> str:
    """sqlite:////data/app.db -> /data/app.db, sqlite:///./app.db -> ./app.db"""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"DATABASE_URL must start with {prefix!r}, got {url!r}")
    path = url[len(prefix):]
    if not path:
        raise ValueError("DATABASE_URL has no file path")
    return path


@dataclass(frozen=True)
class Settings:
    api_keys: list[str] = field(default_factory=list)
    # one model for every key, or one model per key (same order as api_keys)
    models: list[str] = field(default_factory=lambda: [DEFAULT_MODEL])
    database_url: str = "sqlite:///./data/app.db"
    allowed_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    enable_failure_simulation: bool = False
    default_system_prompt: str = DEFAULT_SYSTEM_PROMPT
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600
    llm_timeout_seconds: int = 30
    history_max_messages: int = 40

    @property
    def database_path(self) -> str:
        return sqlite_path_from_url(self.database_url)

    def model_for_key(self, index: int) -> str:
        if len(self.models) == 1:
            return self.models[0]
        return self.models[index]

    @classmethod
    def from_env(cls) -> "Settings":
        keys = _split(os.getenv("LLM_API_KEYS"))
        models = _split(os.getenv("LLM_MODELS")) or [os.getenv("LLM_MODEL", DEFAULT_MODEL).strip()]
        if len(models) not in (1, len(keys)) and keys:
            raise ValueError(
                f"LLM_MODELS has {len(models)} entries but LLM_API_KEYS has {len(keys)}; "
                "give one model for all keys or one per key"
            )
        return cls(
            api_keys=keys,
            models=models,
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            allowed_origins=_split(os.getenv("ALLOWED_ORIGINS")) or ["http://localhost:3000"],
            enable_failure_simulation=_bool(os.getenv("ENABLE_FAILURE_SIMULATION")),
            default_system_prompt=os.getenv("DEFAULT_SYSTEM_PROMPT") or DEFAULT_SYSTEM_PROMPT,
            cache_enabled=_bool(os.getenv("CACHE_ENABLED"), default=True),
            cache_ttl_seconds=_int(os.getenv("CACHE_TTL_SECONDS"), 3600),
            llm_timeout_seconds=_int(os.getenv("LLM_TIMEOUT_SECONDS"), 30),
            history_max_messages=_int(os.getenv("HISTORY_MAX_MESSAGES"), 40),
        )

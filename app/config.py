"""App settings, loaded from environment variables (and a local .env file).

LESSON: same pattern as SiteSpec/PromptShield: pydantic-settings reads and type-checks env vars.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MarkLayer API"
    version: str = "0.1.0"
    # Render sets RENDER_GIT_COMMIT to the deployed commit; /health shows it so you can tell
    # which code is live. Empty when running locally.
    render_git_commit: str = ""
    # RapidAPI adds this shared secret to every request it forwards (X-RapidAPI-Proxy-Secret).
    # Empty = check disabled (local dev).
    rapidapi_proxy_secret: str = ""

    # C2PA signing identity: PEM certificate chain (leaf first) and PEM private key.
    # Empty = a throwaway identity is generated at startup (fine for dev, NOT for production:
    # it changes on every restart). Make a persistent one with scripts/make_signing_cert.py.
    signing_cert_pem: str = ""
    signing_key_pem: str = ""
    # RFC 3161 timestamp authority. Keeps signatures valid after the certificate expires.
    # Empty = no timestamp (one less network call per mark).
    tsa_url: str = ""

    model_dir: Path = ROOT / "models"
    data_dir: Path = ROOT / "data"

    max_upload_mb: int = 25
    # Pixel cap protects memory. Measured peak RSS while marking (models alone ~215 MB):
    # 4.2 MP -> 375 MB, 8.4 MP -> 480 MB, 16.8 MP -> 625 MB. 17 MP covers 4096 x 4096 upscales;
    # on a 512 MB instance set MAX_MEGAPIXELS=4.5 (still covers 1024-2048 px generator output).
    max_megapixels: float = 17.0
    # Watermarking is CPU and memory heavy: cap how many run at once per instance.
    max_concurrent_jobs: int = 1
    # For /v1/inspect?url=...
    fetch_timeout_s: float = 15.0

    # Free checker page (GET /, POST /public/check): per-IP and whole-server limits, so scripts
    # can't use it as an unpaid API and the CPU stays free for paying customers.
    public_checks_per_hour: int = 10
    public_daily_cap: int = 1000
    public_max_upload_mb: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()

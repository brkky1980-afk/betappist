from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    goaloo_base_url: str = "https://football.goaloo.com"
    goaloo_league_path: str = "/league/2024-2025/36"
    goaloo_round: int = 38
    scraper_headless: bool = True
    scraper_timeout_ms: int = 30_000
    scraper_delay_ms: int = 750
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

settings = Settings()

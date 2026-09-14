import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_page_size: int = 100
    api_max_pages: int = 200

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        database_url = os.getenv("DATABASE_URL", "")
        if not database_url:
            raise ValueError("DATABASE_URL is required")

        return cls(
            database_url=database_url,
            api_page_size=max(1, min(500, int(os.getenv("API_PAGE_SIZE", "100")))),
            api_max_pages=max(1, int(os.getenv("API_MAX_PAGES", "200"))),
        )

import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from src.server import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main())

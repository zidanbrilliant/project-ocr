"""Drop & create all tables from ORM models. Usage: python scripts/db_reset.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.infrastructure.database.session import engine
from app.infrastructure.database.models import Base
from app.shared.logging.logger import get_logger

logger = get_logger(__name__)


async def reset():
    async with engine.begin() as conn:
        logger.info("dropping_all_tables")
        await conn.run_sync(Base.metadata.drop_all)
        logger.info("creating_all_tables")
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_reset_complete")
    print("DONE — 13 tables created:")
    for table in Base.metadata.sorted_tables:
        print(f"  {table.name}")


if __name__ == "__main__":
    print("WARNING: This will DELETE all data in vision_ai database!")
    confirm = input('Type "reset" to continue: ')
    if confirm.strip().lower() == "reset":
        import asyncio
        asyncio.run(reset())
    else:
        print("Cancelled.")

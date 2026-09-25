import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect
from backend.database.session import engine
from backend.models.orm import Base
from alembic.config import Config
from alembic import command

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_schema_parity() -> bool:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    
    existing_tables.discard("alembic_version")
    existing_tables.discard("sqlite_sequence")
    
    expected_tables_set = set(Base.metadata.tables.keys())
    
    if existing_tables != expected_tables_set:
        logger.error(f"[PARITY] Table mismatch. Missing: {expected_tables_set - existing_tables}, Unexpected: {existing_tables - expected_tables_set}")
        return False
        
    for table_name in expected_tables_set:
        expected_cols = {col.name for col in Base.metadata.tables[table_name].columns}
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        if existing_cols != expected_cols:
            logger.error(f"[PARITY] Column mismatch in table '{table_name}'. Missing: {expected_cols - existing_cols}, Unexpected: {existing_cols - expected_cols}")
            return False
            
    return True

def main():
    logger.info("Verifying existing database schema parity...")
    if not verify_schema_parity():
        logger.error("REFUSED: Existing database schema does not match baseline expectations. Manual migration required.")
        sys.exit(1)
        
    logger.info("Schema parity equivalent. Stamping as head (baseline)...")
    alembic_cfg = Config(os.path.join(os.path.dirname(__file__), '..', 'alembic.ini'))
    command.stamp(alembic_cfg, "head")
    logger.info("Successfully stamped database to Alembic head.")

if __name__ == '__main__':
    main()

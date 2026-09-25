import os
from pathlib import Path
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, inspect

def test_alembic_upgrade_and_downgrade(tmp_path):
    """
    Verifies that 'alembic upgrade head' and 'alembic downgrade base' 
    can run successfully on a fresh SQLite database, mimicking the CI/CD guard.
    """
    db_path = str(tmp_path / "test_alembic.db")
    db_url = f"sqlite:///{db_path}"
    
    # Configure alembic to use this temporary DB
    orig_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    
    try:
        alembic_cfg_path = Path(__file__).resolve().parent.parent.parent / "alembic.ini"
        alembic_cfg = Config(str(alembic_cfg_path))
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        
        # Run Upgrade to Head
        command.upgrade(alembic_cfg, "head")
        
        # Verify tables were created
        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        assert "alembic_version" in tables
        assert "cameras" in tables
        assert "events" in tables
        
        # Verify we can downgrade back to base
        command.downgrade(alembic_cfg, "base")
        
        # We should only see alembic_version and maybe sqlite_sequence
        # but the main tables should be dropped
        inspector = inspect(engine)
        tables_after = inspector.get_table_names()
        assert "cameras" not in tables_after
        assert "events" not in tables_after
    finally:
        if orig_url is not None:
            os.environ["DATABASE_URL"] = orig_url
        else:
            del os.environ["DATABASE_URL"]


class TestWatchlistTablesRealSchema:
    """WatchlistPerson/WatchlistFaceImage ORM round-trip tests."""

    def _fresh_engine(self, tmp_path):
        from sqlalchemy import create_engine
        from backend.models.orm import Base
        engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
        Base.metadata.create_all(bind=engine)
        return engine

    def test_watchlist_tables_are_created(self, tmp_path):
        from sqlalchemy import inspect as sa_inspect
        engine = self._fresh_engine(tmp_path)
        tables = sa_inspect(engine).get_table_names()
        assert "watchlist_persons" in tables
        assert "watchlist_face_images" in tables

    def test_real_person_and_image_round_trip(self, tmp_path):
        from sqlalchemy.orm import sessionmaker
        from backend.models.orm import WatchlistFaceImage, WatchlistPerson

        engine = self._fresh_engine(tmp_path)
        Session = sessionmaker(bind=engine)
        db = Session()

        person = WatchlistPerson(name="Alice", notes="test enrollment")
        db.add(person)
        db.flush()
        db.add(WatchlistFaceImage(person_id=person.id, image_base64="ZmFrZQ=="))
        db.commit()

        fetched = db.query(WatchlistPerson).filter(WatchlistPerson.name == "Alice").first()
        assert fetched is not None
        assert len(fetched.face_images) == 1
        assert fetched.face_images[0].image_base64 == "ZmFrZQ=="
        assert fetched.is_active is True

    def test_deleting_a_person_cascades_to_their_face_images(self, tmp_path):
        from sqlalchemy.orm import sessionmaker
        from backend.models.orm import WatchlistFaceImage, WatchlistPerson

        engine = self._fresh_engine(tmp_path)
        Session = sessionmaker(bind=engine)
        db = Session()

        person = WatchlistPerson(name="Bob")
        db.add(person)
        db.flush()
        db.add(WatchlistFaceImage(person_id=person.id, image_base64="ZmFrZQ=="))
        db.commit()

        db.delete(person)
        db.commit()

        assert db.query(WatchlistFaceImage).count() == 0

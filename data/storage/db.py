from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from data.storage.models import Base
from config.settings import DATABASE_URL
from loguru import logger

engine = create_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    """Create all tables if they don't exist"""
    try:
        Base.metadata.create_all(engine)
        logger.success("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
"""Initialise la connexion PostgreSQL et la session SQLAlchemy."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

os.environ["OneDrive"] = ""
os.environ["OneDriveCommercial"] = ""

DATABASE_NAME = os.getenv("DATABASE_NAME", "observia")
DATABASE_USER = os.getenv("DATABASE_USER", "postgres")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "postgres")
DATABASE_HOST = os.getenv("DATABASE_HOST", "localhost")
DATABASE_PORT = int(os.getenv("DATABASE_PORT", "5432"))

url_object = URL.create(
    drivername="postgresql+psycopg",
    username=DATABASE_USER,
    password=DATABASE_PASSWORD,
    host=DATABASE_HOST,
    port=DATABASE_PORT,
    database=DATABASE_NAME,
)

engine = create_engine(url_object)
SESSION_LOCAL = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base déclarative commune à tous les modèles SQLAlchemy du projet."""


def get_db():
    """Fournit une session SQLAlchemy et la ferme après usage."""

    db = SESSION_LOCAL()
    try:
        yield db
    finally:
        db.close()

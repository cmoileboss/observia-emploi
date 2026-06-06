from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker
import os

load_dotenv(override=True)

os.environ["OneDrive"] = ""
os.environ["OneDriveCommercial"] = ""

DATABASE_NAME = os.getenv("DATABASE_NAME", "observia")
DATABASE_USER = os.getenv("DATABASE_USER", "postgres")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "postgres")

url_object = URL.create(
    drivername="postgresql+psycopg",
    username=DATABASE_USER,
    password=DATABASE_PASSWORD,
    host="localhost",
    port=5432,
    database=DATABASE_NAME,
)

engine = create_engine(url_object)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
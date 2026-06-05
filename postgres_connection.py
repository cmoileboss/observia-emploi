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

# libpq (psycopg2) lit les variables d'env via getenv() du C runtime (msvcrt).
# os.environ.pop() ne met à jour que le bloc Win32, pas _environ du CRT.
# os.environ["key"] = "" appelle _wputenv_s() qui met à jour les deux.
# Les chemins OneDrive contiennent 'é' (cp1252 0xe9) → UnicodeDecodeError.
os.environ["OneDrive"] = ""
os.environ["OneDriveCommercial"] = ""

DATABASE_NAME = os.getenv("DATABASE_NAME", "observia")
DATABASE_USER = os.getenv("DATABASE_USER", "postgres")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "postgres")

engine = URL.create(
    drivername="postgresql+psycopg",
    username=DATABASE_USER,
    password=DATABASE_PASSWORD,
    host="localhost",
    port=5432,
    database=DATABASE_NAME,
)

engine = create_engine(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
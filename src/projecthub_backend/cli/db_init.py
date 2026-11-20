from projecthub_backend.core.database import Base,engine
import projecthub_backend.models

def init_db() -> None:
    print("Connecting to Postgresql")
    Base.metadata.create_all(bind=engine)
    print("All projecthub tables created successfully")

if __name__ == "__main__":
    init_db()
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database.session import init_db, SessionLocal
from backend.models.orm import User, Camera, Event, EvidencePackage, Zone
from backend.security.auth import hash_password

def main():
    print("Initializing Database...")
    init_db()
    
    db = SessionLocal()
    
    # Create default admin user if not exists
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        print("Creating admin user...")
        admin = User(
            username="admin",
            hashed_password=hash_password("admin"),
            role="ADMIN"
        )
        db.add(admin)
    
    # Create the demo camera
    cam = db.query(Camera).filter(Camera.id == "edge-001").first()
    if not cam:
        print("Creating edge-001 camera...")
        cam = Camera(
            id="edge-001",
            name="Alpha Gate",
            location="Sector 7G",
            owning_command_id="COMMAND_A",
            is_active=True
        )
        db.add(cam)
        
    db.commit()
    print("Database initialized successfully.")
    
if __name__ == "__main__":
    main()

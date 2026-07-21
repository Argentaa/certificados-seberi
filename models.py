from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Registration(db.Model):
    __tablename__ = "registrations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    email = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="pending")  # pending | completed | failed
    certificate_file = db.Column(db.String(500), nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    sent_count = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "status": self.status,
            "certificate_file": self.certificate_file,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "sent_count": self.sent_count,
        }

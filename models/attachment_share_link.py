import uuid
from sqlalchemy import Column, Uuid, Integer, String, DateTime
from sqlalchemy.sql import func
from database import Base


class AttachmentShareLink(Base):
    __tablename__ = "attachment_share_links"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    attachment_id = Column(Integer, nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    pin_hash = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    uses = Column(Integer, nullable=False, default=0)
    max_uses = Column(Integer, nullable=False, default=50)
    created_by_user_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

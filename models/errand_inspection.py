import uuid
from sqlalchemy import Column, Uuid, String, Boolean, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID
from database import Base

class ErrandInspectionItem(Base):
    __tablename__ = "errand_inspection_items"
    
    id = Column(Uuid, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    errand_id = Column(Uuid, nullable=False, index=True)
    label = Column(String, nullable=False)
    requires_photo = Column(Boolean, default=False)
    completed = Column(Boolean, default=False)
    photo_url = Column(String, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    completed_by = Column(String, nullable=True)
    sort_order = Column(Integer, default=0)

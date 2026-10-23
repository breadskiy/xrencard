from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import relationship

try:
    from database import Base
except ImportError:
    from backend.database import Base


class Space(Base):
    __tablename__ = "spaces"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    is_published = Column(Boolean, default=True, nullable=False)

    # Relationships
    floors = relationship(
        "Floor",
        back_populates="space",
        cascade="all, delete-orphan",
        order_by="Floor.level",
    )


class Floor(Base):
    __tablename__ = "floors"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False)
    level = Column(Integer, nullable=False)
    name = Column(String(255), nullable=False)
    plan_image_url = Column(String(500), nullable=True)
    width = Column(Integer, default=1200, nullable=False)
    height = Column(Integer, default=800, nullable=False)
    nav_graph = Column("nav_graph_json", JSON, nullable=True)

    # Property for backward compatibility
    @property
    def nav_graph_json(self):
        return self.nav_graph

    @nav_graph_json.setter
    def nav_graph_json(self, value):
        self.nav_graph = value

    # Relationships
    space = relationship("Space", back_populates="floors")
    pois = relationship("POI", back_populates="floor", cascade="all, delete-orphan")
    panoramas = relationship("Panorama", back_populates="floor", cascade="all, delete-orphan")


class POI(Base):
    __tablename__ = "pois"

    id = Column(Integer, primary_key=True, index=True)
    floor_id = Column(Integer, ForeignKey("floors.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    x = Column(Float, nullable=False)  # 0..100%
    y = Column(Float, nullable=False)  # 0..100%
    panorama_id = Column(Integer, ForeignKey("panoramas.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    floor = relationship("Floor", back_populates="pois")
    panorama = relationship("Panorama", back_populates="pois")


class Panorama(Base):
    __tablename__ = "panoramas"

    id = Column(Integer, primary_key=True, index=True)
    floor_id = Column(Integer, ForeignKey("floors.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    image_url = Column(String(500), nullable=False)
    thumbnail_url = Column(String(500), nullable=True)
    x = Column(Float, nullable=False, default=0.0)  # 0..100%
    y = Column(Float, nullable=False, default=0.0)  # 0..100%
    connections = Column("connections_json", JSON, nullable=True)

    # Property for backward compatibility
    @property
    def connections_json(self):
        return self.connections

    @connections_json.setter
    def connections_json(self, value):
        self.connections = value

    # Relationships
    floor = relationship("Floor", back_populates="panoramas")
    pois = relationship("POI", back_populates="panorama")

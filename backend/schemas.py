from typing import Any, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from pydantic.alias_generators import to_camel


# ==========================================
# Base Model with camelCase alias support
# ==========================================

class BaseCamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        coerce_numbers_to_str=True,
    )


# ==========================================
# NavGraph Schemas
# ==========================================

class NavNode(BaseCamelModel):
    id: str = Field(..., description="Идентификатор узла (например, node_1)")
    x: float = Field(..., description="Координата X (0..100% относительно плана)")
    y: float = Field(..., description="Координата Y (0..100% относительно плана)")
    floor_id: str = Field(..., alias="floorId", description="ID этажа")

    @field_serializer("floor_id", check_fields=False)
    def serialize_floor_id(self, v: Any) -> str:
        return str(v) if v is not None else ""


class NavEdge(BaseCamelModel):
    source: str = Field(..., description="ID начального узла")
    target: str = Field(..., description="ID конечного узла")
    weight: float = Field(..., description="Длина прохода в метрах/пикселях")


class NavGraph(BaseCamelModel):
    nodes: List[NavNode] = Field(default_factory=list, description="Список узлов графа")
    edges: List[NavEdge] = Field(default_factory=list, description="Список рёбер графа")


# ==========================================
# POI Schemas
# ==========================================

POICategory = Literal['hall', 'booth', 'service', 'wifi', 'entrance', 'wc', 'food']


class POIBase(BaseCamelModel):
    title: str = Field(..., description="Название точки интереса")
    category: Union[POICategory, str] = Field(..., description="Категория ('hall' | 'booth' | 'service' | 'wifi' | 'entrance' | 'wc' | 'food')")
    description: str = Field("", description="Описание точки интереса")
    x: float = Field(..., description="Координата X (0..100% относительно плана)")
    y: float = Field(..., description="Координата Y (0..100% относительно плана)")
    panorama_id: Optional[str] = Field(None, alias="panoramaId", description="Привязанная панорама (panoramaId)")


class POICreate(POIBase):
    floor_id: Union[int, str] = Field(..., alias="floorId", description="ID этажа")


class POIUpdate(BaseCamelModel):
    title: Optional[str] = None
    category: Optional[Union[POICategory, str]] = None
    description: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    panorama_id: Optional[str] = Field(None, alias="panoramaId")
    floor_id: Optional[Union[int, str]] = Field(None, alias="floorId")


class POIResponse(POIBase):
    id: str
    floor_id: str = Field(..., alias="floorId")

    @field_serializer("id", "floor_id", "panorama_id", check_fields=False)
    def serialize_str_ids(self, v: Any) -> Optional[str]:
        return str(v) if v is not None else None


# ==========================================
# Panorama Schemas
# ==========================================

class PanoramaConnection(BaseCamelModel):
    target_panorama_id: str = Field(..., alias="targetPanoramaId", description="ID целевой панорамы")
    yaw: float = Field(0.0, description="Угол горизонтального поворота (азимут)")
    pitch: float = Field(0.0, description="Угол вертикального наклона")

    @field_serializer("target_panorama_id", check_fields=False)
    def serialize_target_id(self, v: Any) -> str:
        return str(v) if v is not None else ""


class PanoramaBase(BaseCamelModel):
    title: str = Field(..., description="Название или метка панорамы")
    image_url: str = Field(..., alias="imageUrl", description="Эквидистантная проекция 360")
    thumbnail_url: str = Field("", alias="thumbnailUrl", description="Миниатюра 360-фото")
    x: float = Field(0.0, description="Положение на 2D-плане (0..100%)")
    y: float = Field(0.0, description="Положение на 2D-плане (0..100%)")
    connections: List[PanoramaConnection] = Field(
        default_factory=list,
        description="Связи переходов с другими панорамами",
    )


class PanoramaCreate(PanoramaBase):
    floor_id: Union[int, str] = Field(..., alias="floorId", description="ID этажа")


class PanoramaUpdate(BaseCamelModel):
    title: Optional[str] = None
    image_url: Optional[str] = Field(None, alias="imageUrl")
    thumbnail_url: Optional[str] = Field(None, alias="thumbnailUrl")
    x: Optional[float] = None
    y: Optional[float] = None
    connections: Optional[List[PanoramaConnection]] = None
    floor_id: Optional[Union[int, str]] = Field(None, alias="floorId")


class PanoramaResponse(PanoramaBase):
    id: str
    floor_id: str = Field(..., alias="floorId")

    @field_serializer("id", "floor_id", check_fields=False)
    def serialize_str_ids(self, v: Any) -> str:
        return str(v) if v is not None else ""


class PanoramaUploadResponse(BaseCamelModel):
    image_url: str = Field(..., alias="imageUrl")
    thumbnail_url: str = Field(..., alias="thumbnailUrl")
    panorama: Optional[PanoramaResponse] = None


# ==========================================
# Floor Schemas
# ==========================================

class FloorBase(BaseCamelModel):
    level: int = Field(..., description="Номер/уровень этажа")
    name: str = Field(..., description="Название этажа")
    plan_image_url: str = Field("", alias="planImageUrl", description="URL плана этажа")
    width: int = Field(1200, description="Ширина плана этажа в пикселях")
    height: int = Field(800, description="Высота плана этажа в пикселях")
    nav_graph: Optional[Union[NavGraph, Any]] = Field(
        default_factory=NavGraph,
        alias="navGraph",
        description="Навигационный граф",
    )


class FloorCreate(FloorBase):
    space_id: Union[int, str] = Field(..., alias="spaceId", description="ID пространства")


class FloorUpdate(BaseCamelModel):
    level: Optional[int] = None
    name: Optional[str] = None
    plan_image_url: Optional[str] = Field(None, alias="planImageUrl")
    width: Optional[int] = None
    height: Optional[int] = None
    nav_graph: Optional[Union[NavGraph, Any]] = Field(None, alias="navGraph")


class FloorGraphUpdate(BaseCamelModel):
    nav_graph: Union[NavGraph, Any] = Field(..., alias="navGraph", description="Новая структура навигационного графа")


class FloorResponse(FloorBase):
    id: str
    space_id: str = Field(..., alias="spaceId")

    @field_serializer("id", "space_id", check_fields=False)
    def serialize_str_ids(self, v: Any) -> str:
        return str(v) if v is not None else ""


class FloorPublicResponse(FloorBase):
    id: str
    space_id: str = Field(..., alias="spaceId")
    pois: List[POIResponse] = Field(default_factory=list, description="Точки интереса")
    panoramas: List[PanoramaResponse] = Field(default_factory=list, description="360-панорамы")

    @field_serializer("id", "space_id", check_fields=False)
    def serialize_str_ids(self, v: Any) -> str:
        return str(v) if v is not None else ""


# ==========================================
# Space Schemas
# ==========================================

class SpaceBase(BaseCamelModel):
    title: str = Field(..., description="Название пространства")
    slug: str = Field(..., description="URL slug")
    description: Optional[str] = Field(None, description="Описание пространства")
    is_published: bool = Field(True, alias="isPublished", description="Опубликовано")


class SpaceCreate(SpaceBase):
    pass


class SpaceUpdate(BaseCamelModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    is_published: Optional[bool] = Field(None, alias="isPublished")


class SpaceResponse(SpaceBase):
    id: str

    @field_serializer("id", check_fields=False)
    def serialize_str_ids(self, v: Any) -> str:
        return str(v) if v is not None else ""


class SpacePublicResponse(SpaceBase):
    id: str
    floors: List[FloorPublicResponse] = Field(default_factory=list)

    @field_serializer("id", check_fields=False)
    def serialize_str_ids(self, v: Any) -> str:
        return str(v) if v is not None else ""

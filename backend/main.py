import json
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session, selectinload

from pathlib import Path

try:
    from database import Base, engine, get_db
    import models
    import schemas
except ImportError:
    from backend.database import Base, engine, get_db
    from backend import models
    from backend import schemas

# ==========================================
# Paths & Directories
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"
PLANS_DIR = UPLOADS_DIR / "plans"
PANORAMAS_DIR = UPLOADS_DIR / "panoramas"
THUMBS_DIR = PANORAMAS_DIR / "thumbs"

for directory in [PLANS_DIR, PANORAMAS_DIR, THUMBS_DIR]:
    os.makedirs(directory, exist_ok=True)


# ==========================================
# Helper: Pillow Thumbnail Generation
# ==========================================
def create_image_thumbnail(source_path: str, dest_path: str, size: tuple = (400, 200)) -> None:
    """Генерирует миниатюру изображения с помощью Pillow с безопасной конвертацией цветовых профилей."""
    with Image.open(source_path) as img:
        img_copy = img.copy()
        if img_copy.mode in ("RGBA", "LA", "P"):
            rgb_img = Image.new("RGB", img_copy.size, (255, 255, 255))
            if img_copy.mode == "P":
                img_copy = img_copy.convert("RGBA")
            mask = img_copy.split()[-1] if img_copy.mode == "RGBA" else None
            rgb_img.paste(img_copy, mask=mask)
            img_copy = rgb_img
        elif img_copy.mode != "RGB":
            img_copy = img_copy.convert("RGB")

        img_copy.thumbnail(size, Image.Resampling.LANCZOS)
        img_copy.save(dest_path, "JPEG", quality=85)


# ==========================================
# Helper: Generate Mock Images & SVG Plan
# ==========================================
def generate_mock_files_if_missing():
    """Создаёт SVG-план этажа и 360-заглушки для панорам, чтобы ссылки не возвращали 404."""
    # 1. Mock Floor Plan SVG (1200x800)
    svg_plan_path = os.path.join(PLANS_DIR, "floor_1_plan.svg")
    if not os.path.exists(svg_plan_path):
        svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" width="100%" height="100%">
  <defs>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#e2e8f0" stroke-width="1"/>
    </pattern>
  </defs>
  <!-- Background & Grid -->
  <rect width="100%" height="100%" fill="#f8fafc"/>
  <rect width="100%" height="100%" fill="url(#grid)" />

  <!-- Outer Walls -->
  <rect x="60" y="60" width="1080" height="680" rx="20" fill="#ffffff" stroke="#334155" stroke-width="8"/>

  <!-- Zone: Reception (Entrance) ~18%, 50% -->
  <rect x="90" y="260" width="240" height="280" rx="12" fill="#e0f2fe" stroke="#0284c7" stroke-width="3"/>
  <text x="210" y="405" font-family="sans-serif" font-size="18" font-weight="bold" fill="#0369a1" text-anchor="middle">Вход и Ресепшн</text>

  <!-- Zone: Central Atrium ~44%, 50% -->
  <circle cx="528" cy="400" r="110" fill="#fef3c7" stroke="#d97706" stroke-width="3" stroke-dasharray="8,6"/>
  <text x="528" y="405" font-family="sans-serif" font-size="18" font-weight="bold" fill="#b45309" text-anchor="middle">Центральный атриум</text>

  <!-- Zone: Cafe & Food ~44%, 25% -->
  <rect x="408" y="100" width="240" height="160" rx="12" fill="#f0fdf4" stroke="#16a34a" stroke-width="3"/>
  <text x="528" y="185" font-family="sans-serif" font-size="18" font-weight="bold" fill="#15803d" text-anchor="middle">Кофейня &amp; Лаунж</text>

  <!-- Zone: Elevators & Service ~44%, 77% -->
  <rect x="408" y="540" width="240" height="160" rx="12" fill="#f3e8ff" stroke="#9333ea" stroke-width="3"/>
  <text x="528" y="625" font-family="sans-serif" font-size="18" font-weight="bold" fill="#7e22ce" text-anchor="middle">Лифтовой холл</text>

  <!-- Zone: Congress Hall ~75%, 51% -->
  <rect x="730" y="140" width="370" height="520" rx="16" fill="#fff1f2" stroke="#e11d48" stroke-width="4"/>
  <text x="915" y="405" font-family="sans-serif" font-size="22" font-weight="bold" fill="#be123c" text-anchor="middle">Конгресс-холл «Премьер»</text>

  <!-- Pathways -->
  <line x1="210" y1="400" x2="418" y2="400" stroke="#94a3b8" stroke-width="4" stroke-dasharray="10,6"/>
  <line x1="528" y1="260" x2="528" y2="290" stroke="#94a3b8" stroke-width="4" stroke-dasharray="10,6"/>
  <line x1="528" y1="510" x2="528" y2="540" stroke="#94a3b8" stroke-width="4" stroke-dasharray="10,6"/>
  <line x1="638" y1="400" x2="730" y2="400" stroke="#94a3b8" stroke-width="4" stroke-dasharray="10,6"/>
</svg>"""
        with open(svg_plan_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

    # 2. Mock 360 Panoramas and Thumbnails
    panos_meta = [
        ("pano_reception.jpg", "thumb_pano_reception.jpg", (30, 144, 255), "360° Reception & Lobby"),
        ("pano_atrium.jpg", "thumb_pano_atrium.jpg", (218, 165, 32), "360° Central Atrium"),
        ("pano_hall.jpg", "thumb_pano_hall.jpg", (220, 20, 60), "360° Grand Congress Hall"),
    ]

    for pano_file, thumb_file, color, title in panos_meta:
        pano_path = os.path.join(PANORAMAS_DIR, pano_file)
        thumb_path = os.path.join(THUMBS_DIR, thumb_file)

        if not os.path.exists(pano_path):
            img = Image.new("RGB", (1024, 512), color=color)
            draw = ImageDraw.Draw(img)
            draw.rectangle([20, 20, 1004, 492], outline=(255, 255, 255), width=4)
            draw.text((512, 256), title, fill=(255, 255, 255), anchor="mm")
            img.save(pano_path, "JPEG", quality=85)

        if not os.path.exists(thumb_path):
            create_image_thumbnail(pano_path, thumb_path, size=(400, 200))


# ==========================================
# Database Seeder (Mock Data matching frontend types)
# ==========================================
def seed_mock_data():
    """Инициализирует базу данных SQLite демонстрационными данными отеля и конференц-холла."""
    generate_mock_files_if_missing()

    db: Session = next(get_db())
    try:
        if db.query(models.Space).count() > 0:
            return

        # 1. Демонстрационное пространство
        space = models.Space(
            title="Конференц-отель & Экспо «Гранд Атриум»",
            slug="grand-atrium",
            description="Интерактивный навигационный план отеля, конгресс-холла и зон отдыха с виртуальными турами 360°.",
            is_published=True,
        )
        db.add(space)
        db.flush()

        # 2. Этаж с навигационным графом (узлы и рёбра с source/target/weight, координаты 0..100%)
        nav_graph = {
            "nodes": [
                {"id": "node_1", "x": 18.0, "y": 50.0, "floorId": "1"},
                {"id": "node_2", "x": 44.0, "y": 50.0, "floorId": "1"},
                {"id": "node_3", "x": 44.0, "y": 25.0, "floorId": "1"},
                {"id": "node_4", "x": 44.0, "y": 77.0, "floorId": "1"},
                {"id": "node_5", "x": 75.0, "y": 51.0, "floorId": "1"},
            ],
            "edges": [
                {"source": "node_1", "target": "node_2", "weight": 26.0},
                {"source": "node_2", "target": "node_3", "weight": 25.0},
                {"source": "node_2", "target": "node_4", "weight": 27.0},
                {"source": "node_2", "target": "node_5", "weight": 31.0},
            ],
        }

        floor = models.Floor(
            space_id=space.id,
            level=1,
            name="1 этаж — Главный вестибюль и конгресс-холл",
            plan_image_url="/static/uploads/plans/floor_1_plan.svg",
            width=1200,
            height=800,
            nav_graph=nav_graph,
        )
        db.add(floor)
        db.flush()

        # 3. Создание 3 панорам с 0..100% координатами и связями {targetPanoramaId, yaw, pitch}
        pano_reception = models.Panorama(
            floor_id=floor.id,
            title="Ресепшн и входная зона",
            image_url="/static/uploads/panoramas/pano_reception.jpg",
            thumbnail_url="/static/uploads/panoramas/thumbs/thumb_pano_reception.jpg",
            x=18.0,
            y=50.0,
            connections=[
                {"targetPanoramaId": "2", "yaw": 90.0, "pitch": 0.0}
            ],
        )
        pano_atrium = models.Panorama(
            floor_id=floor.id,
            title="Центральный атриум",
            image_url="/static/uploads/panoramas/pano_atrium.jpg",
            thumbnail_url="/static/uploads/panoramas/thumbs/thumb_pano_atrium.jpg",
            x=44.0,
            y=50.0,
            connections=[
                {"targetPanoramaId": "1", "yaw": 270.0, "pitch": 0.0},
                {"targetPanoramaId": "3", "yaw": 90.0, "pitch": 0.0}
            ],
        )
        pano_hall = models.Panorama(
            floor_id=floor.id,
            title="Конгресс-холл «Премьер»",
            image_url="/static/uploads/panoramas/pano_hall.jpg",
            thumbnail_url="/static/uploads/panoramas/thumbs/thumb_pano_hall.jpg",
            x=75.0,
            y=51.0,
            connections=[
                {"targetPanoramaId": "2", "yaw": 270.0, "pitch": 0.0}
            ],
        )
        db.add_all([pano_reception, pano_atrium, pano_hall])
        db.flush()

        # 4. Точки интереса (POI) с категориями 'hall' | 'booth' | 'service' | 'wifi' | 'entrance' | 'wc' | 'food'
        pois = [
            models.POI(
                floor_id=floor.id,
                title="Главный вход и регистрация",
                category="entrance",
                description="Стойка регистрации участников мероприятий и гостей отеля 24/7.",
                x=18.0,
                y=50.0,
                panorama_id=pano_reception.id,
            ),
            models.POI(
                floor_id=floor.id,
                title="Кофейня & Бизнес-лаунж",
                category="food",
                description="Свежий кофе, напитки, снэки и удобные рабочие места с розетками.",
                x=44.0,
                y=25.0,
                panorama_id=pano_atrium.id,
            ),
            models.POI(
                floor_id=floor.id,
                title="Пассажирские скоростные лифты",
                category="service",
                description="Лифты на жилые этажи (2-15), в спа-комплекс и видовой ресторан.",
                x=44.0,
                y=77.0,
                panorama_id=pano_atrium.id,
            ),
            models.POI(
                floor_id=floor.id,
                title="Конгресс-холл «Премьер» (Зал A+B)",
                category="hall",
                description="Главный конференц-зал вместимостью до 600 человек с синхронным переводом.",
                x=75.0,
                y=51.0,
                panorama_id=pano_hall.id,
            ),
        ]
        db.add_all(pois)
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


# ==========================================
# Lifespan Context Manager
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_mock_data()
    yield


# ==========================================
# FastAPI Application
# ==========================================
app = FastAPI(
    title="Indoor Map & Panorama Backend API",
    description="Backend-сервис интерактивных карт помещений с 360° панорамами и навигацией",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ==========================================
# Spaces Endpoints
# ==========================================

@app.get(
    "/api/spaces/{slug}/public",
    response_model=schemas.SpacePublicResponse,
    summary="Публичное получение всей структуры пространства",
    tags=["Public Viewer"],
)
def get_public_space(slug: str, db: Session = Depends(get_db)):
    """Публичная отдача всей структуры пространства (этажи, POI, панорамы, навигационный граф) для фронтенд-вьюера."""
    space = (
        db.query(models.Space)
        .options(
            selectinload(models.Space.floors).selectinload(models.Floor.pois),
            selectinload(models.Space.floors).selectinload(models.Floor.panoramas),
        )
        .filter(models.Space.slug == slug)
        .first()
    )

    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пространство не найдено")

    return space


@app.post(
    "/api/spaces",
    response_model=schemas.SpaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создание нового пространства",
    tags=["Spaces"],
)
def create_space(payload: schemas.SpaceCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Space).filter(models.Space.slug == payload.slug).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Пространство с slug '{payload.slug}' уже существует",
        )

    space = models.Space(
        title=payload.title,
        slug=payload.slug,
        description=payload.description,
        is_published=payload.is_published,
    )
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


@app.get(
    "/api/spaces",
    response_model=List[schemas.SpaceResponse],
    summary="Список пространств",
    tags=["Spaces"],
)
def list_spaces(db: Session = Depends(get_db)):
    return db.query(models.Space).all()


# ==========================================
# Floors Endpoints
# ==========================================

@app.post(
    "/api/floors",
    response_model=schemas.FloorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создание этажа",
    tags=["Floors"],
)
def create_floor(payload: schemas.FloorCreate, db: Session = Depends(get_db)):
    space_id = int(payload.space_id)
    space = db.query(models.Space).filter(models.Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пространство не найдено")

    nav_dict = payload.nav_graph.model_dump(by_alias=True) if isinstance(payload.nav_graph, schemas.NavGraph) else payload.nav_graph

    floor = models.Floor(
        space_id=space_id,
        level=payload.level,
        name=payload.name,
        plan_image_url=payload.plan_image_url,
        width=payload.width,
        height=payload.height,
        nav_graph=nav_dict,
    )
    db.add(floor)
    db.commit()
    db.refresh(floor)
    return floor


@app.post(
    "/api/floors/{floor_id}/upload-plan",
    response_model=schemas.FloorResponse,
    summary="Загрузка картинки плана этажа",
    tags=["Floors"],
)
async def upload_floor_plan(
    floor_id: int,
    file: UploadFile = File(..., description="Файл изображения плана (PNG, JPG, SVG, WebP)"),
    width: Optional[int] = Form(None, description="Ширина в пикселях (если не указана, вычисляется Pillow)"),
    height: Optional[int] = Form(None, description="Высота в пикселях (если не указана, вычисляется Pillow)"),
    db: Session = Depends(get_db),
):
    """Загрузка картинки плана этажа (сохранение в static/uploads/plans).

    Автоматически определяет ширину и высоту изображения с помощью Pillow.
    """
    floor = db.query(models.Floor).filter(models.Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Этаж не найден")

    filename = file.filename or "plan.png"
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in [".png", ".jpg", ".jpeg", ".svg", ".webp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Поддерживаются только изображения форматов PNG, JPG, JPEG, SVG, WEBP",
        )

    unique_filename = f"plan_{floor_id}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = os.path.join(PLANS_DIR, unique_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Определение размеров плана
    if width is not None and height is not None:
        floor.width = width
        floor.height = height
    else:
        try:
            with Image.open(file_path) as img:
                floor.width, floor.height = img.size
        except Exception:
            pass  # Для SVG или нестандартных форматов сохраняем исходные width/height

    relative_url = f"/static/uploads/plans/{unique_filename}"
    floor.plan_image_url = relative_url
    db.commit()
    db.refresh(floor)

    return floor


@app.put(
    "/api/floors/{floor_id}/graph",
    response_model=schemas.FloorResponse,
    summary="Обновление навигационного графа этажа",
    tags=["Floors"],
)
def update_floor_graph(
    floor_id: int,
    payload: schemas.FloorGraphUpdate,
    db: Session = Depends(get_db),
):
    """Обновление навигационного графа этажа (узлы и рёбра)."""
    floor = db.query(models.Floor).filter(models.Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Этаж не найден")

    if isinstance(payload.nav_graph, schemas.NavGraph):
        floor.nav_graph = payload.nav_graph.model_dump(by_alias=True)
    elif isinstance(payload.nav_graph, dict):
        floor.nav_graph = payload.nav_graph
    else:
        floor.nav_graph = payload.nav_graph

    db.commit()
    db.refresh(floor)
    return floor


# ==========================================
# Panoramas Endpoints (Upload & CRUD)
# ==========================================

@app.post(
    "/api/panoramas/upload",
    response_model=schemas.PanoramaUploadResponse,
    summary="Загрузка 360-фото и создание миниатюры (Pillow)",
    tags=["Panoramas"],
)
async def upload_panorama(
    file: UploadFile = File(..., description="Файл 360-градусной эквидистантной панорамы"),
    floor_id: Optional[Union[int, str]] = Form(None, alias="floorId", description="ID этажа"),
    title: Optional[str] = Form(None, description="Название панорамы"),
    x: float = Form(0.0, description="Положение X на 2D-плане (0..100%)"),
    y: float = Form(0.0, description="Положение Y на 2D-плане (0..100%)"),
    connections: Optional[str] = Form(None, description="Связи переходов в формате JSON-строки"),
    db: Session = Depends(get_db),
):
    """Загрузка 360-фото, создание миниатюры (Pillow thumbnail) и сохранение."""
    filename = file.filename or "panorama.jpg"
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Поддерживаются только форматы JPG, JPEG, PNG, WEBP для 360-панорам",
        )

    file_uuid = uuid.uuid4().hex[:10]
    unique_filename = f"pano_{file_uuid}{ext}"
    thumb_filename = f"thumb_{file_uuid}.jpg"

    original_path = os.path.join(PANORAMAS_DIR, unique_filename)
    thumb_path = os.path.join(THUMBS_DIR, thumb_filename)

    with open(original_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        create_image_thumbnail(original_path, thumb_path, size=(400, 200))
    except Exception as e:
        if os.path.exists(original_path):
            os.remove(original_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки изображения Pillow: {str(e)}",
        )

    image_url = f"/static/uploads/panoramas/{unique_filename}"
    thumbnail_url = f"/static/uploads/panoramas/thumbs/{thumb_filename}"

    created_panorama = None
    if floor_id is not None:
        target_floor_id = int(floor_id)
        floor = db.query(models.Floor).filter(models.Floor.id == target_floor_id).first()
        if not floor:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Этаж не найден")

        parsed_connections = []
        if connections:
            try:
                parsed_connections = json.loads(connections)
            except Exception:
                parsed_connections = connections

        pano_title = title if title else f"Панорама {file_uuid[:6]}"
        created_panorama = models.Panorama(
            floor_id=target_floor_id,
            title=pano_title,
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            x=x,
            y=y,
            connections=parsed_connections,
        )
        db.add(created_panorama)
        db.commit()
        db.refresh(created_panorama)

    return schemas.PanoramaUploadResponse(
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        panorama=created_panorama,
    )


@app.post(
    "/api/panoramas",
    response_model=schemas.PanoramaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создание панорамы (CRUD)",
    tags=["Panoramas"],
)
def create_panorama(payload: schemas.PanoramaCreate, db: Session = Depends(get_db)):
    floor_id = int(payload.floor_id)
    floor = db.query(models.Floor).filter(models.Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Этаж не найден")

    conn_dump = [c.model_dump(by_alias=True) for c in payload.connections] if payload.connections else []

    panorama = models.Panorama(
        floor_id=floor_id,
        title=payload.title,
        image_url=payload.image_url,
        thumbnail_url=payload.thumbnail_url,
        x=payload.x,
        y=payload.y,
        connections=conn_dump,
    )
    db.add(panorama)
    db.commit()
    db.refresh(panorama)
    return panorama


@app.get(
    "/api/panoramas",
    response_model=List[schemas.PanoramaResponse],
    summary="Список панорам (CRUD)",
    tags=["Panoramas"],
)
def list_panoramas(
    floor_id: Optional[int] = Query(None, alias="floorId", description="Фильтр по ID этажа"),
    db: Session = Depends(get_db),
):
    query = db.query(models.Panorama)
    if floor_id is not None:
        query = query.filter(models.Panorama.floor_id == floor_id)
    return query.all()


@app.get(
    "/api/panoramas/{id}",
    response_model=schemas.PanoramaResponse,
    summary="Получение панорамы по ID (CRUD)",
    tags=["Panoramas"],
)
def get_panorama(id: int, db: Session = Depends(get_db)):
    panorama = db.query(models.Panorama).filter(models.Panorama.id == id).first()
    if not panorama:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Панорама не найдена")
    return panorama


@app.put(
    "/api/panoramas/{id}",
    response_model=schemas.PanoramaResponse,
    summary="Обновление панорамы по ID (CRUD)",
    tags=["Panoramas"],
)
def update_panorama(id: int, payload: schemas.PanoramaUpdate, db: Session = Depends(get_db)):
    panorama = db.query(models.Panorama).filter(models.Panorama.id == id).first()
    if not panorama:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Панорама не найдена")

    update_data = payload.model_dump(exclude_unset=True)
    if "floor_id" in update_data and update_data["floor_id"] is not None:
        target_floor_id = int(update_data["floor_id"])
        floor = db.query(models.Floor).filter(models.Floor.id == target_floor_id).first()
        if not floor:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Указанный этаж не существует")
        update_data["floor_id"] = target_floor_id

    if "connections" in update_data and update_data["connections"] is not None:
        update_data["connections"] = [
            c if isinstance(c, dict) else c.model_dump(by_alias=True)
            for c in update_data["connections"]
        ]

    for field, value in update_data.items():
        setattr(panorama, field, value)

    db.commit()
    db.refresh(panorama)
    return panorama


@app.delete(
    "/api/panoramas/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление панорамы по ID (CRUD)",
    tags=["Panoramas"],
)
def delete_panorama(id: int, db: Session = Depends(get_db)):
    panorama = db.query(models.Panorama).filter(models.Panorama.id == id).first()
    if not panorama:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Панорама не найдена")

    db.delete(panorama)
    db.commit()
    return None


# ==========================================
# POI Endpoints (CRUD)
# ==========================================

@app.post(
    "/api/pois",
    response_model=schemas.POIResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создание точки интереса (POI)",
    tags=["POI"],
)
def create_poi(payload: schemas.POICreate, db: Session = Depends(get_db)):
    floor_id = int(payload.floor_id)
    floor = db.query(models.Floor).filter(models.Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Этаж не найден")

    pano_id = int(payload.panorama_id) if payload.panorama_id is not None else None
    if pano_id is not None:
        pano = db.query(models.Panorama).filter(models.Panorama.id == pano_id).first()
        if not pano:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Указанная панорама не найдена")

    poi = models.POI(
        floor_id=floor_id,
        title=payload.title,
        category=payload.category,
        description=payload.description,
        x=payload.x,
        y=payload.y,
        panorama_id=pano_id,
    )
    db.add(poi)
    db.commit()
    db.refresh(poi)
    return poi


@app.get(
    "/api/pois",
    response_model=List[schemas.POIResponse],
    summary="Список точек интереса (POI)",
    tags=["POI"],
)
def list_pois(
    floor_id: Optional[int] = Query(None, alias="floorId", description="Фильтр по ID этажа"),
    category: Optional[str] = Query(None, description="Фильтр по категории"),
    db: Session = Depends(get_db),
):
    query = db.query(models.POI)
    if floor_id is not None:
        query = query.filter(models.POI.floor_id == floor_id)
    if category is not None:
        query = query.filter(models.POI.category == category)
    return query.all()


@app.get(
    "/api/pois/{id}",
    response_model=schemas.POIResponse,
    summary="Получение точки интереса по ID (POI)",
    tags=["POI"],
)
def get_poi(id: int, db: Session = Depends(get_db)):
    poi = db.query(models.POI).filter(models.POI.id == id).first()
    if not poi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Точка интереса не найдена")
    return poi


@app.put(
    "/api/pois/{id}",
    response_model=schemas.POIResponse,
    summary="Обновление точки интереса по ID (POI)",
    tags=["POI"],
)
def update_poi(id: int, payload: schemas.POIUpdate, db: Session = Depends(get_db)):
    poi = db.query(models.POI).filter(models.POI.id == id).first()
    if not poi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Точка интереса не найдена")

    update_data = payload.model_dump(exclude_unset=True)

    if "floor_id" in update_data and update_data["floor_id"] is not None:
        target_floor_id = int(update_data["floor_id"])
        floor = db.query(models.Floor).filter(models.Floor.id == target_floor_id).first()
        if not floor:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Указанный этаж не найден")
        update_data["floor_id"] = target_floor_id

    if "panorama_id" in update_data and update_data["panorama_id"] is not None:
        target_pano_id = int(update_data["panorama_id"])
        pano = db.query(models.Panorama).filter(models.Panorama.id == target_pano_id).first()
        if not pano:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Указанная панорама не найдена")
        update_data["panorama_id"] = target_pano_id

    for field, value in update_data.items():
        setattr(poi, field, value)

    db.commit()
    db.refresh(poi)
    return poi


@app.delete(
    "/api/pois/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление точки интереса по ID (POI)",
    tags=["POI"],
)
def delete_poi(id: int, db: Session = Depends(get_db)):
    poi = db.query(models.POI).filter(models.POI.id == id).first()
    if not poi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Точка интереса не найдена")

    db.delete(poi)
    db.commit()
    return None

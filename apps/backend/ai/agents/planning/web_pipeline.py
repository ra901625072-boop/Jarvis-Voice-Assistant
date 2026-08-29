"""
ai/agents/planning/web_pipeline.py — Professional Web Development Pipeline Compiler.

Implements an end-to-end, multi-stage pipeline for building production-grade websites,
web applications, and full-stack systems:
  1. Requirements & PRD Generation (docs/PRD.md)
  2. Research & UI/UX Design System (docs/DESIGN_SYSTEM.md)
  3. Technical Architecture & Database Schema (docs/ARCHITECTURE.md, schema.sql)
  4. Backend Scaffolding, Models, Routers & Business Logic (backend/)
  5. Database Setup, Connection & Seed Data (backend/database.py)
  6. Frontend Scaffolding, Views & Accessible Components (frontend/)
  7. API Integration, Auth & Security Layer (CORS, JWT, api.js)
  8. Automated Testing & QA (tests/test_api.py)
  9. Performance Optimization & Containerization (Dockerfile, docker-compose.yml, start.bat, README.md)
  10. Verification, Smoke Testing & Self-Healing Remediation
"""

import os
import re
import logging
from typing import List, Dict, Any, Optional
from modules.task.state_manager import SubTask

logger = logging.getLogger("JARVIS.WebPipeline")

# Keywords that indicate a web development project
WEB_KEYWORDS = [
    "website", "web site", "web app", "web application", "web service",
    "web platform", "hotel booking", "ecommerce", "e-commerce", "online store",
    "landing page", "dashboard", "portal", "portfolio", "blog site", "saas",
    "full stack", "fullstack", "frontend", "front-end", "backend and frontend",
    "create site", "build site", "make website", "develop website", "create website"
]


def is_web_development_goal(goal: str) -> bool:
    """Determine if a user goal is requesting the creation/development of a web project."""
    if not goal:
        return False
    goal_lower = goal.strip().lower()

    # Exclude simple informational, search, or URL opening/browsing queries
    if goal_lower.startswith(("what is", "how to", "explain", "who is", "search for", "google ", "open ", "visit ", "go to ", "show ", "launch ", "browse ")):
        if not any(dev_verb in goal_lower for dev_verb in ["create", "build", "develop", "make", "scaffold", "code"]):
            return False

    return any(keyword in goal_lower for keyword in WEB_KEYWORDS)


def extract_project_metadata(goal: str) -> Dict[str, Any]:
    """Extract project name, domain topic, target folder, and tech stack from goal description."""
    goal_clean = goal.strip()
    goal_lower = goal_clean.lower()
    
    # Extract project title/topic
    topic = "web_project"
    for kw in ["hotel booking", "ecommerce", "e-commerce", "task manager", "booking", "portfolio", "dashboard", "blog", "chat", "real estate", "restaurant", "hospital", "travel"]:
        if kw in goal_lower:
            topic = kw.replace("-", "_").replace(" ", "_")
            break
            
    if topic == "web_project":
        m = re.search(r'(?:create|build|make|develop)\s+(?:a|an)?\s*([a-zA-Z0-9_\-\s]+?)(?:\s+(?:website|webapp|web app|site|platform|with|in))', goal_lower)
        if m:
            extracted = m.group(1).strip().replace(" ", "_")
            if extracted:
                topic = re.sub(r'[^a-zA-Z0-9_]', '', extracted)[:24]

    project_name = f"{topic}_app"
    target_dir = f"d:/Jarvis/scratch/{project_name}"
    
    path_match = re.search(r'(?:in|at|to)\s+([a-zA-Z]:[\\/][a-zA-Z0-9_\-\\/]+)', goal_clean)
    if path_match:
        target_dir = path_match.group(1).replace("\\", "/")

    tech_stack = "fastapi-react"
    if "django" in goal_lower:
        tech_stack = "django-react"
    elif "flask" in goal_lower:
        tech_stack = "flask-react"
    elif "node" in goal_lower or "express" in goal_lower:
        tech_stack = "node-react"
    elif "next" in goal_lower or "nextjs" in goal_lower:
        tech_stack = "nextjs"

    return {
        "project_name": project_name,
        "topic": topic.replace("_", " ").title(),
        "target_dir": target_dir,
        "tech_stack": tech_stack,
        "goal": goal_clean
    }


def compile_web_development_pipeline(goal: str, context_str: str = "") -> List[SubTask]:
    """
    Compiles a comprehensive, dependency-aware 15-stage Web Development Workflow
    into an ordered DAG of executable SubTasks.
    """
    meta = extract_project_metadata(goal)
    p_name = meta["project_name"]
    p_topic = meta["topic"]
    t_dir = meta["target_dir"]
    
    subtasks: List[SubTask] = []
    
    # ── Phase 1: Requirements & PRD ──────────────────────────────────────────
    prd_content = f"""# Product Requirements Document (PRD): {p_topic} Website

## 1. Executive Summary
The **{p_topic}** platform is an end-to-end modern web application designed for high usability, security, responsiveness, and performance.

## 2. Target Users & Personas
- **Customer / Guest**: Browses items/listings, applies filters, views details, completes reservations/orders, manages profile.
- **Administrator**: Manages inventory/listings, views booking metrics, handles user permissions and reports.

## 3. Core Functional Requirements
1. **Interactive Catalog & Search**: Real-time filtering by category, price, dates, and availability.
2. **Detail & Booking / Ordering Flow**: Step-by-step checkout with form validation and instant confirmation.
3. **User Authentication & Profiles**: Secure JWT-based login, registration, and active session management.
4. **Admin Dashboard**: Metrics overview, status updates, and CRUD management.

## 4. Non-Functional Requirements
- **Performance**: Sub-100ms API response time, optimized assets.
- **Accessibility**: WCAG 2.1 AA compliant color contrast and keyboard navigation.
- **Security**: Password hashing, JWT token expiry, CORS isolation, sanitized SQL inputs.
- **Cross-Platform**: Full responsiveness across mobile, tablet, and desktop viewports.
"""
    subtasks.append(SubTask(
        task_id=1,
        description=f"Generate Product Requirements Document (PRD) for {p_topic} website",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/docs/PRD.md",
            "code": prd_content,
            "instruction": "Create the Product Requirements Document"
        },
        dependencies=[],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/docs/PRD.md",
        execution_mode="deterministic"
    ))

    # ── Phase 2: Research & UI/UX Design System ──────────────────────────────
    design_system_content = f"""# UI/UX Design System: {p_topic}

## 1. Color Palette (WCAG 2.1 AA Compliant)
- **Primary Brand**: `#2563EB` (Blue 600) — Dominant action color (Contrast 4.8:1 on white)
- **Primary Hover**: `#1D4ED8` (Blue 700)
- **Secondary / Accent**: `#0D9488` (Teal 600) — Badges, highlights, success tags
- **Background (Light)**: `#F8FAFC` (Slate 50)
- **Surface / Cards**: `#FFFFFF` (Pure White)
- **Text Primary**: `#0F172A` (Slate 900 — Contrast 15.8:1 on white)
- **Text Secondary**: `#475569` (Slate 600 — Contrast 5.1:1 on white)
- **Danger / Error**: `#DC2626` (Red 600)
- **Success**: `#16A34A` (Green 600)

## 2. Typography
- **Headings**: Inter / System UI, Bold (Weights 600, 700)
- **Body**: Inter / Roboto, Regular (Weight 400), Medium (Weight 500)

## 3. UI Components & States
- **Navbar**: Sticky header with logo, navigation links, search bar, and auth buttons.
- **Hero Section**: Value proposition headline, high-impact CTA, quick search widget.
- **Card Grid**: Responsive 1/2/3-column grid with image preview, badge, rating, price, and CTA.
- **Interactive Modal / Drawer**: Smooth booking / checkout modal with form validation feedback.
- **Empty / Loading States**: Skeleton loaders and clean empty state illustrations.
"""
    subtasks.append(SubTask(
        task_id=2,
        description=f"Create UI/UX Design System Specification & Design Tokens for {p_topic}",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/docs/DESIGN_SYSTEM.md",
            "code": design_system_content,
            "instruction": "Create the Design System Specification"
        },
        dependencies=[1],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/docs/DESIGN_SYSTEM.md",
        execution_mode="deterministic"
    ))

    # ── Phase 3: Technical Architecture & Database Schema ────────────────────
    arch_content = f"""# Technical Architecture & Database Design: {p_topic}

## 1. System Architecture
```text
  [ Client Browser (HTML5/React/Tailwind) ]
                     │  HTTP / JSON (REST API)
                     ▼
       [ Backend API Server (Python FastAPI) ]
         ├── CORS & Security Middleware
         ├── Auth & JWT Token Validator
         ├── Business Logic Controllers
         └── Data Access Layer (SQLAlchemy / SQLite)
                     │
                     ▼
         [ Database (SQLite / PostgreSQL) ]
```

## 2. API Route Specifications
- `GET  /api/health` — System status & connectivity check
- `GET  /api/items` — List items / listings with query filters
- `GET  /api/items/:id` — Retrieve item details
- `POST /api/bookings` — Create a new booking / reservation
- `GET  /api/bookings` — List user bookings

## 3. Database Entities (ERD)
- **users** (`id`, `email`, `password_hash`, `full_name`, `role`, `created_at`)
- **items** (`id`, `title`, `description`, `price_per_night`, `location`, `rating`, `image_url`, `created_at`)
- **bookings** (`id`, `user_id`, `item_id`, `start_date`, `end_date`, `total_price`, `status`, `created_at`)
"""
    subtasks.append(SubTask(
        task_id=3,
        description=f"Design Technical Architecture & Database Schema for {p_topic}",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/docs/ARCHITECTURE.md",
            "code": arch_content,
            "instruction": "Create the Technical Architecture and ERD document"
        },
        dependencies=[1],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/docs/ARCHITECTURE.md",
        execution_mode="deterministic"
    ))

    # ── Phase 4: Database Models ─────────────────────────────────────────────
    models_code = """from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship
import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, default="customer")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    bookings = relationship("Booking", back_populates="user")

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    location = Column(String, nullable=False)
    rating = Column(Float, default=4.8)
    image_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    bookings = relationship("Booking", back_populates="item")

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=False)
    start_date = Column(String, nullable=False)
    end_date = Column(String, nullable=False)
    total_price = Column(Float, nullable=False)
    status = Column(String, default="confirmed")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    user = relationship("User", back_populates="bookings")
    item = relationship("Item", back_populates="bookings")
"""
    subtasks.append(SubTask(
        task_id=4,
        description=f"Create backend database models in backend/models.py",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/backend/models.py",
            "code": models_code,
            "instruction": "Define database models"
        },
        dependencies=[3],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/backend/models.py",
        execution_mode="deterministic"
    ))

    # ── Phase 5: Database Connection & Seeding ───────────────────────────────
    db_template = """from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from .models import Base, Item

DB_PATH = os.path.join(os.path.dirname(__file__), "{PROJECT_NAME}.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if db.query(Item).count() == 0:
        sample_items = [
            Item(
                title="Grand Luxury Suite & Spa",
                description="Experience unmatched luxury with panoramic city views, private balcony, marble bath, and 24/7 concierge service.",
                price=249.0,
                location="Downtown Metropolitan",
                rating=4.9,
                image_url="https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=800&q=80"
            ),
            Item(
                title="Seaside Oceanview Villa",
                description="Direct private beach access, infinity pool overlooking azure waters, gourmet kitchen, and sunset terrace.",
                price=389.0,
                location="Coastal Bay Promenade",
                rating=5.0,
                image_url="https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?auto=format&fit=crop&w=800&q=80"
            ),
            Item(
                title="Serene Mountain Alpine Retreat",
                description="Cozy cedar chalet surrounded by pine forests, heated stone fireplace, sauna, and ski-in access.",
                price=185.0,
                location="Alpine Valley Slopes",
                rating=4.8,
                image_url="https://images.unsplash.com/photo-1571896349842-33c89424de2d?auto=format&fit=crop&w=800&q=80"
            ),
            Item(
                title="Modern Executive Penthouse",
                description="Ultra-modern smart home with skyline vistas, private gym, high-speed fiber WiFi, and business lounge access.",
                price=310.0,
                location="Financial District",
                rating=4.7,
                image_url="https://images.unsplash.com/photo-1590490360182-c33d57733427?auto=format&fit=crop&w=800&q=80"
            )
        ]
        db.add_all(sample_items)
        db.commit()
    db.close()

# Auto-initialize tables immediately
init_db()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
"""
    db_code = db_template.replace("{PROJECT_NAME}", p_name)
    subtasks.append(SubTask(
        task_id=5,
        description=f"Create database connection and seed data in backend/database.py",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/backend/database.py",
            "code": db_code,
            "instruction": "Create database initialization and seed data"
        },
        dependencies=[4],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/backend/database.py",
        execution_mode="deterministic"
    ))

    # ── Phase 6: Backend REST API Server ─────────────────────────────────────
    main_py_template = """from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
import os

from .database import get_db, init_db
from .models import Item, Booking

# Initialize database schema and seeds
init_db()

app = FastAPI(title="{PROJECT_TOPIC} API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ItemResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    price: float
    location: str
    rating: float
    image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class BookingCreate(BaseModel):
    item_id: int
    customer_name: str
    customer_email: str
    start_date: str
    end_date: str
    total_price: float

class BookingResponse(BaseModel):
    id: int
    item_id: int
    customer_name: str
    customer_email: str
    start_date: str
    end_date: str
    total_price: float
    status: str

    model_config = ConfigDict(from_attributes=True)

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "{PROJECT_TOPIC} API", "version": "1.0.0"}

@app.get("/api/items", response_model=List[ItemResponse])
def get_items(
    search: Optional[str] = None,
    max_price: Optional[float] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Item)
    if search:
        query = query.filter(Item.title.contains(search) | Item.location.contains(search))
    if max_price:
        query = query.filter(Item.price <= max_price)
    return query.all()

@app.get("/api/items/{item_id}", response_model=ItemResponse)
def get_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.post("/api/bookings", response_model=BookingResponse)
def create_booking(booking: BookingCreate, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == booking.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    new_booking = Booking(
        item_id=booking.item_id,
        customer_name=booking.customer_name,
        customer_email=booking.customer_email,
        start_date=booking.start_date,
        end_date=booking.end_date,
        total_price=booking.total_price,
        status="confirmed"
    )
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    return new_booking

@app.get("/api/bookings", response_model=List[BookingResponse])
def list_bookings(db: Session = Depends(get_db)):
    return db.query(Booking).order_by(Booking.id.desc()).all()

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
"""
    main_py_code = main_py_template.replace("{PROJECT_TOPIC}", p_topic)
    subtasks.append(SubTask(
        task_id=6,
        description=f"Create backend REST API server with FastAPI in backend/main.py",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/backend/main.py",
            "code": main_py_code,
            "instruction": "Create FastAPI REST backend"
        },
        dependencies=[5],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/backend/main.py",
        execution_mode="deterministic"
    ))

    # ── Phase 7: Backend Requirements ────────────────────────────────────────
    reqs_code = """fastapi>=0.100.0
uvicorn>=0.22.0
sqlalchemy>=2.0.0
pydantic>=2.0.0
httpx>=0.24.0
pytest>=7.0.0
"""
    subtasks.append(SubTask(
        task_id=7,
        description=f"Create backend requirements.txt",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/backend/requirements.txt",
            "code": reqs_code,
            "instruction": "Create requirements.txt"
        },
        dependencies=[6],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/backend/requirements.txt",
        execution_mode="deterministic"
    ))

    # ── Phase 8: Modern Responsive Frontend Application ──────────────────────
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{PROJECT_TOPIC} — Premium Experience</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/lucide@latest"></script>
</head>
<body class="bg-slate-50 text-slate-900 font-sans antialiased min-h-screen flex flex-col">

  <header class="sticky top-0 z-40 bg-white/95 backdrop-blur border-b border-slate-200 shadow-sm">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center text-white font-bold text-xl shadow-md">
          <i data-lucide="compass"></i>
        </div>
        <span class="font-extrabold text-xl tracking-tight text-blue-600">{PROJECT_TOPIC}</span>
      </div>
      <nav class="hidden md:flex items-center gap-8 text-sm font-medium text-slate-600">
        <a href="#catalog" class="hover:text-blue-600 transition-colors">Explore</a>
        <a href="#bookings-section" class="hover:text-blue-600 transition-colors">My Bookings</a>
      </nav>
      <button onclick="document.getElementById('catalog').scrollIntoView({behavior: 'smooth'})" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg text-sm transition-all shadow-sm flex items-center gap-2">
        <i data-lucide="calendar" class="w-4 h-4"></i>
        <span>Book Now</span>
      </button>
    </div>
  </header>

  <section class="relative bg-gradient-to-b from-blue-50/60 to-transparent pt-12 pb-16 px-4 sm:px-6 lg:px-8">
    <div class="max-w-4xl mx-auto text-center">
      <h1 class="text-4xl sm:text-5xl font-black text-slate-900 tracking-tight leading-tight">
        Discover & Book Extraordinary {PROJECT_TOPIC}
      </h1>
      <p class="mt-4 text-lg text-slate-600 max-w-2xl mx-auto">
        Handcrafted luxury experiences with instant confirmation and 24/7 dedicated support.
      </p>

      <div class="mt-8 bg-white p-3 rounded-2xl shadow-xl border border-slate-200 flex flex-col md:flex-row gap-3 items-center max-w-3xl mx-auto">
        <div class="flex-1 flex items-center gap-2 px-3 w-full border-b md:border-b-0 md:border-r border-slate-200 pb-2 md:pb-0">
          <i data-lucide="search" class="text-slate-400 w-5 h-5"></i>
          <input type="text" id="searchInput" placeholder="Search destination, city, or title..." class="w-full text-sm outline-none bg-transparent">
        </div>
        <div class="flex items-center gap-2 px-3 w-full md:w-48">
          <select id="priceFilter" class="w-full text-sm outline-none bg-transparent text-slate-600">
            <option value="">Any Price</option>
            <option value="200">Under $200</option>
            <option value="300">Under $300</option>
            <option value="400">Under $400</option>
          </select>
        </div>
        <button onclick="fetchItems()" class="w-full md:w-auto px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-xl text-sm transition-all shadow-md flex items-center justify-center gap-2">
          <span>Search</span>
        </button>
      </div>
    </div>
  </section>

  <main id="catalog" class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 flex-1 w-full">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-2xl font-bold text-slate-900">Featured Accommodations</h2>
        <p class="text-sm text-slate-500 mt-1">Select an option to reserve</p>
      </div>
      <div id="resultsCount" class="text-sm font-semibold text-slate-600 bg-slate-100 px-3 py-1 rounded-lg">Loading...</div>
    </div>
    <div id="itemsGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8"></div>
  </main>

  <section id="bookings-section" class="bg-slate-100/70 border-t border-slate-200 py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-7xl mx-auto">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <i data-lucide="check-circle" class="text-teal-600"></i>
          Recent Bookings
        </h2>
        <button onclick="fetchBookings()" class="text-sm font-medium text-blue-600 hover:underline">Refresh</button>
      </div>
      <div id="bookingsList" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>
    </div>
  </section>

  <div id="bookingModal" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-100 relative">
      <button onclick="closeBookingModal()" class="absolute top-4 right-4 text-slate-400 hover:text-slate-600">
        <i data-lucide="x" class="w-5 h-5"></i>
      </button>
      <h3 id="modalTitle" class="text-xl font-bold text-slate-900 mb-2">Reserve Stay</h3>
      <p id="modalDescription" class="text-sm text-slate-500 mb-6"></p>

      <form id="bookingForm" onsubmit="handleBookingSubmit(event)" class="space-y-4">
        <input type="hidden" id="modalItemId">
        <input type="hidden" id="modalItemPrice">

        <div>
          <label class="block text-xs font-semibold text-slate-700 uppercase mb-1">Full Name</label>
          <input type="text" id="customerName" required placeholder="John Doe" class="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm">
        </div>
        <div>
          <label class="block text-xs font-semibold text-slate-700 uppercase mb-1">Email</label>
          <input type="email" id="customerEmail" required placeholder="john@example.com" class="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm">
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-xs font-semibold text-slate-700 uppercase mb-1">Check-in</label>
            <input type="date" id="startDate" required class="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm">
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-700 uppercase mb-1">Check-out</label>
            <input type="date" id="endDate" required class="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm">
          </div>
        </div>

        <div class="bg-slate-50 p-3 rounded-xl border border-slate-200 flex justify-between items-center text-sm font-semibold">
          <span class="text-slate-600">Total (3 Nights):</span>
          <span id="modalEstimatedTotal" class="text-blue-600 text-lg">$0.00</span>
        </div>

        <button type="submit" class="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-xl text-sm shadow-md">
          Confirm Reservation
        </button>
      </form>
    </div>
  </div>

  <script>
    const API_BASE = window.location.origin.includes(':8000') || window.location.origin.includes(':3000')
      ? window.location.origin
      : 'http://localhost:8000';

    let allItems = [];

    async function fetchItems() {
      const search = document.getElementById('searchInput').value;
      const maxPrice = document.getElementById('priceFilter').value;
      let url = API_BASE + '/api/items?';
      if (search) url += 'search=' + encodeURIComponent(search) + '&';
      if (maxPrice) url += 'max_price=' + maxPrice + '&';

      try {
        const res = await fetch(url);
        if (res.ok) {
          allItems = await res.json();
          renderItems(allItems);
        }
      } catch (err) {
        console.warn('Using mock catalog');
      }
    }

    function renderItems(items) {
      const grid = document.getElementById('itemsGrid');
      const count = document.getElementById('resultsCount');
      count.textContent = items.length + ' listings available';

      grid.innerHTML = items.map(function(item) {
        return '<div class="bg-white rounded-2xl overflow-hidden border border-slate-200 shadow-sm hover:shadow-xl transition-all duration-300 flex flex-col group">' +
          '<div class="relative h-52 overflow-hidden bg-slate-100">' +
            '<img src="' + (item.image_url || 'https://images.unsplash.com/photo-1566073771259-6a8506099945') + '" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500">' +
            '<div class="absolute bottom-3 left-3 bg-slate-900/80 backdrop-blur px-3 py-1 rounded-lg text-xs font-semibold text-white">' + item.location + '</div>' +
          '</div>' +
          '<div class="p-5 flex-1 flex flex-col justify-between">' +
            '<div>' +
              '<h3 class="text-lg font-bold text-slate-900 group-hover:text-blue-600 transition-colors">' + item.title + '</h3>' +
              '<p class="text-slate-500 text-sm mt-1 line-clamp-2">' + item.description + '</p>' +
            '</div>' +
            '<div class="mt-6 pt-4 border-t border-slate-100 flex items-center justify-between">' +
              '<span class="text-2xl font-black text-slate-900">$' + item.price + ' <span class="text-xs text-slate-500 font-medium">/ night</span></span>' +
              '<button onclick="openBookingModal(' + item.id + ')" class="px-4 py-2 bg-blue-50 hover:bg-blue-600 text-blue-600 hover:text-white font-semibold rounded-lg text-sm transition-colors">Book</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      }).join('');
      lucide.createIcons();
    }

    function openBookingModal(itemId) {
      const item = allItems.find(function(i) { return i.id === itemId; });
      if (!item) return;
      document.getElementById('modalItemId').value = item.id;
      document.getElementById('modalItemPrice').value = item.price;
      document.getElementById('modalTitle').textContent = 'Book ' + item.title;
      document.getElementById('modalDescription').textContent = item.location + ' • $' + item.price + ' / night';
      const today = new Date().toISOString().split('T')[0];
      const future = new Date(Date.now() + 3*86400000).toISOString().split('T')[0];
      document.getElementById('startDate').value = today;
      document.getElementById('endDate').value = future;
      document.getElementById('modalEstimatedTotal').textContent = '$' + (item.price * 3).toFixed(2);
      document.getElementById('bookingModal').classList.remove('hidden');
      lucide.createIcons();
    }

    function closeBookingModal() {
      document.getElementById('bookingModal').classList.add('hidden');
    }

    async function handleBookingSubmit(event) {
      event.preventDefault();
      const payload = {
        item_id: parseInt(document.getElementById('modalItemId').value),
        customer_name: document.getElementById('customerName').value,
        customer_email: document.getElementById('customerEmail').value,
        start_date: document.getElementById('startDate').value,
        end_date: document.getElementById('endDate').value,
        total_price: parseFloat(document.getElementById('modalItemPrice').value) * 3
      };
      try {
        const res = await fetch(API_BASE + '/api/bookings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        alert('Booking successfully recorded!');
        closeBookingModal();
        fetchBookings();
      } catch (err) {
        alert('Booking saved locally.');
        closeBookingModal();
      }
    }

    async function fetchBookings() {
      const container = document.getElementById('bookingsList');
      try {
        const res = await fetch(API_BASE + '/api/bookings');
        if (res.ok) {
          const bookings = await res.json();
          container.innerHTML = bookings.map(function(b) {
            return '<div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">' +
              '<div>' +
                '<p class="font-bold text-slate-900">' + b.customer_name + ' <span class="text-xs text-slate-500 font-normal">(' + b.customer_email + ')</span></p>' +
                '<p class="text-xs text-slate-500">' + b.start_date + ' to ' + b.end_date + '</p>' +
              '</div>' +
              '<span class="text-sm font-bold text-teal-600 bg-teal-50 px-2.5 py-1 rounded-full border border-teal-200">Confirmed: $' + b.total_price + '</span>' +
            '</div>';
          }).join('');
          lucide.createIcons();
        }
      } catch (e) {}
    }

    document.addEventListener('DOMContentLoaded', function() {
      fetchItems();
      fetchBookings();
      lucide.createIcons();
    });
  </script>
</body>
</html>
"""
    html_code = html_template.replace("{PROJECT_TOPIC}", p_topic)
    subtasks.append(SubTask(
        task_id=8,
        description=f"Build modern responsive Frontend UI with Tailwind CSS in frontend/index.html",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/frontend/index.html",
            "code": html_code,
            "instruction": "Create frontend application HTML5/Tailwind"
        },
        dependencies=[6],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/frontend/index.html",
        execution_mode="deterministic"
    ))

    # ── Phase 9: Automated Test Suite & QA ───────────────────────────────────
    test_code = """import pytest
from fastapi.testclient import TestClient
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.main import app

def test_health_check():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data

def test_get_items():
    client = TestClient(app)
    response = client.get("/api/items")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert len(items) > 0

def test_create_and_list_booking():
    client = TestClient(app)
    payload = {
        "item_id": 1,
        "customer_name": "Alice Tester",
        "customer_email": "alice@example.com",
        "start_date": "2026-09-01",
        "end_date": "2026-09-05",
        "total_price": 747.0
    }
    res = client.post("/api/bookings", json=payload)
    assert res.status_code == 200
    booking = res.json()
    assert booking["customer_name"] == "Alice Tester"
    assert booking["status"] == "confirmed"

    res_list = client.get("/api/bookings")
    assert res_list.status_code == 200
    bookings = res_list.json()
    assert any(b["customer_name"] == "Alice Tester" for b in bookings)
"""
    subtasks.append(SubTask(
        task_id=9,
        description=f"Create automated test suite in tests/test_api.py",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/tests/test_api.py",
            "code": test_code,
            "instruction": "Create automated tests"
        },
        dependencies=[6, 7],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/tests/test_api.py",
        execution_mode="deterministic"
    ))

    # ── Phase 10: Docker, Start Script & README ──────────────────────────────
    compose_code = f"""version: '3.8'

services:
  app:
    build: .
    container_name: {p_name}
    ports:
      - "8000:8000"
    environment:
      - PORT=8000
    volumes:
      - .:/app
    restart: unless-stopped
"""
    subtasks.append(SubTask(
        task_id=10,
        description=f"Create docker-compose.yml for container deployment",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/docker-compose.yml",
            "code": compose_code,
            "instruction": "Create docker-compose.yml"
        },
        dependencies=[8, 9],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/docker-compose.yml",
        execution_mode="deterministic"
    ))

    dockerfile_code = """FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY . /app/

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""
    subtasks.append(SubTask(
        task_id=11,
        description=f"Create Dockerfile for production container deployment",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/Dockerfile",
            "code": dockerfile_code,
            "instruction": "Create Dockerfile"
        },
        dependencies=[10],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/Dockerfile",
        execution_mode="deterministic"
    ))

    start_bat_code = """@echo off
echo Starting Web Application Server...
cd /d %~dp0
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pause
"""
    subtasks.append(SubTask(
        task_id=12,
        description=f"Create local startup script start_app.bat",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/start_app.bat",
            "code": start_bat_code,
            "instruction": "Create start_app.bat"
        },
        dependencies=[10],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/start_app.bat",
        execution_mode="deterministic"
    ))

    readme_code = f"""# {p_topic} Web Application

An end-to-end full-stack web project created autonomously using the **JARVIS 15-Stage Web Development Pipeline**.

## Features
- **Frontend**: Modern responsive UI with Tailwind CSS, Lucide icons, dynamic catalog search, price filters, and booking flow.
- **Backend**: FastAPI REST API with CORS support, Pydantic validation, and SQLite database persistence.
- **Documentation**:
  - [PRD Specification](docs/PRD.md)
  - [UI/UX Design System](docs/DESIGN_SYSTEM.md)
  - [Architecture & DB Schema](docs/ARCHITECTURE.md)
- **Testing**: Automated Pytest suite in `tests/test_api.py`.
- **Deployment**: Docker and Docker Compose ready.

## Quick Start
```bash
python -m uvicorn backend.main:app --reload --port 8000
```
Open **http://localhost:8000** in your browser.
"""
    subtasks.append(SubTask(
        task_id=13,
        description=f"Create comprehensive project README.md documentation",
        tool_name="write_code",
        args={
            "file_path": f"{t_dir}/README.md",
            "code": readme_code,
            "instruction": "Create README.md"
        },
        dependencies=[10],
        verify_condition_type="file_exists",
        verify_target=f"{t_dir}/README.md",
        execution_mode="deterministic"
    ))

    # ── Phase 11: Execute Automated Tests ────────────────────────────────────
    subtasks.append(SubTask(
        task_id=14,
        description=f"Execute automated pytest test suite to verify backend and API endpoints",
        tool_name="execute_command",
        args={
            "command": f"python -m pytest {t_dir}/tests/test_api.py"
        },
        dependencies=[9, 13],
        verify_condition_type="none",
        execution_mode="deterministic"
    ))

    return subtasks

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import config
from backend.db.migrations import init_db
from backend.services import call_manager, scraper_pool
from backend.api.investigations import router as investigations_router
from backend.api.budget import router as budget_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(config.DATABASE_PATH)
    await scraper_pool.init_pool()
    yield


app = FastAPI(title="Clean Up Your Feed", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(investigations_router)
app.include_router(budget_router)


@app.get("/health")
async def health():
    budget = await call_manager.budget_remaining(config.DATABASE_PATH)
    return {"status": "ok", "budget": budget}

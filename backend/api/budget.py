from fastapi import APIRouter
from backend import config
from backend.services import call_manager

router = APIRouter(tags=["budget"])


@router.get("/budget")
async def get_budget():
    return await call_manager.budget_remaining(config.DATABASE_PATH)

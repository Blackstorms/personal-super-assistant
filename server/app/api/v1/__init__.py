"""API v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    chat,
    checklists,
    experts,
    health,
    knowledge,
    mcp,
    memories,
    scheduled_jobs,
    sessions,
    settings,
    skills,
    tools,
    workspaces,
    fs,
)

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(settings.router, prefix="/settings", tags=["settings"])
router.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
router.include_router(skills.router, prefix="/skills", tags=["skills"])
router.include_router(mcp.router, prefix="/mcp", tags=["mcp"])
router.include_router(tools.router, prefix="/tools", tags=["tools"])
router.include_router(experts.router, prefix="/experts", tags=["experts"])
router.include_router(memories.router, prefix="/memories", tags=["memories"])
router.include_router(fs.router, prefix="/fs", tags=["fs"])
router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
router.include_router(audit.router, prefix="/audit", tags=["audit"])
router.include_router(checklists.router, prefix="/checklists", tags=["checklists"])
router.include_router(scheduled_jobs.router, prefix="/scheduled-jobs", tags=["scheduled-jobs"])

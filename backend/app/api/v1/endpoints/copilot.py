"""Planning copilot endpoints. Read-only: the copilot answers and simulates, people decide."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.all_models import User
from app.services import copilot_service

router = APIRouter(prefix="/copilot", tags=["Copilot"])


class CopilotChatRequest(BaseModel):
    scenario_id: str
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = None


class CopilotChatResponse(BaseModel):
    conversation_id: str
    reply: str
    steps: List[Dict[str, Any]]
    stop_reason: Optional[str]
    model: Optional[str]


@router.get("/status")
def status(current_user: User = Depends(get_current_user)):
    return {
        "configured": copilot_service.is_configured(),
        "provider": copilot_service.provider(),
        "model": copilot_service.model_name(),
    }


@router.post("/chat", response_model=CopilotChatResponse)
def chat(payload: CopilotChatRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return copilot_service.chat(db, current_user, payload.scenario_id, payload.message.strip(), payload.conversation_id)

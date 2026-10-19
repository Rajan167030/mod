"""Object explorer and link graph over a scenario. Read-only."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.all_models import User
from app.services import ontology_service

router = APIRouter(prefix="/ontology", tags=["Object explorer"])


@router.get("/{scenario_id}/search")
def search(
    scenario_id: str,
    q: str = Query("", max_length=100),
    type: Optional[str] = Query(None, pattern="^(aircraft|task|site|capability)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    return ontology_service.search(db, scenario_id, q, type)


@router.get("/{scenario_id}/objects/{kind}/{object_id}")
def get_object(
    scenario_id: str, kind: str, object_id: str,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return ontology_service.profile(db, scenario_id, kind, object_id)


@router.get("/{scenario_id}/graph")
def get_graph(
    scenario_id: str,
    capabilities: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return ontology_service.graph(db, scenario_id, capabilities)

from typing import List, Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.all_models import Resource, Scenario, User
from app.core.permissions import UserRole
from app.core.errors import NotFoundError
from app.api.deps import get_current_user, require_roles
from app.services.audit_service import log_audit_event
from app.schemas.all_schemas import (
    ResourceCreate, ResourceUpdate, ResourceResponse
)

router = APIRouter(prefix="/resources", tags=["Resources"])


@router.get("", response_model=List[ResourceResponse])
def list_resources(
    scenario_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List operational resources with optional scenario and type filters."""
    query = db.query(Resource)
    if scenario_id:
        query = query.filter(Resource.scenario_id == scenario_id)
    if resource_type:
        query = query.filter(Resource.resource_type == resource_type)
    if status:
        query = query.filter(Resource.status == status)
    return query.order_by(Resource.name.asc()).all()


@router.post("", response_model=ResourceResponse, status_code=status.HTTP_201_CREATED)
def create_resource(
    payload: ResourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """Register a new operational resource."""
    if not db.query(Scenario).filter(Scenario.id == payload.scenario_id).first():
        raise NotFoundError("Scenario", payload.scenario_id)
    resource = Resource(
        scenario_id=payload.scenario_id,
        name=payload.name,
        resource_type=payload.resource_type,
        status=payload.status,
        metadata_json=payload.metadata_json or {}
    )
    db.add(resource)
    db.flush()

    log_audit_event(
        db,
        action="RESOURCE_CREATED",
        entity_type="RESOURCE",
        entity_id=resource.id,
        actor=current_user,
        metadata={"name": resource.name, "type": resource.resource_type}
    )
    db.commit()
    db.refresh(resource)
    return resource


@router.get("/{resource_id}", response_model=ResourceResponse)
def get_resource(
    resource_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get single resource by ID."""
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise NotFoundError("Resource", resource_id)
    return resource


@router.patch("/{resource_id}", response_model=ResourceResponse)
def update_resource(
    resource_id: str,
    payload: ResourceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """Update resource parameters or availability status."""
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise NotFoundError("Resource", resource_id)

    update_data = payload.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(resource, k, v)

    log_audit_event(
        db,
        action="RESOURCE_UPDATED",
        entity_type="RESOURCE",
        entity_id=resource.id,
        actor=current_user,
        metadata=update_data
    )
    db.commit()
    db.refresh(resource)
    return resource


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resource(
    resource_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """Safely remove a resource if not assigned to active tasks."""
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise NotFoundError("Resource", resource_id)

    log_audit_event(
        db,
        action="RESOURCE_DELETED",
        entity_type="RESOURCE",
        entity_id=resource.id,
        actor=current_user,
        metadata={"name": resource.name}
    )
    db.delete(resource)
    db.commit()
    return None

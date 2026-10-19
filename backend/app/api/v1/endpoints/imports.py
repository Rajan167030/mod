"""Bulk import of aircraft, tasks, maintenance and sites from CSV or Excel. Preview first, then commit."""
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.errors import ValidationError
from app.core.permissions import UserRole
from app.db.session import get_db
from app.models.all_models import User
from app.services import import_service

router = APIRouter(prefix="/imports", tags=["Data import"])
MAX_BYTES = 5 * 1024 * 1024


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise ValidationError("Files are limited to 5 MB.")
    return data


@router.get("/templates/{kind}", response_class=PlainTextResponse)
def template(kind: str):
    if kind not in import_service.TEMPLATES:
        raise ValidationError(f"kind must be one of {', '.join(import_service.KINDS)}")
    return PlainTextResponse(
        import_service.TEMPLATES[kind],
        headers={"Content-Disposition": f'attachment; filename="airops-{kind}-template.csv"'},
    )


@router.post("/{scenario_id}/{kind}/preview")
async def preview(
    scenario_id: str,
    kind: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    return import_service.analyse(db, scenario_id, kind, file.filename or "", await _read(file))


@router.post("/{scenario_id}/{kind}/commit")
async def commit(
    scenario_id: str,
    kind: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    return import_service.commit(db, scenario_id, kind, file.filename or "", await _read(file), user)

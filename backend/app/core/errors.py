from fastapi import HTTPException, status


class AppError(HTTPException):
    def __init__(self, status_code: int, detail: str, error_code: str = "GENERIC_ERROR"):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code


class NotFoundError(AppError):
    def __init__(self, entity: str, identifier: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{entity} with id '{identifier}' not found.",
            error_code=f"{entity.upper()}_NOT_FOUND"
        )


class PermissionDeniedError(AppError):
    def __init__(self, action: str = "perform this action"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not possess the required authorization to {action}.",
            error_code="PERMISSION_DENIED"
        )


class VersionConflictError(AppError):
    def __init__(self, detail: str = "Schedule version conflict or stale proposal detected."):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            error_code="VERSION_CONFLICT"
        )


class ValidationError(AppError):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
            error_code="VALIDATION_FAILED"
        )

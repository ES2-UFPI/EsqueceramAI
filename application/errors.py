class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, details: dict | None = None):
        super().__init__(message)
        self.message, self.status, self.details = message, status, details


def not_found(entity="Registro"):
    return ApiError(f"{entity} não encontrado.", 404)


def forbidden(message="Você não tem permissão para esta ação."):
    return ApiError(message, 403)


def unauthorized(message="Faça login para continuar."):
    return ApiError(message, 401)


class ValidationFailed(ApiError):
    """Equivale ao ZodError: 422 com `details` por campo."""
    def __init__(self, details: dict):
        super().__init__("Confira os campos do formulário.", 422, details)

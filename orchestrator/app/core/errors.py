"""The API error type. Handlers render every failure as {error:{code,message,request_id}}."""


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def unauthorized(message: str = "Authentication is required.", code: str = "UNAUTHENTICATED") -> ApiError:
    return ApiError(401, code, message, {"WWW-Authenticate": "Bearer"})


def forbidden(message: str = "You do not have permission to do this.") -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError(404, "NOT_FOUND", message)

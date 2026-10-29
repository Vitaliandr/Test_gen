#свои ошибки, дальше в http


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(AppError):
    status_code = 404


class LlmError(AppError):
    status_code = 502


class CostLimit(LlmError):
    status_code = 402

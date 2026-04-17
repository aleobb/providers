class EdenorError(Exception):
    def __init__(self, message: str, context: dict | None = None):
        super().__init__(message)
        self.context = context or {}


class ConfigurationError(EdenorError):
    pass


class LoginError(EdenorError):
    pass


class CaptchaError(LoginError):
    pass


class AccountLockedError(LoginError):
    pass


class NavigationError(EdenorError):
    pass


class InvoiceNotFoundError(EdenorError):
    pass


class DownloadError(EdenorError):
    pass

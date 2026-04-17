class MetrogasError(Exception):
    def __init__(self, message: str, context: dict | None = None):
        super().__init__(message)
        self.context = context or {}


class ConfigurationError(MetrogasError):
    pass


class LoginError(MetrogasError):
    pass


class NavigationError(MetrogasError):
    pass


class InvoiceNotFoundError(MetrogasError):
    pass


class DownloadError(MetrogasError):
    pass

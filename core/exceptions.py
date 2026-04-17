class InvoiceDownloaderError(Exception):
    def __init__(self, message: str, context: dict | None = None):
        super().__init__(message)
        self.context = context or {}


class ConfigurationError(InvoiceDownloaderError):
    pass


class LoginError(InvoiceDownloaderError):
    pass


class CaptchaError(LoginError):
    pass


class AccountLockedError(LoginError):
    pass


class NavigationError(InvoiceDownloaderError):
    pass


class InvoiceNotFoundError(InvoiceDownloaderError):
    pass


class DownloadError(InvoiceDownloaderError):
    pass


class ServerUnavailableError(InvoiceDownloaderError):
    """El servidor del proveedor devolvió un error transitorio (HTTP 500/503,
    'intente más tarde', 'error inesperado', etc.). El script debe registrarlo
    en el log y continuar con el siguiente proveedor/cuenta."""
    pass

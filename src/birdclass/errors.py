class BirdClassError(Exception):
    """可向 UI 展示的受控错误。"""


class ConfigError(BirdClassError):
    pass


class ApiAuthenticationError(BirdClassError):
    pass


class ApiRateLimitError(BirdClassError):
    pass


class ApiQuotaError(BirdClassError):
    pass


class ApiTransportError(BirdClassError):
    pass


class ApiProtocolError(BirdClassError):
    pass


class ImageValidationError(BirdClassError):
    pass


class ImagePreparationError(BirdClassError):
    pass


class RecognitionFailedError(BirdClassError):
    pass


class SpeciesNotFoundError(RecognitionFailedError):
    pass


class RecognitionTimeoutError(RecognitionFailedError):
    pass


class HistoryError(BirdClassError):
    pass


class ArchiveError(BirdClassError):
    pass

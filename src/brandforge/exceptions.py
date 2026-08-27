class BrandForgeError(Exception):
    """Base error for expected domain failures."""


class NotFoundError(BrandForgeError):
    pass


class TenantIsolationError(BrandForgeError):
    pass


class InvalidTransitionError(BrandForgeError):
    pass


class ConcurrencyError(BrandForgeError):
    pass


class ValidationError(BrandForgeError):
    pass


class SecurityError(BrandForgeError):
    pass


class BudgetExceededError(BrandForgeError):
    pass

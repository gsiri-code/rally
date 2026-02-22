from __future__ import annotations


class PlannerError(Exception):
    pass


class PlannerConfigurationError(PlannerError):
    pass


class PlannerGenerationError(PlannerError):
    pass


class PlannerValidationError(PlannerError):
    pass

from __future__ import annotations


class DomainError(Exception):
    code = "upstream_error"
    status_code = 502

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationDomainError(DomainError):
    code = "bad_request"
    status_code = 400


class NotFoundDomainError(DomainError):
    code = "not_found"
    status_code = 404


class UpstreamDomainError(DomainError):
    code = "upstream_error"
    status_code = 502


class CacheDomainError(DomainError):
    code = "cache_error"
    status_code = 502


class RepositoryDomainError(DomainError):
    code = "repository_error"
    status_code = 502


class PayloadTooLargeDomainError(DomainError):
    code = "payload_too_large"
    status_code = 413

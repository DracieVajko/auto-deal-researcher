"""Product domain profiles and their detection order."""

from src.output.domains.base import DomainProfile
from src.output.domains.generic import GENERIC
from src.output.domains.registry import DOMAIN_REGISTRY, detect, get

__all__ = ["DOMAIN_REGISTRY", "GENERIC", "DomainProfile", "detect", "get"]

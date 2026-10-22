"""Validated tenant/user context for the next API boundary.

This module is intentionally isolated: Block 4 defines the contract before it is
wired into FastAPI dependencies or authentication.  Headers are identity hints,
not proof of identity; a later auth layer must establish and compare them with
the authenticated principal.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Scope in which a request may read or write application data."""

    tenant_id: str
    user_id: str

    @classmethod
    def from_headers(cls, tenant_id: str | None, user_id: str | None) -> "TenantContext":
        """Build a context from the planned ``X-*`` headers.

        Empty, oversized, or delimiter-bearing values are rejected so they cannot
        silently become Qdrant filters, storage paths, or log fields.  This does
        not authenticate either value.
        """

        return cls(
            tenant_id=_validate_identifier("X-Tenant-ID", tenant_id),
            user_id=_validate_identifier("X-User-ID", user_id),
        )


def _validate_identifier(header_name: str, value: str | None) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{header_name} es obligatorio.")
    normalized = value.strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{header_name} tiene un formato inválido.")
    return normalized


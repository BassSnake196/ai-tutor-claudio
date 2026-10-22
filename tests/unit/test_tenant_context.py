import pytest

from app.core.tenant_context import TenantContext


def test_context_normalizes_safe_header_values() -> None:
    context = TenantContext.from_headers("  school-01 ", "teacher.alma")

    assert context.tenant_id == "school-01"
    assert context.user_id == "teacher.alma"


@pytest.mark.parametrize(
    ("tenant_id", "user_id"),
    [
        (None, "teacher"),
        ("school", None),
        ("", "teacher"),
        ("school/other", "teacher"),
        ("school", "teacher\\other"),
        ("x" * 129, "teacher"),
    ],
)
def test_context_rejects_missing_or_unsafe_values(tenant_id: str | None, user_id: str | None) -> None:
    with pytest.raises(ValueError, match="obligatorio|formato inválido"):
        TenantContext.from_headers(tenant_id, user_id)


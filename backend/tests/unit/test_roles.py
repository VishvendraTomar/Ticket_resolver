from __future__ import annotations

import pytest

from app.tenancy.roles import Role, can_assign_role, can_manage_members


@pytest.mark.parametrize("role", list(Role))
def test_only_owner_and_admin_manage_members(role: Role) -> None:
    assert can_manage_members(role) is (role in {Role.OWNER, Role.ADMIN})


@pytest.mark.parametrize("target", list(Role))
def test_owner_can_assign_anything(target: Role) -> None:
    assert can_assign_role(Role.OWNER, target)


@pytest.mark.parametrize("target", list(Role))
def test_admin_can_assign_anything_but_owner(target: Role) -> None:
    assert can_assign_role(Role.ADMIN, target) is (target is not Role.OWNER)


@pytest.mark.parametrize("actor", [r for r in Role if r not in {Role.OWNER, Role.ADMIN}])
def test_others_assign_nothing(actor: Role) -> None:
    assert not any(can_assign_role(actor, t) for t in Role)

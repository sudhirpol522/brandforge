from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request, status

from brandforge.config import Settings
from brandforge.workflow import BrandForgeWorkflow

from .schemas import TenantContext


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_workflow(request: Request) -> BrandForgeWorkflow:
    return cast(BrandForgeWorkflow, request.app.state.workflow)


def tenant_context(
    request: Request,
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_role: Annotated[str | None, Header()] = None,
) -> TenantContext:
    settings: Settings = request.app.state.settings
    if settings.dev_auth:
        tenant_id = x_tenant_id or settings.default_tenant
        user_id = x_user_id or settings.default_user
        role = x_user_role or "campaign_owner"
    else:
        # Production replaces this boundary with validated OIDC claims at the gateway or here.
        if not x_tenant_id or not x_user_id or not x_user_role:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="validated identity headers are required",
            )
        tenant_id, user_id, role = x_tenant_id, x_user_id, x_user_role
    try:
        return TenantContext(tenant_id=tenant_id, user_id=user_id, role=role)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


Tenant = Annotated[TenantContext, Depends(tenant_context)]
Workflow = Annotated[BrandForgeWorkflow, Depends(get_workflow)]

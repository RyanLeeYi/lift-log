from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import require_domain_auth
from app.schemas import McpTokenCreateIn, McpTokenCreateOut, McpTokenOut
from app.services import mcp_tokens as svc

router = APIRouter(
    prefix="/api/mcp-tokens",
    tags=["mcp-tokens"],
    dependencies=[Depends(require_domain_auth)],
)


def _user_id(request: Request) -> str:
    """legacy 單一 token 沒有 user 身分，不能管理 MCP token（F147）。"""
    scope = request.state.domain_scope
    if scope == "legacy":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return scope


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_mcp_token(data: McpTokenCreateIn, request: Request) -> McpTokenCreateOut:
    """明文只在這次回應出現——之後 GET 列表與 DB 都只有 hash。"""
    user_id = _user_id(request)
    with request.app.state.control_session_factory() as control:
        token, plaintext = svc.create_token(control, user_id, data.name)
        return McpTokenCreateOut(
            id=token.id, name=token.name, token=plaintext, created_at=token.created_at
        )


@router.get("/")
def list_mcp_tokens(request: Request) -> list[McpTokenOut]:
    user_id = _user_id(request)
    with request.app.state.control_session_factory() as control:
        return [McpTokenOut.model_validate(row) for row in svc.list_tokens(control, user_id)]


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_mcp_token(token_id: str, request: Request) -> None:
    user_id = _user_id(request)
    with request.app.state.control_session_factory() as control:
        svc.revoke_token(control, user_id, token_id)

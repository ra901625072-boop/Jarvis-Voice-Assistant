from fastapi import HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from container import ServiceContainer

security_scheme = HTTPBearer()

def get_security_manager():
    container = ServiceContainer.instance()
    if container:
        return container.get("security")
    from modules.core.security_manager import SecurityManager
    return SecurityManager()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security_scheme),
    security_mgr = Depends(get_security_manager)
) -> dict:
    token = credentials.credentials
    try:
        payload = security_mgr.verify_jwt(token)
        return payload
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=401, detail="Authentication failed")

def require_role(allowed_roles: list):
    def dependency(current_user: dict = Depends(get_current_user)):
        role = current_user.get("role", "user")
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Permission denied")
        return current_user
    return dependency

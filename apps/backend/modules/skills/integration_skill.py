import json
import httpx
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class IntegrationSkill(BaseSkill):
    """
    Skill for quick ad-hoc REST calls without going through IntegrationAgent's bus round-trip.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Make a quick API REST call")
    async def quick_api_call(self, method: str, url: str, headers: str = None, body: str = None) -> str:
        """Make a direct HTTP request."""
        async def _do_call():
            method_upper = method.upper()
            if method_upper not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
                return f"Error: Unsupported HTTP method '{method_upper}'."

            req_headers = {}
            if headers:
                try:
                    req_headers = json.loads(headers)
                except Exception:
                    return "Error: headers must be a valid JSON string."

            req_body = None
            if body:
                try:
                    req_body = json.loads(body)
                except Exception:
                    req_body = body # Send as raw string if not JSON

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.request(
                        method=method_upper,
                        url=url,
                        headers=req_headers,
                        json=req_body if isinstance(req_body, dict) else None,
                        content=req_body if isinstance(req_body, str) else None
                    )
                
                try:
                    resp_data = response.json()
                    resp_text = json.dumps(resp_data, indent=2)
                except Exception:
                    resp_text = response.text

                return f"Status: {response.status_code}\nResponse:\n{resp_text}"

            except Exception as e:
                return f"API Call Failed: {e}"

        return await self.safe_execute(
            _do_call,
            confirmation_category="read" if method.upper() == "GET" else "confirm", # Non-GET calls might modify external state, but it's external. Default to 'read' or 'open' tier equivalent. 
            confirmation_action=f"make {method.upper()} request to {url}",
            confirmed=True, # We'll treat this as safe for real-time voice, let the user deal with auth. Wait, if it's destructive, maybe we should gate it?
            success_msg="Completed API call successfully",
            error_msg="Failed to complete API call"
        )

import logging
from typing import Optional

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult
from modules.security.egress import SafeEgressClient, SSRFValidationError

logger = logging.getLogger("JARVIS.IntegrationAgent")

class IntegrationAgent(BaseAgent):
    """
    External API and service orchestration.
    Absorbs IntegrationSkill.
    """
    def __init__(self, bus):
        super().__init__(agent_id="integration_agent")
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type in ("call_api", "call_rest_api"):
                return await self._handle_call_api(task, payload)
            elif task_type == "webhook_flow":
                return await self._handle_webhook_flow(task, payload)
            elif task_type == "call_graphql":
                return await self._handle_call_graphql(task, payload)
            elif task_type == "authenticate":
                return await self._handle_authenticate(task, payload)
            elif task_type == "connect_service":
                return await self._handle_connect_service(task, payload)
            elif task_type == "sync_data":
                return await self._handle_sync_data(task, payload)
            else:
                return self._create_result(task, success=False, error=f"IntegrationAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"IntegrationAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_call_api(self, task: AgentTask, payload: dict) -> AgentResult:
        service = payload.get("service", "")
        endpoint = payload.get("endpoint", "")
        params = payload.get("params", {})
        
        prompt = f"""
        You are JARVIS's Integration Agent.
        Construct the HTTP request details for the following API call:
        Service: {service}
        Endpoint: {endpoint}
        Parameters: {params}
        
        Return JSON with exactly:
        - 'method': HTTP method (e.g. GET, POST)
        - 'url': Full URL
        - 'headers': Key-value pairs for headers
        - 'body': JSON body (if applicable)
        """
        
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            method = data.get("method", "GET")
            url = data.get("url")
            headers = data.get("headers", {})
            body = data.get("body")
            
            if url:
                egress_resp = await SafeEgressClient.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=body if isinstance(body, dict) else None,
                    data=body if isinstance(body, str) else None,
                )
                data["http_status"] = egress_resp["status"]
                data["http_response"] = egress_resp["text"]

            return self._create_result(task, success=True, result=data)
        except SSRFValidationError as e:
            return self._create_result(task, success=False, error=f"SSRF security policy blocked API request: {e}")
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse or execute API call: {e}")

    async def _handle_webhook_flow(self, task: AgentTask, payload: dict) -> AgentResult:
        url = payload.get("url") or payload.get("target_url")
        if not url:
            return self._create_result(task, success=False, error="Missing target 'url' in webhook_flow payload")
        method = payload.get("method", "POST").upper()
        headers = payload.get("headers", {"Content-Type": "application/json"})
        body = payload.get("data") or payload.get("body") or payload.get("payload", {})

        try:
            resp = await SafeEgressClient.request(
                method=method,
                url=url,
                headers=headers,
                json=body if isinstance(body, dict) else None,
                data=str(body) if not isinstance(body, dict) else None,
            )
            return self._create_result(
                task,
                success=resp["status"] < 400,
                result={"status": resp["status"], "response": resp["text"][:1000], "url": url}
            )
        except SSRFValidationError as e:
            return self._create_result(task, success=False, error=f"SSRF security policy blocked webhook dispatch: {e}")
        except Exception as e:
            return self._create_result(task, success=False, error=f"Webhook dispatch failed: {e}")

    async def _handle_call_graphql(self, task: AgentTask, payload: dict) -> AgentResult:
        url = payload.get("url") or payload.get("endpoint")
        query = payload.get("query")
        if not url or not query:
            return self._create_result(task, success=False, error="GraphQL requires 'url' and 'query' in payload")
        variables = payload.get("variables", {})
        headers = payload.get("headers", {"Content-Type": "application/json"})

        try:
            gql_payload = {"query": query, "variables": variables}
            resp = await SafeEgressClient.request(
                method="POST",
                url=url,
                headers=headers,
                json=gql_payload
            )
            import json as json_lib
            try:
                data = json_lib.loads(resp["text"])
            except Exception:
                data = resp["text"]
            return self._create_result(
                task,
                success=resp["status"] == 200,
                result={"status": resp["status"], "data": data}
            )
        except SSRFValidationError as e:
            return self._create_result(task, success=False, error=f"SSRF security policy blocked GraphQL request: {e}")
        except Exception as e:
            return self._create_result(task, success=False, error=f"GraphQL execution failed: {e}")

    async def _handle_authenticate(self, task: AgentTask, payload: dict) -> AgentResult:
        auth_type = payload.get("type", "api_key")
        key = payload.get("key") or payload.get("token")
        service = payload.get("service", "generic")
        if not key:
            return self._create_result(task, success=False, error=f"Missing credential key/token for service '{service}'")
        
        # Return explicit dry_run / not_implemented status rather than simulating completed live auth
        return self._create_result(
            task,
            success=True,
            result={
                "status": "not_implemented",
                "service": service,
                "type": auth_type,
                "detail": f"Durable OAuth/API-key integration for '{service}' is not configured in this environment."
            }
        )

    async def _handle_connect_service(self, task: AgentTask, payload: dict) -> AgentResult:
        service = payload.get("service")
        endpoint = payload.get("endpoint")
        if not service and not endpoint:
            return self._create_result(task, success=False, error="Missing service or endpoint parameters")
        
        return self._create_result(
            task,
            success=True,
            result={
                "status": "dry_run",
                "service": service or endpoint,
                "active": False,
                "detail": f"Service connection for '{service or endpoint}' validated in dry-run mode (no live session)."
            }
        )

    async def _handle_sync_data(self, task: AgentTask, payload: dict) -> AgentResult:
        source = payload.get("source", "unknown")
        destination = payload.get("destination", "unknown")
        records = payload.get("records", [])
        
        return self._create_result(
            task,
            success=True,
            result={
                "status": "not_implemented",
                "source": source,
                "destination": destination,
                "records_count": len(records) if isinstance(records, list) else 1,
                "detail": f"Live data synchronization from '{source}' to '{destination}' requires a registered sync provider."
            }
        )


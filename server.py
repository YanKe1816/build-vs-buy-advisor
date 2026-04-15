#!/usr/bin/env python3
"""Minimal deterministic MCP Task App backend for Build vs Buy Advisor.

Endpoints:
- GET /health
- POST /mcp
- GET /privacy
- GET /terms
- GET /support
- GET /.well-known/openai-apps-challenge

No external dependencies.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Tuple

TOOL_NAME = "build_vs_buy_advisor"
TOOL_DESCRIPTION = (
    "Decide whether a team should build in-house or buy a third-party solution."
)


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, status: int, text: str) -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def evaluate_build_vs_buy(
    deadline_days: float,
    is_core_competency: bool,
    handles_sensitive_data: bool,
    is_mvp: bool,
) -> Dict[str, str]:
    """Apply deterministic decision rules."""
    if deadline_days <= 14 and is_mvp and not is_core_competency:
        return {
            "decision": "buy",
            "reason": "Short deadline and MVP focus with non-core capability favor faster third-party adoption.",
            "next_step": "Shortlist vendors, run a rapid proof of concept, and negotiate terms.",
        }

    if is_core_competency or handles_sensitive_data:
        return {
            "decision": "build",
            "reason": "Core differentiation or sensitive data handling favors in-house control and customization.",
            "next_step": "Define architecture, security requirements, and a phased internal implementation plan.",
        }

    return {
        "decision": "buy",
        "reason": "No strong strategic or compliance driver to build, so buying reduces time and delivery risk.",
        "next_step": "Evaluate top vendors and integrate the best-fit solution.",
    }


def _validate_arguments(arguments: Any) -> Tuple[bool, Dict[str, Any], str]:
    if not isinstance(arguments, dict):
        return False, {}, "arguments must be an object"

    required = [
        "deadline_days",
        "is_core_competency",
        "handles_sensitive_data",
        "is_mvp",
    ]

    for key in required:
        if key not in arguments:
            return False, {}, f"missing required field: {key}"

    deadline_days = arguments["deadline_days"]
    is_core_competency = arguments["is_core_competency"]
    handles_sensitive_data = arguments["handles_sensitive_data"]
    is_mvp = arguments["is_mvp"]

    if not isinstance(deadline_days, (int, float)) or isinstance(deadline_days, bool):
        return False, {}, "deadline_days must be a number"
    if not isinstance(is_core_competency, bool):
        return False, {}, "is_core_competency must be a boolean"
    if not isinstance(handles_sensitive_data, bool):
        return False, {}, "handles_sensitive_data must be a boolean"
    if not isinstance(is_mvp, bool):
        return False, {}, "is_mvp must be a boolean"

    normalized = {
        "deadline_days": float(deadline_days),
        "is_core_competency": is_core_competency,
        "handles_sensitive_data": handles_sensitive_data,
        "is_mvp": is_mvp,
    }
    return True, normalized, ""


def _mcp_tool_schema() -> Dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "deadline_days": {"type": "number"},
                "is_core_competency": {"type": "boolean"},
                "handles_sensitive_data": {"type": "boolean"},
                "is_mvp": {"type": "boolean"},
            },
            "required": [
                "deadline_days",
                "is_core_competency",
                "handles_sensitive_data",
                "is_mvp",
            ],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string"},
                "reason": {"type": "string"},
                "next_step": {"type": "string"},
            },
            "required": ["decision", "reason", "next_step"],
            "additionalProperties": False,
        },
    }


def _jsonrpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _handle_mcp_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params", {})

    if payload.get("jsonrpc") != "2.0":
        return _jsonrpc_error(request_id, -32600, "Invalid Request")
    if not isinstance(method, str):
        return _jsonrpc_error(request_id, -32600, "Invalid Request")
    if not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32602, "Invalid params")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "build-vs-buy-advisor", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [_mcp_tool_schema()]}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments")
        if name != TOOL_NAME:
            return _jsonrpc_error(request_id, -32602, f"Unknown tool: {name}")

        ok, normalized, error = _validate_arguments(arguments)
        if not ok:
            return _jsonrpc_error(request_id, -32602, error)

        result = evaluate_build_vs_buy(**normalized)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Decision: {result['decision']}\n\n"
                            f"Reason: {result['reason']}\n\n"
                            f"Next step: {result['next_step']}"
                        ),
                    }
                ],
                "structuredContent": result,
            },
        }

    return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            _json_response(self, 200, {"ok": True})
            return

        if self.path == "/.well-known/openai-apps-challenge":
            token = os.getenv("OPENAI_APPS_CHALLENGE", "")
            _text_response(self, 200, token)
            return

        if self.path == "/privacy":
            _text_response(self, 200, "Privacy: This deterministic tool does not store personal data.")
            return

        if self.path == "/terms":
            _text_response(self, 200, "Terms: Provided as-is for build-vs-buy advisory judgments.")
            return

        if self.path == "/support":
            _text_response(self, 200, "Support: Contact your platform administrator for assistance.")
            return

        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/mcp":
            _json_response(self, 404, {"error": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            _json_response(self, 400, {"error": "invalid content length"})
            return

        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _json_response(self, 400, {"error": "invalid json"})
            return

        if not isinstance(payload, dict):
            _json_response(self, 400, {"error": "request body must be an object"})
            return

        response = _handle_mcp_payload(payload)
        _json_response(self, 200, response)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep output deterministic/minimal for hosted environments.
        return


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

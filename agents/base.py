"""
Shared constants, DB helpers, and client factory used by all agents.
Uses Ollama for local LLM inference — no API key required.
"""
import json
import sqlite3
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# ── Paths ─────────────────────────────────────────────────────────────────────
AGENTS_DIR   = Path(__file__).parent
PROJECT_DIR  = AGENTS_DIR.parent
DB_PATH      = str(PROJECT_DIR / "data" / "bets.db")

# Load API keys from api/.env (ODDS_API_KEY etc.)
load_dotenv(PROJECT_DIR / "api" / ".env")

# ── Ollama config ─────────────────────────────────────────────────────────────
OLLAMA_BASE  = "http://localhost:11434"
MODEL        = "llama3.1"   # single model for all agents


# ── Ollama client ─────────────────────────────────────────────────────────────

class OllamaClient:
    """Minimal Ollama client with tool-use support via the /api/chat endpoint."""

    def __init__(self, base_url: str = OLLAMA_BASE):
        self.base_url = base_url

    def chat(
        self,
        messages:    list[dict],
        tools:       list[dict] | None = None,
        system:      str        | None = None,
        max_tokens:  int               = 4096,
    ) -> dict:
        """Send a chat request to Ollama and return the full response dict."""
        payload: dict[str, Any] = {
            "model":  MODEL,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }

        # Prepend system message if provided
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        payload["messages"] = full_messages

        if tools:
            payload["tools"] = tools

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()


def get_client() -> OllamaClient:
    """Return an Ollama client."""
    return OllamaClient()


def get_db_conn() -> sqlite3.Connection:
    """Open and return a SQLite connection to the bets database."""
    return sqlite3.connect(DB_PATH)


# ── Tool-use agentic loop ─────────────────────────────────────────────────────

def run_agent(
    client:     OllamaClient,
    system:     str,
    user_msg:   str,
    tools:      list[dict],
    tool_fns:   dict[str, Any],
    max_tokens: int = 4096,
    max_rounds: int = 10,
) -> str:
    """
    Agentic loop: keep calling Ollama until it produces a final text response
    with no pending tool calls.

    Args:
        client:     OllamaClient instance
        system:     System prompt string
        user_msg:   Initial user message
        tools:      List of tool definitions in Ollama/OpenAI format
        tool_fns:   Dict mapping tool name → callable Python function
        max_tokens: Max tokens per Ollama call
        max_rounds: Safety cap on tool-call iterations

    Returns:
        Final text response from the model.
    """
    messages = [{"role": "user", "content": user_msg}]

    for _ in range(max_rounds):
        response  = client.chat(messages=messages, tools=tools,
                                system=system, max_tokens=max_tokens)
        msg       = response.get("message", {})
        tool_calls = msg.get("tool_calls", [])

        if not tool_calls:
            # No more tool calls — return the final text
            return msg.get("content", "")

        # Append the assistant turn (with tool calls)
        messages.append({"role": "assistant", "content": msg.get("content", ""),
                         "tool_calls": tool_calls})

        # Execute each tool call and append the results
        for tc in tool_calls:
            fn_name = tc.get("function", {}).get("name")
            raw_args = tc.get("function", {}).get("arguments", {})

            # Ollama may return arguments as a JSON string or already a dict
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}
            else:
                args = raw_args

            if fn_name in tool_fns:
                try:
                    result = tool_fns[fn_name](**args)
                except Exception as exc:
                    result = json.dumps({"error": str(exc)})
            else:
                result = json.dumps({"error": f"Unknown tool: {fn_name}"})

            messages.append({
                "role":    "tool",
                "content": result if isinstance(result, str) else json.dumps(result),
            })

    return "Max tool-call rounds reached without a final response."

import os
import uuid
import httpx
import gradio as gr

A2A_URL = os.getenv("A2A_URL", "https://flight-booking-agent-bq9s.onrender.com/")
REQUEST_TIMEOUT = int(os.getenv("A2A_TIMEOUT", "60"))

STATE_MAP = {
    "completed": "completed",
    "input-required": "input-required",
    "failed": "failed",
    "canceled": "canceled",
    "working": "working",
}

_session_ctx: dict[str, str] = {}


def respond(message: str, history: list, broker_url: str, request: gr.Request):
    url = (broker_url or A2A_URL).strip().rstrip("/") + "/"
    session_key = str(request.session_hash) if request else "default"
    context_id = _session_ctx.get(session_key, "")

    # A2A v0.3 classic JSON-RPC
    payload = {
        "jsonrpc": "2.0",
        "id": f"req-{uuid.uuid4().hex[:8]}",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": uuid.uuid4().hex,
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
                **({"contextId": context_id} if context_id else {}),
            }
        },
    }

    try:
        resp = httpx.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        return "Request timed out — the agent may be cold-starting on Render. Wait ~30s and retry."
    except Exception as e:
        return f"Error: {e}"

    if "error" in data:
        err = data["error"]
        return f"Agent error {err.get('code')}: {err.get('message')}"

    result = data.get("result", {})

    new_ctx = result.get("contextId") or result.get("status", {}).get("contextId")
    if new_ctx:
        _session_ctx[session_key] = new_ctx

    state = STATE_MAP.get(result.get("status", {}).get("state", "unknown"), "unknown")

    status_text = _extract_text(result.get("status", {}).get("message", {}).get("parts", []))
    artifact_text = "".join(
        _extract_text(a.get("parts", [])) for a in result.get("artifacts", [])
    )

    body = artifact_text or status_text or f"(state: {state}, no text returned)"

    if state == "input-required":
        body = f"**Agent needs more info:**\n\n{body}"
    elif state == "failed":
        body = f"**Agent failed:**\n\n{body}"
    elif state not in ("completed", "unknown"):
        body = f"*State: {state}*\n\n{body}"

    return body


def _extract_text(parts: list) -> str:
    return "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()


broker_input = gr.Textbox(
    value=A2A_URL,
    label="Agent URL",
    placeholder="https://your-agent-url/",
)

demo = gr.ChatInterface(
    fn=respond,
    title="Flight Booking Agent",
    description="Governed corporate flight booking demo — search and book flights via an A2A agent.",
    additional_inputs=[broker_input],
    additional_inputs_accordion=gr.Accordion("⚙️ Settings", open=True),
    examples=[
        ["What flights are there from SFO to JFK?", A2A_URL],
        ["Find me a business class flight from JFK to London.", A2A_URL],
        ["Book the morning flight from SFO to JFK for John Smith.", A2A_URL],
        ["Book me on AF250 to London tonight.", A2A_URL],
    ],
    chatbot=gr.Chatbot(height=480),
)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port, share=False)

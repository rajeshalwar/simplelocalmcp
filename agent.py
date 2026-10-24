"""A tiny agent: a local Ollama model that can call the tools in server.py.

    python agent.py              # with tools
    python agent.py --no-tools   # same model, no tools: watch it guess
"""
import asyncio
import json
import os
import sys

import ollama
from mcp import Client, StdioServerParameters

MODEL = os.environ.get("MODEL", "qwen2.5:7b")
SYSTEM = ("You are a solar assistant for Texas homeowners. Never guess numbers: "
          "get every figure from a tool, then explain it in plain English.")

CYAN, DIM, RESET = ("\033[36m", "\033[2m", "\033[0m") if sys.stdout.isatty() else ("", "", "")


async def main(use_tools: bool) -> None:
    # 1. Start the MCP server as a subprocess and connect to it over stdio.
    server_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
    server = StdioServerParameters(command=sys.executable, args=[server_py])
    async with Client(server) as mcp:

        # 2. Ask the server what tools it has, and describe them to the model.
        tools = [{"type": "function",
                  "function": {"name": t.name,
                               "description": t.description,
                               "parameters": t.input_schema}}
                 for t in (await mcp.list_tools()).tools] if use_tools else []
        print(f"{DIM}model: {MODEL} · tools: {[t['function']['name'] for t in tools]}{RESET}")

        messages = [{"role": "system", "content": SYSTEM}]
        while True:
            try:
                question = input("\nyou › ")
            except (EOFError, KeyboardInterrupt):
                return
            messages.append({"role": "user", "content": question})

            # 3. The agent loop: let the model call tools until it answers.
            while True:
                reply = ollama.chat(model=MODEL, messages=messages, tools=tools).message
                messages.append(reply)
                if not reply.tool_calls:
                    print(f"\n{reply.content}")
                    break
                for call in reply.tool_calls:
                    name, args = call.function.name, call.function.arguments
                    print(f"{CYAN}  → {name}({args}){RESET}")
                    result = await mcp.call_tool(name, args)
                    text = result.content[0].text
                    print(f"{DIM}  ← {json.dumps(json.loads(text))}{RESET}")
                    messages.append({"role": "tool", "tool_name": name, "content": text})


if __name__ == "__main__":
    asyncio.run(main(use_tools="--no-tools" not in sys.argv))

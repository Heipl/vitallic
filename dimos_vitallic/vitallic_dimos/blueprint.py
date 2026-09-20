"""Go2 connection + MCP skills. No LLM, no OpenAI key.

Run it with:

    dimos run vitallic-dimos.scan --robot-ip <DOG_IP>

This wraps stock `unitree-go2-basic` (WebRTC + viewer) and an MCP server so
`precise_move` / `blind_move` are callable. It does **not** include `McpClient`
or the agentic stack, which is what demanded OPENAI_API_KEY.

Velocity from PreciseMove is remapped onto GO2Connection.cmd_vel (there is no
MovementManager / tele_cmd_vel on the basic blueprint). Override if `dimos spy`
shows a different name:

    VITALLIC_CMD_VEL_TOPIC=<real name> dimos run vitallic-dimos.scan --robot-ip <IP>
"""

from __future__ import annotations

from dimos.agents.mcp.mcp_server import McpServer
from dimos.core.coordination.blueprints import autoconnect
from dimos.robot.unitree.go2.blueprints.basic.unitree_go2_basic import unitree_go2_basic

from vitallic_dimos.precise_move import CMD_VEL_TOPIC, PreciseMove

vitallic_scan = autoconnect(
    unitree_go2_basic,
    McpServer.blueprint(),
    PreciseMove.blueprint(),
).remappings([(PreciseMove, "cmd_vel", CMD_VEL_TOPIC)])

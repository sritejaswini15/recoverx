# MCP

`GET /mcp/tools` lists read and write RecoverX tools. `POST /mcp` requires bearer authentication. Case and customer arguments are checked against the authenticated organization before dispatch. Read tools are scoped queries; write tools add actor and organization context and call ToolGateway.

MCP never calls Razorpay directly and cannot bypass policy, authorization, idempotency, or audit logging.
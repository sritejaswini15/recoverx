# Architecture

```text
Provider webhook -> signature check -> dedupe -> raw RevenueEvent
  -> risk -> recovery case -> recovery graph -> policy -> ToolGateway
  -> simulated provider/communication -> webhook -> observation -> analytics/audit
```

PostgreSQL is business truth. AI returns recommendations only. Every merchant object is organization-scoped. MCP calls use the same authenticated organization and write tools route through ToolGateway and PolicyEngine.
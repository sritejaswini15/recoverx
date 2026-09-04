# Policy

Default limits are 25,000 currency units for autonomous actions, three contact attempts, seven escalation days, and 0.70 minimum AI confidence. Opt-out, terminal cases, exhausted attempts, over-limit amounts, low confidence, and overdue thresholds stop or escalate actions.

Policies are stored per organization. The ToolGateway re-evaluates the current policy immediately before provider execution and checks the merchant allowed-action list.
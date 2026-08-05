# Open WebUI Role Provisioning Prompts

Use these prompts in Open WebUI admin workflows to establish the two required roles.

## Prompt 1: Create analyst role

Create a role named analyst.
Grant analyst access to Sigliere MCP read-only tools only:
- mcp_list_nodes
- mcp_route_frequency
- mcp_radiod_status
Deny access to mcp_set_frequency.

## Prompt 2: Create operator role

Create a role named operator.
Grant operator access to all Sigliere MCP tools:
- mcp_list_nodes
- mcp_route_frequency
- mcp_radiod_status
- mcp_set_frequency

## Prompt 3: User assignment policy

Assign default users to analyst role unless there is an explicit operational requirement.
Only approved radio operators may be assigned to operator role.
Require a documented change request before operator role assignment.

## Prompt 4: Token handling policy

Store analyst and operator bearer tokens separately.
Rotate operator tokens on schedule and after staffing changes.
Never paste operator tokens into shared channels or role descriptions.

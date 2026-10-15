SELECT pg_advisory_xact_lock(98210422);
-- Synthetic development data only. Re-running does not create duplicate chains.
INSERT INTO workspaces (slug, name) VALUES ('development', 'Development workspace') ON CONFLICT (slug) DO NOTHING;
INSERT INTO members (workspace_id, subject_id, role)
SELECT id, 'seed-admin', 'Admin' FROM workspaces WHERE slug='development'
ON CONFLICT (workspace_id, subject_id) DO NOTHING;
INSERT INTO members (workspace_id, subject_id, role)
SELECT id, 'seed-agent', 'Agent' FROM workspaces WHERE slug='development'
ON CONFLICT (workspace_id, subject_id) DO NOTHING;
INSERT INTO goals (workspace_id, title, description, status, kpi_definition, constraints)
SELECT w.id, '[seed] Club campaign', 'Synthetic demonstration, no publishing', 'active', '{"registrations":20}', '{"external_publish":false}'
FROM workspaces w WHERE slug='development'
AND NOT EXISTS (SELECT 1 FROM goals g WHERE g.workspace_id=w.id AND g.title='[seed] Club campaign');
INSERT INTO strategies (workspace_id, goal_id, version, content, rationale)
SELECT g.workspace_id, g.id, 1, 'Draft an Instagram campaign; approval required.', 'Synthetic baseline'
FROM goals g JOIN workspaces w ON w.id=g.workspace_id
WHERE w.slug='development' AND g.title='[seed] Club campaign'
ON CONFLICT (workspace_id, goal_id, version) DO NOTHING;
INSERT INTO executions (workspace_id, strategy_id, status, result_summary)
SELECT s.workspace_id, s.id, 'QUEUED', 'Seed record only; no external execution'
FROM strategies s JOIN goals g ON g.id=s.goal_id AND g.workspace_id=s.workspace_id JOIN workspaces w ON w.id=s.workspace_id
WHERE w.slug='development' AND g.title='[seed] Club campaign' AND s.version=1
AND NOT EXISTS (SELECT 1 FROM executions e WHERE e.workspace_id=s.workspace_id AND e.strategy_id=s.id AND e.result_summary='Seed record only; no external execution');

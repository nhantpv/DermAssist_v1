-- ============================================================
-- 002_seed_demo_user.sql
-- DermAssist VN — Seed demo account (REQ-FUNC-013)
-- Idempotent: ON CONFLICT DO NOTHING
-- ============================================================

BEGIN;

-- Demo account per REQ-FUNC-013
-- Password: 'demo' (bcrypt-hashed)
-- To regenerate this hash:
--   python3 -c "import bcrypt; print(bcrypt.hashpw(b'demo', bcrypt.gensalt(rounds=12)).decode())"
-- To verify:
--   python3 -c "import bcrypt; print(bcrypt.checkpw(b'demo', b'\$2b\$12\$HZXsGd866KPOaND78MWFz.w3yPUPUHOSblPjU69MjSJa3.FEpPIwG'))"

INSERT INTO users (username, password_hash, full_name, role, rate_limit_rpm)
VALUES (
    'demo',
    '$2b$12$HZXsGd866KPOaND78MWFz.w3yPUPUHOSblPjU69MjSJa3.FEpPIwG',
    'Demo Account',
    'demo',
    10  -- 10 RPM rate limit
)
ON CONFLICT (username) DO NOTHING;

COMMIT;

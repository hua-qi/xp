CREATE TABLE IF NOT EXISTS experiences (
    id              VARCHAR(36)     PRIMARY KEY,
    type            VARCHAR(32)     NOT NULL,
    level           VARCHAR(16)     NOT NULL,
    title           TEXT            NOT NULL,
    tags            JSON            NOT NULL DEFAULT (JSON_ARRAY()),
    problem         TEXT            NOT NULL,
    solution        TEXT            NOT NULL,
    key_decisions   TEXT            NOT NULL DEFAULT '',
    confidence      FLOAT           NOT NULL DEFAULT 0.6,
    status          VARCHAR(32)     NOT NULL DEFAULT 'pending',
    source          VARCHAR(32)     NOT NULL DEFAULT 'agent',
    created_at      VARCHAR(32)     NOT NULL,
    related_files   JSON            NOT NULL DEFAULT (JSON_ARRAY()),
    reject_reason   TEXT,
    metadata        JSON            NOT NULL DEFAULT (JSON_OBJECT()),
    project         VARCHAR(36)     NOT NULL DEFAULT 'default',
    scope_type      VARCHAR(32)     NOT NULL DEFAULT 'project',
    scope_id        VARCHAR(36),
    promoted_to     VARCHAR(36),
    demoted_from    VARCHAR(36),
    recall_count    INT             NOT NULL DEFAULT 0,
    adoption_rate   FLOAT           NOT NULL DEFAULT 0.0,
    last_hit_at     VARCHAR(32),
    stale_reason    TEXT,
    ab_group        ENUM('A','B')   NOT NULL DEFAULT 'B',
    conflict_with   VARCHAR(36),
    retry_count     INT             NOT NULL DEFAULT 0,
    raw_input       JSON,
    embedding       MEDIUMBLOB
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE FULLTEXT INDEX IF NOT EXISTS ft_experiences_content
    ON experiences (title, problem, solution);

CREATE TABLE IF NOT EXISTS sessions (
    session_id              VARCHAR(36)     PRIMARY KEY,
    task_description        TEXT            NOT NULL,
    experience_ids_injected JSON            NOT NULL DEFAULT (JSON_ARRAY()),
    iteration_count         INT             NOT NULL DEFAULT 1,
    had_error_correction    TINYINT(1)      NOT NULL DEFAULT 0,
    user_accepted           TINYINT(1)      NOT NULL DEFAULT 1,
    ab_test_group           VARCHAR(16)     NOT NULL DEFAULT 'B',
    created_at              VARCHAR(32)     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS feedbacks (
    id              VARCHAR(36)     PRIMARY KEY,
    experience_id   VARCHAR(36)     NOT NULL,
    session_id      VARCHAR(36),
    helpful         TINYINT(1)      NOT NULL,
    comment         TEXT,
    created_at      VARCHAR(32)     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS experience_stats (
    experience_id   VARCHAR(36)     PRIMARY KEY,
    hit_count       INT             NOT NULL DEFAULT 0,
    adopted_count   INT             NOT NULL DEFAULT 0,
    rejected_count  INT             NOT NULL DEFAULT 0,
    adoption_rate   FLOAT           NOT NULL DEFAULT 0.0,
    last_adopted_at VARCHAR(32)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS conflict_reviews (
    id              VARCHAR(36)     PRIMARY KEY,
    experience_id_a VARCHAR(36)     NOT NULL,
    experience_id_b VARCHAR(36)     NOT NULL,
    conflict_type   VARCHAR(32)     NOT NULL,
    status          ENUM('pending','resolved') NOT NULL DEFAULT 'pending',
    resolution      VARCHAR(32),
    condition_note  TEXT,
    resolved_at     VARCHAR(32),
    created_at      VARCHAR(32)     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS correction_requests (
    id                  VARCHAR(36)     PRIMARY KEY,
    experience_id       VARCHAR(36)     NOT NULL,
    session_id          VARCHAR(36)     NOT NULL,
    comment             TEXT            NOT NULL,
    task_description    TEXT            NOT NULL,
    outcome_description TEXT            NOT NULL,
    status              ENUM('pending','fixed','dismissed') NOT NULL DEFAULT 'pending',
    fixed_at            VARCHAR(32),
    created_at          VARCHAR(32)     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prompt_configs (
    `key`       VARCHAR(64)     PRIMARY KEY,
    content     TEXT            NOT NULL,
    updated_at  VARCHAR(32)     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO prompt_configs (`key`, content, updated_at) VALUES
('extraction_prompt',
'你是一个工程经验提炼助手。根据以下任务信息，提炼出结构化的工程经验。\n\n## 输入\n任务描述：{task_description}\n任务结果：{outcome_description}\n结果状态：{outcome}\n\n## 输出要求\n严格按照以下 JSON 格式输出，不要输出其他内容：\n{\n  \"title\": \"10-20字的经验标题，概括核心问题和解法\",\n  \"problem\": \"清晰描述问题场景和背景，50字以上\",\n  \"solution\": \"具体的解决方案和步骤，50字以上\",\n  \"key_decisions\": \"关键决策点和踩坑点，30字以上\",\n  \"tags\": [\"技术栈标签\", \"最多5个\"],\n  \"type\": \"bugfix 或 feature 或 pattern 三选一\"\n}',
NOW()),
('conflict_type_prompt',
'以下两条工程经验针对相似问题给出了不同方案，请判断冲突类型。\n\n## 已有经验\n问题：{existing_problem}\n方案：{existing_solution}\n\n## 新经验\n问题：{new_problem}\n方案：{new_solution}\n\n## 冲突类型\n请从以下类型中选择一个，只输出类型名称：\n- outdated\n- alternative\n- version_diff\n- new_may_wrong\n- condition_diff',
NOW()),
('rerank_prompt',
'根据以下任务描述，从候选经验中选出最相关的至多3条。\n\n## 任务\n{task_description}\n\n## 候选经验\n{candidates}\n\n## 输出要求\n只输出 JSON 数组，包含最相关的经验 ID，按相关度降序排列：\n["id-1", "id-2", "id-3"]\n若没有相关经验，输出：[]',
NOW()),
('comment_analysis_prompt',
'以下是用户对一条工程经验的反馈 comment，请判断反馈语义类型。\n\n## 反馈内容\n{comment}\n\n## 判断规则\n- 如果反馈表达"经验完全不适用、方向错误、和当前问题无关"，输出：irrelevant\n- 如果反馈表达"经验思路/方向是对的，但某些细节、版本、参数有误"，输出：needs_fix\n\n只输出一个词：irrelevant 或 needs_fix',
NOW());

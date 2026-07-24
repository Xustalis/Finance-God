"""Server-owned AI provider endpoints and controlled model catalog."""

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})

STEPFUN_BASE_URL = "https://api.stepfun.com/v1"
STEPFUN_PROFILE_MODEL = "step-3.5-flash-2603"
STEPFUN_MODELS = frozenset({STEPFUN_PROFILE_MODEL})

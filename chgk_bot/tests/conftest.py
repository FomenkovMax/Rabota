import os

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_for_tests_only")
os.environ.setdefault("DATA_DIR", "/tmp/chgk_test_data")
os.environ.pop("ANTHROPIC_API_KEY", None)

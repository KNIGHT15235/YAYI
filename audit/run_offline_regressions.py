"""Run explicitly selected offline tests without .env files or external sockets.

Usage: python audit/run_offline_regressions.py test_workflow_improvements test_runtime_improvements
This runner never proves live provider availability or retrieval/quality metrics.
"""
from pathlib import Path
import os
import json
import logging
import socket
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "audit"), str(ROOT / "backend" / "app")]
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ.update(POSTGRES_HOST="127.0.0.1", POSTGRES_PORT="1", POSTGRES_USER="offline_test",
                  POSTGRES_PASSWORD="offline_test", POSTGRES_DB="offline_test",
                  REDIS_HOST="127.0.0.1", REDIS_PORT="1", REDIS_PASSWORD="")
# Imports must not discover credentials from developer shells either.
for key in list(os.environ):
    if any(word in key.upper() for word in ("API_KEY", "ACCESS_KEY", "SECRET_KEY")):
        os.environ.pop(key, None)

import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
dotenv.dotenv_values = lambda *args, **kwargs: {}


def deny_network(*args, **kwargs):
    raise RuntimeError("Offline regression runner blocked an external network connection")


socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network

if __name__ == "__main__":
    quiet = '--quiet' in sys.argv
    names = [name for name in sys.argv[1:] if name != '--quiet'] or [
        "test_workflow_improvements", "test_runtime_improvements", "test_evidence_improvements",
        "test_runtime_configuration",
        "test_agent_request_configuration",
        "test_hybrid_retrieval",
        "test_science_engine", "test_science_assets", "test_science_recursion",
        "test_scout_hypothesis_stage", "test_review_only_pipeline",
        "test_research_regressions", "test_research_error_checkpoint", "test_docmind_result_shapes",
    ]
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    if quiet:
        logging.disable(logging.INFO)
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=1 if quiet else 2).run(suite)
    print('OFFLINE_TEST_SUMMARY=' + json.dumps({
        'modules': names, 'tests': result.testsRun, 'failures': len(result.failures),
        'errors': len(result.errors), 'skipped': len(result.skipped),
        'seconds': round(time.monotonic() - started, 3), 'success': result.wasSuccessful(),
        'network': 'blocked', 'dotenv': 'disabled',
    }))
    raise SystemExit(0 if result.wasSuccessful() else 1)

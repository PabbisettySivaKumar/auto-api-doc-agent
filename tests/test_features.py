"""Phase A tests: feature resolution + bucketing (agent/features.py)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import features, detect  # noqa: E402
from agent.features import CORE_SHARED  # noqa: E402


def test_resolve_feature_basic() -> None:
    assert features.resolve_feature("users/routes.py") == "users"
    assert features.resolve_feature("payments/api/charge.py") == "payments"
    assert features.resolve_feature("orders/handlers/create.ts") == "orders"
    print("PASS test_resolve_feature_basic")


def test_resolve_feature_source_root() -> None:
    assert features.resolve_feature("src/orders/h.py", source_root="src") == "orders"
    assert features.resolve_feature("src/app.py", source_root="src") == CORE_SHARED
    print("PASS test_resolve_feature_source_root")


def test_resolve_feature_catch_all() -> None:
    assert features.resolve_feature("main.py") == CORE_SHARED           # root file
    assert features.resolve_feature("utils/helpers.py") == CORE_SHARED  # shared dir
    assert features.resolve_feature("common/db.py") == CORE_SHARED
    assert features.resolve_feature("config/settings.py") == CORE_SHARED
    print("PASS test_resolve_feature_catch_all")


def test_display_name_default_and_override() -> None:
    assert features.feature_display_name("users") == "Users"
    assert features.feature_display_name("user_management") == "User Management"
    assert features.feature_display_name("payment-service") == "Payment Service"
    assert features.feature_display_name(CORE_SHARED) == "Core / Shared"
    ov = {"users": "User Management"}
    assert features.feature_display_name("users", ov) == "User Management"
    print("PASS test_display_name_default_and_override")


def test_yaml_override_loading() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "features.yml").write_text(
            "features:\n  users: User Management\n  payments: Billing\n"
        )
        ov = features._load_overrides(d)
        assert ov == {"users": "User Management", "payments": "Billing"}
    # No file -> empty, no error.
    with tempfile.TemporaryDirectory() as d:
        assert features._load_overrides(d) == {}
    print("PASS test_yaml_override_loading")


def test_change_file_stamped_by_dispatcher() -> None:
    before = "def get_user(id):\n    return {}\n"
    after = "def get_user(id, verbose=False):\n    return {}\n"
    changes = detect.detect_changes("users/service.py", before, after)
    assert changes and all(c.file == "users/service.py" for c in changes)
    print("PASS test_change_file_stamped_by_dispatcher")


def test_bucket_multi_feature_pr() -> None:
    # Simulate a PR touching two features + a shared util.
    changes = []
    changes += detect.detect_changes(
        "users/service.py",
        "def create_user(name):\n    return {}\n",
        "def create_user(name, role):\n    return {}\n",
    )
    changes += detect.detect_changes(
        "payments/charge.py",
        "def charge(amount):\n    return {}\n",
        "def charge(amount, currency):\n    return {}\n",
    )
    changes += detect.detect_changes(
        "utils/format.py",
        "def money(x):\n    return x\n",
        "def money(x, sym='$'):\n    return x\n",
    )
    buckets = features.bucket_changes(changes)
    assert set(buckets) == {"users", "payments", CORE_SHARED}
    assert buckets["users"][0].key == "func create_user"
    assert buckets["payments"][0].key == "func charge"
    assert buckets[CORE_SHARED][0].key == "func money"
    print("PASS test_bucket_multi_feature_pr ->", {k: len(v) for k, v in buckets.items()})


if __name__ == "__main__":
    test_resolve_feature_basic()
    test_resolve_feature_source_root()
    test_resolve_feature_catch_all()
    test_display_name_default_and_override()
    test_yaml_override_loading()
    test_change_file_stamped_by_dispatcher()
    test_bucket_multi_feature_pr()
    print("\nAll feature-bucketing tests passed.")

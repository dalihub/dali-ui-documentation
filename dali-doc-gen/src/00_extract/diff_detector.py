"""
diff_detector.py — Detect changed APIs by comparing parsed_doxygen JSON snapshots

동작:
  - cache/parsed_doxygen/<pkg>.json.old (이전 실행) vs <pkg>.json (현재 실행) 비교
  - compound(class) 레벨: brief 변경 감지
  - member 레벨: added / removed / modified (signature, brief, params, returns, notes) 감지
  - 결과를 cache/changed_apis.json 에 저장

주의:
  - pipeline.py 가 doxygen_parser.py 실행 전에 *.json → *.json.old 백업을 수행해야 함
  - *.json.old 가 없으면 "첫 실행"으로 간주하고 changed_apis.json 을 빈 dict 로 저장
"""

import json
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PARSED_DOXYGEN_DIR = PROJECT_ROOT / "cache" / "parsed_doxygen"
OUT_PATH = PROJECT_ROOT / "cache" / "changed_apis.json"

# Doxygen 주석 및 API 시그니처 관련 필드만 비교 (license/include 변경은 여기에 나타나지 않음)
COMPARE_MEMBER_FIELDS = [
    "brief", "signature", "params", "returns",
    "notes", "warnings", "deprecated", "since"
]


def load_json(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def index_compounds(data):
    """compound 목록을 name 기준 dict 로 인덱싱"""
    if not data:
        return {}
    return {c["name"]: c for c in data.get("compounds", []) if "name" in c}


def index_members(compound):
    """member 목록을 name 기준 dict 로 인덱싱"""
    return {m["name"]: m for m in compound.get("members", []) if "name" in m}


def diff_member(old_m, new_m):
    """두 멤버를 비교하여 변경된 필드 dict 반환"""
    changed = {}
    for field in COMPARE_MEMBER_FIELDS:
        old_val = old_m.get(field)
        new_val = new_m.get(field)
        if old_val != new_val:
            changed[field] = {"old": old_val, "new": new_val}
    return changed


def diff_package(old_data, new_data):
    """
    두 parsed_doxygen JSON 을 비교하여 변경된 API 목록 반환.

    Returns:
        list of dict — 변경/추가/삭제된 class 항목들
    """
    old_compounds = index_compounds(old_data)
    new_compounds = index_compounds(new_data)

    result = []

    # ── 신규 추가 또는 변경된 클래스 ────────────────────────────────────────
    for cls_name, new_cls in new_compounds.items():
        api_tier = new_cls.get("api_tier", "unknown")

        # 신규 추가된 클래스
        if cls_name not in old_compounds:
            result.append({
                "class": cls_name,
                "api_tier": api_tier,
                "class_change": "added",
                "class_brief_changed": False,
                "changed_members": [],
                "added_members": [
                    {
                        "name": m.get("name", ""),
                        "change_type": "added",
                        "new_brief": m.get("brief", ""),
                        "new_signature": m.get("signature", ""),
                    }
                    for m in new_cls.get("members", [])
                ],
                "removed_members": [],
            })
            continue

        old_cls = old_compounds[cls_name]
        old_members = index_members(old_cls)
        new_members = index_members(new_cls)

        class_brief_changed = old_cls.get("brief") != new_cls.get("brief")
        changed_members = []
        added_members = []
        removed_members = []

        # 변경 또는 추가된 멤버
        for mb_name, new_mb in new_members.items():
            if mb_name not in old_members:
                added_members.append({
                    "name": mb_name,
                    "change_type": "added",
                    "new_brief": new_mb.get("brief", ""),
                    "new_signature": new_mb.get("signature", ""),
                })
            else:
                diff = diff_member(old_members[mb_name], new_mb)
                if diff:
                    entry = {"name": mb_name, "change_type": "modified"}
                    for field, vals in diff.items():
                        entry[f"old_{field}"] = vals["old"]
                        entry[f"new_{field}"] = vals["new"]
                    changed_members.append(entry)

        # 삭제된 멤버
        for mb_name in old_members:
            if mb_name not in new_members:
                removed_members.append({"name": mb_name})

        # 변경이 있는 클래스만 기록
        if class_brief_changed or changed_members or added_members or removed_members:
            result.append({
                "class": cls_name,
                "api_tier": api_tier,
                "class_change": None,
                "class_brief_changed": class_brief_changed,
                "changed_members": changed_members,
                "added_members": added_members,
                "removed_members": removed_members,
            })

    # ── 삭제된 클래스 ────────────────────────────────────────────────────────
    for cls_name in old_compounds:
        if cls_name not in new_compounds:
            result.append({
                "class": cls_name,
                "api_tier": old_compounds[cls_name].get("api_tier", "unknown"),
                "class_change": "removed",
                "class_brief_changed": False,
                "changed_members": [],
                "added_members": [],
                "removed_members": [],
            })

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Detect changed APIs by comparing parsed_doxygen JSON snapshots"
    )
    parser.add_argument(
        "--package", type=str,
        help="Specific package to check (e.g., dali-core). If omitted, runs all."
    )
    args = parser.parse_args()

    packages = ["dali-core", "dali-adaptor", "dali-ui"]
    if args.package:
        packages = [args.package]

    all_changes = {}

    for pkg in packages:
        new_path = PARSED_DOXYGEN_DIR / f"{pkg}.json"
        old_path = PARSED_DOXYGEN_DIR / f"{pkg}.json.old"

        if not new_path.exists():
            print(f"  [{pkg}] Parsed JSON not found at {new_path}. Skipping.")
            all_changes[pkg] = []
            continue

        if not old_path.exists():
            print(f"  [{pkg}] No previous snapshot (*.json.old) — first run, no changes recorded.")
            all_changes[pkg] = []
            continue

        print(f"  [{pkg}] Comparing parsed_doxygen snapshots...")
        old_data = load_json(old_path)
        new_data = load_json(new_path)

        changes = diff_package(old_data, new_data)
        all_changes[pkg] = changes

        total_members = sum(
            len(c.get("changed_members", []))
            + len(c.get("added_members", []))
            + len(c.get("removed_members", []))
            for c in changes
        )
        print(f"  [{pkg}] {len(changes)} class(es) with changes, "
              f"{total_members} member-level change(s).")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_changes, f, indent=2, ensure_ascii=False)

    print(f"\nChanged APIs saved to {OUT_PATH}")


if __name__ == "__main__":
    main()

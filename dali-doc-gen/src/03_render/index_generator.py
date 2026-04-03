"""
index_generator.py — Stage E: Index.md 자동 생성

역할:
  - feature_taxonomy.json의 Tree 구조를 읽어
  - 실제로 생성된 .md 파일 목록과 대조
  - Tree 형태의 링크 구조를 가진 index.md 파일 생성

출력:
  output/<tier>-guide/docs/index.md  (최종 output, --tier 지정 시)
  cache/markdown_drafts/Index.md     (캐시, 항상 저장)
"""

import json
import argparse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
TAXONOMY_PATH = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"
VALIDATED_DIR = CACHE_DIR / "validated_drafts"   # Stage D 통과 파일
DRAFTS_DIR = CACHE_DIR / "markdown_drafts"        # fallback (Stage D 미실행 시)
REPORT_PATH = CACHE_DIR / "validation_report" / "stage_d_report.json"
CACHE_INDEX_PATH = CACHE_DIR / "markdown_drafts" / "Index.md"

GUIDE_ROOT = PROJECT_ROOT.parent          # dali-guide/
APP_GUIDE_OUT = GUIDE_ROOT / "app-guide" / "docs"
PLATFORM_GUIDE_OUT = GUIDE_ROOT / "platform-guide" / "docs"


def load_json(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_verdict(feat_key, report_cache=[None]):
    """
    Stage D 리포트에서 해당 feature의 판정을 읽어 반환합니다.
    리포트를 한 번만 로드하도록 내부 캐시.
    """
    if report_cache[0] is None:
        report_cache[0] = load_json(REPORT_PATH) or []
    for entry in report_cache[0]:
        if entry.get("feature") == feat_key:
            return entry.get("verdict")
    return None


def doc_exists(feat_key, validated_dir=None, drafts_dir=None):
    """validated_drafts/ 또는 markdown_drafts/ 어디에라도 .md가 있는지 확인."""
    vdir = validated_dir if validated_dir is not None else VALIDATED_DIR
    ddir = drafts_dir if drafts_dir is not None else DRAFTS_DIR
    return (vdir / f"{feat_key}.md").exists() or \
           (ddir / f"{feat_key}.md").exists()


def notier_exists(feat_key, validated_dir=None, drafts_dir=None):
    """이 tier에 스펙이 없어 stage_c가 .notier 마커를 남긴 경우 True."""
    vdir = validated_dir if validated_dir is not None else VALIDATED_DIR
    ddir = drafts_dir if drafts_dir is not None else DRAFTS_DIR
    return (vdir / f"{feat_key}.notier").exists() or \
           (ddir / f"{feat_key}.notier").exists()


def render_tree_node(feat_key, taxonomy, indent=0, visited=None,
                     validated_dir=None, drafts_dir=None):
    """
    taxonomy를 재귀적으로 탐색하여 Tree 구조의 마크다운 링크 목록을 생성합니다.
    """
    if visited is None:
        visited = set()
    if feat_key in visited:
        return []   # 순환 방지
    visited.add(feat_key)

    lines = []
    tax_entry = taxonomy.get(feat_key, {})
    display_name = tax_entry.get("display_name", feat_key)
    doc_file = tax_entry.get("doc_file", f"{feat_key}.md")
    children = tax_entry.get("children", [])
    prefix = "  " * indent

    verdict = get_verdict(feat_key)
    badge = ""
    if verdict == "WARN":
        badge = " ⚠️"
    elif verdict == "FAIL":
        badge = " ❌"
    elif verdict == "LOW_CONTENT":
        badge = " 📄"

    # 링크 생성: 3-way 구분
    # 1) .md 있음 → 링크
    # 2) .notier 있음 → 이 티어에 스펙 없음 → 숨김
    # 3) 둘 다 없음 → 생성 예정 표시
    if doc_exists(feat_key, validated_dir, drafts_dir):
        link = f"{prefix}- [{display_name}]({doc_file}){badge}"
    elif notier_exists(feat_key, validated_dir, drafts_dir):
        return []   # 이 티어에 스펙 없음 — 인덱스에서 완전히 숨김
    else:
        link = f"{prefix}- {display_name}{badge} *(not yet generated)*"

    lines.append(link)

    # 자식 노드 재귀 렌더링
    for child_key in children:
        lines.extend(render_tree_node(child_key, taxonomy, indent + 1, visited,
                                      validated_dir, drafts_dir))

    return lines


def main():
    parser = argparse.ArgumentParser(description="Generate index.md for DALi documentation")
    parser.add_argument("--tier", type=str, choices=["app", "platform"], default=None,
                        help="Target output tier. If set, also writes to output/<tier>-guide/docs/index.md")
    args = parser.parse_args()

    # 티어별 validated/drafts 경로 결정
    if args.tier:
        tier_validated = VALIDATED_DIR / args.tier
        tier_drafts = DRAFTS_DIR / args.tier
    else:
        tier_validated = VALIDATED_DIR
        tier_drafts = DRAFTS_DIR

    print("=================================================================")
    print(" Index Generator: Building documentation tree index              ")
    print("=================================================================")

    taxonomy = load_json(TAXONOMY_PATH)
    if not taxonomy:
        print("Error: feature_taxonomy.json not found. Run Phase 1.5 first.")
        return

    tier_validated.mkdir(parents=True, exist_ok=True)
    tier_drafts.mkdir(parents=True, exist_ok=True)

    # --tier 에 따라 platform 전용 feature 를 index 에서 제외
    exclude_platform = (args.tier == "app")

    # 생성된 .md 파일 목록 (tier별 경로 기준)
    generated_files = {p.stem for p in tier_drafts.glob("*.md") if p.name != "Index.md"}
    generated_files |= {p.stem for p in tier_validated.glob("*.md") if p.name != "Index.md"}
    print(f"[Index] Found {len(generated_files)} generated markdown files.")

    # ── Index.md 구성 ──────────────────────────────────────────────────
    lines = []
    lines.append("# DALi Documentation Index")
    lines.append("")
    lines.append("> Auto-generated documentation index. "
                 "Tree structure reflects the class hierarchy determined by Taxonomy.")
    lines.append("")
    lines.append(f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 최상위 Feature 그룹별 섹션 생성 ──────────────────────────────────
    # parent가 없고, tree_decision이 tree 또는 flat인 최상위 항목만 수집
    # app 티어면 platform 전용(audience == "platform") 항목 제외
    top_level_roots = []
    for feat_key, entry in taxonomy.items():
        if feat_key == "uncategorized_ambiguous_root":
            continue
        if entry.get("suppress_doc"):
            continue
        if entry.get("parent") is None and entry.get("tree_decision") != "leaf":
            if exclude_platform and entry.get("audience") == "platform":
                continue
            top_level_roots.append(feat_key)

    # 어떤 tree의 child로 등록된 항목은 최상위에서 제외
    # (tree 구조 안에 있는 항목이 우선 — 최상위 중복 노출 방지)
    child_keys_in_trees = set()
    for feat_key in top_level_roots:
        for child_key in taxonomy.get(feat_key, {}).get("children", []):
            child_keys_in_trees.add(child_key)
    top_level_roots = [k for k in top_level_roots if k not in child_keys_in_trees]

    # display_name 알파벳 순 정렬
    top_level_roots.sort(key=lambda k: taxonomy.get(k, {}).get("display_name", k).lower())

    # tree 항목(children 있음)과 flat 항목 분리
    tree_roots = [k for k in top_level_roots
                  if taxonomy.get(k, {}).get("tree_decision") == "tree" and taxonomy.get(k, {}).get("children")]
    flat_roots = [k for k in top_level_roots
                  if k not in tree_roots]

    # ── Section 1: All Features (Flat) ───────────────────────────────
    lines.append("## All Features")
    lines.append("")
    lines.append("Complete list of all documented features:")
    lines.append("")

    # 모든 최상위 feature를 영문 정렬로 나열
    for feat_key in top_level_roots:
        tax_entry = taxonomy.get(feat_key, {})
        display_name = tax_entry.get("display_name", feat_key)
        doc_file = tax_entry.get("doc_file", f"{feat_key}.md")
        children = tax_entry.get("children", [])

        if doc_exists(feat_key, tier_validated, tier_drafts):
            lines.append(f"- **[{display_name}]({doc_file})**")
        elif notier_exists(feat_key, tier_validated, tier_drafts):
            pass  # 이 티어에 스펙 없음 — 숨김
        else:
            lines.append(f"- **{display_name}** *(not yet generated)*")

        # 자식 목록도 들여쓰기로 포함
        for child_key in children:
            child_entry = taxonomy.get(child_key, {})
            child_display = child_entry.get("display_name", child_key)
            child_file = child_entry.get("doc_file", f"{child_key}.md")
            if doc_exists(child_key, tier_validated, tier_drafts):
                lines.append(f"  - [{child_display}]({child_file})")
            elif notier_exists(child_key, tier_validated, tier_drafts):
                pass  # 숨김
            else:
                lines.append(f"  - {child_display} *(not yet generated)*")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*This index is auto-generated by the DALi documentation pipeline.*")

    content = "\n".join(lines)

    # ── 캐시 저장 (항상) ──────────────────────────────────────────────
    CACHE_INDEX_PATH.write_text(content, encoding="utf-8")
    print(f"[Index] Cache copy saved: {CACHE_INDEX_PATH}")

    # ── 최종 output 저장 (--tier 지정 시) ────────────────────────────
    if args.tier:
        output_dir = APP_GUIDE_OUT if args.tier == "app" else PLATFORM_GUIDE_OUT
        output_dir.mkdir(parents=True, exist_ok=True)

        # Docusaurus Frontmatter 추가
        frontmatter = f"---\nid: index\ntitle: \"Documentation Index\"\nsidebar_label: \"Index\"\n---\n\n"
        out_path = output_dir / "index.md"
        out_path.write_text(frontmatter + content, encoding="utf-8")
        print(f"[Index] Output copy saved: {out_path}")

    print(f"[Index] Total top-level entries: {len(top_level_roots)}")
    print(f"[Index] Tree hierarchy roots: {len(tree_roots)}")
    print("=================================================================")


if __name__ == "__main__":
    main()

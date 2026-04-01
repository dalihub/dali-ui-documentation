import os
import json
import re
import shutil
import argparse
from pathlib import Path
from jinja2 import Template

# ── Paths ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
VALIDATED_DIR = CACHE_DIR / "validated_drafts"
TAXONOMY_PATH = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"

APP_GUIDE_OUT = PROJECT_ROOT / "output" / "app-guide" / "docs"
PLATFORM_GUIDE_OUT = PROJECT_ROOT / "output" / "platform-guide" / "docs"

DUMMY_DOXYGEN_BASE = "https://dummy-doxygen.tizen.org/dali/"

# ── Frontmatter Template ──────────────────────────────────────────────
# Jinja2 템플릿을 사용하여 마크다운 최상단에 주입할 YAML 메타데이터 구조입니다.
FRONTMATTER_TEMPLATE = """---
id: {{ doc_id }}
title: "{{ title }}"
sidebar_label: "{{ title }}"
---

"""

def load_json(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def build_cross_linking_regex(taxonomy):
    """
    Taxonomy에 명시된 모든 display_name을 추출하여 
    본문에서 링크로 변환할 정규식 컴파일.
    """
    # display_name -> feature_id (md 파일명 제외)
    name_to_id = {}
    for feat_id, data in taxonomy.items():
        # 이름이 길고 명확한 것부터 치환하기 위해 길이를 고려할 수 있으나,
        # 일단 이름을 통째로 매핑합니다.
        disp = data.get("display_name", feat_id)
        if len(disp) > 2: # 너무 짧은 단어 무시
            name_to_id[disp] = feat_id

    if not name_to_id:
        return None, {}

    # 가장 긴 단어부터 매칭되도록 정렬 (예: "Image" 보다 "ImageView"가 먼저 매칭)
    sorted_names = sorted(name_to_id.keys(), key=len, reverse=True)
    
    # 정규식 구조: 이미 링크( [text](url) )이거나 코드블록(`text`) 안인지 판별하기 위해,
    # Negative Lookahead/Lookbehind 등을 복잡하게 쓰기보다, 콜백 함수로 처리합니다.
    # 단어 경계(\b)를 사용하여 매칭합니다. (알파벳 기준)
    escaped_names = [re.escape(name) for name in sorted_names]
    pattern_str = r'(`[^`]+`|\[[^\]]+\]\([^)]+\))|(\b(?:' + '|'.join(escaped_names) + r')\b)'
    
    return re.compile(pattern_str), name_to_id

def cross_link_replacer(match, name_to_id):
    """정규식 치환에 사용될 콜백 함수"""
    protected = match.group(1) # 코드블록이나 기존 링크
    target = match.group(2)    # 우리가 치환할 타겟 단어

    if protected:
        return protected
    elif target:
        doc_id = name_to_id.get(target)
        if doc_id:
            # Docusaurus 내부 링크 포맷: [단어](./doc_id.md)
            return f"[{target}](./{doc_id}.md)"
        return target
    return match.group(0)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=str, choices=["app", "platform"], default="app", help="Target output tier")
    args = parser.parse_args()

    print("=================================================================")
    print(f" MD Renderer: Formatting documents for '{args.tier}-guide'     ")
    print("=================================================================")

    if not VALIDATED_DIR.exists():
        print(f"Error: {VALIDATED_DIR} not found. Please run previous stages.")
        return

    output_dir = APP_GUIDE_OUT if args.tier == "app" else PLATFORM_GUIDE_OUT
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[Renderer] Output directory prepared: {output_dir}")

    taxonomy = load_json(TAXONOMY_PATH)
    cross_link_regex, name_to_id = build_cross_linking_regex(taxonomy)
    
    if cross_link_regex:
        print(f"[Renderer] Cross-linking engine loaded with {len(name_to_id)} taxonomy keywords.")

    md_files = list(VALIDATED_DIR.glob("*.md"))
    processed_count = 0

    for md_path in md_files:
        doc_id = md_path.stem
        
        # Taxonomy에서 제목 추출
        tax_info = taxonomy.get(doc_id, {})
        title = tax_info.get("display_name", doc_id.title())
        audience = tax_info.get("audience", "app")

        # [필터링 안전장치] app-guide인데 내부 전용 모듈이면 스킵
        if args.tier == "app" and audience == "platform":
            continue

        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 1. 문서 간 교차 링크(Cross-Linking) 적용
        if cross_link_regex:
            # lambda를 사용하여 매칭 그룹과 name_to_id를 replacer에 전달
            content = cross_link_regex.sub(lambda m: cross_link_replacer(m, name_to_id), content)

        # 2. 더미 Doxygen 링크 하단 부착
        doxygen_link_block = f"\n\n---\n\n> 🔗 **API Reference**: [View Original Documentation]({DUMMY_DOXYGEN_BASE}{doc_id})\n"
        content += doxygen_link_block

        # 3. Frontmatter 주입
        template = Template(FRONTMATTER_TEMPLATE)
        frontmatter = template.render(doc_id=doc_id, title=title)
        
        final_markdown = frontmatter + content

        # 출력 파일 저장
        out_file = output_dir / f"{doc_id}.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(final_markdown)
        processed_count += 1

    print(f"[Renderer] Successfully rendered {processed_count} files for Docusaurus v3.")
    print("=================================================================")

if __name__ == "__main__":
    main()

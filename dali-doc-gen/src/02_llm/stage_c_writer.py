import os
import json
import yaml
import argparse
from pathlib import Path
import sys

# Important: Append module path so it can import llm_client natively
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_client import LLMClient

# Context Directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
BLUEPRINTS_PATH = CACHE_DIR / "doc_blueprints" / "stage_b_blueprints.json"
PARSED_DOXYGEN_DIR = CACHE_DIR / "parsed_doxygen"
OUT_DRAFTS_DIR = CACHE_DIR / "markdown_drafts"
VALIDATED_DRAFTS_DIR = CACHE_DIR / "validated_drafts"
CHANGED_APIS_PATH = CACHE_DIR / "changed_apis.json"
TAXONOMY_PATH = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"
DOC_CONFIG_PATH = PROJECT_ROOT / "config" / "doc_config.yaml"
FEATURE_MAP_PATH = CACHE_DIR / "feature_map" / "feature_map.json"
CLASS_FEATURE_MAP_PATH = CACHE_DIR / "feature_map" / "class_feature_map.json"

def load_doc_config():
    if not DOC_CONFIG_PATH.exists():
        return {}
    with open(DOC_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def estimate_prompt_tokens(text):
    """JSON 직렬화 문자열의 토큰 수를 근사 추정한다 (chars / 3.5)."""
    return int(len(text) / 3.5)

def chunk_specs_by_class(specs, token_budget):
    """
    클래스 단위로 묶어서 청크 분할한다.
    같은 클래스의 메서드가 두 청크에 걸치지 않도록 보장한다.
    token_budget을 초과하면 새 청크를 시작한다.
    """
    # 클래스 이름(Dali::Actor::SetPos → Dali::Actor)별로 그룹화
    groups = {}
    for spec in specs:
        cls = "::".join(spec.get("name", "").split("::")[:-1]) or spec.get("name", "")
        groups.setdefault(cls, []).append(spec)

    chunks, current, current_tokens = [], [], 0
    for cls_specs in groups.values():
        size = estimate_prompt_tokens(json.dumps(cls_specs))
        if current and current_tokens + size > token_budget:
            chunks.append(current)
            current, current_tokens = [], 0
        current.extend(cls_specs)
        current_tokens += size

    if current:
        chunks.append(current)
    return chunks if chunks else [specs]

def build_rolling_initial_prompt(feat_name, outline, specs_chunk, covered_classes,
                                  total_classes, taxonomy_context, view_context, tier_context,
                                  chaining_context="", feature_hint_block=""):
    """롤링 정제 1차 호출 프롬프트: 전체 스펙의 일부만 받았음을 인지하고 초안 작성."""
    return f"""
    You are an elite C++ technical writer documenting the Samsung DALi GUI framework.
    Your task is to write the FIRST PASS of the documentation for the '{feat_name}' module.
    {view_context}
    {tier_context}
    {taxonomy_context}
    {chaining_context}
    {feature_hint_block}

    IMPORTANT — INCREMENTAL WRITING MODE:
    This batch covers class group {covered_classes} of {total_classes} total groups.
    More API specs will follow in subsequent passes.

    Rules for this pass:
    - Write COMPLETE sections for all classes provided in the specs below.
    - For sections in the outline that have NO specs in this batch, write the ## heading
      followed by exactly this placeholder on its own line: <!-- PENDING -->
    - Do NOT write a conclusion section yet.
    - Do NOT claim this document covers all APIs.

    Follow this Table of Contents structure:
    {json.dumps(outline, indent=2)}

    ANTI-HALLUCINATION RULE:
    Use ONLY the C++ API specs below. Do NOT invent APIs or parameters.
    CODE EXAMPLE STRICT RULE: Only call methods whose exact name appears in the specs below.
    {json.dumps(specs_chunk, indent=2)}

    WRITING STANDARD — each section must meet ALL of these:
    1. Every section starts with 1-2 sentences explaining the purpose in practical terms.
    2. For every non-trivial API method: what it does, when to call it, parameters, return value,
       and a complete compilable C++ code snippet showing realistic usage.
    3. Use > Note: or > Warning: blockquotes for non-obvious behavior.
    - Write entirely in valid GitHub Flavored Markdown.
    - Use ## for section titles and ### for sub-sections.
    - Output raw markdown text only. Do NOT wrap in ```markdown blocks.
    """

def build_rolling_refine_prompt(feat_name, existing_draft, specs_chunk, is_last):
    """롤링 정제 후속 호출 프롬프트: 기존 초안을 보존하면서 새 스펙 섹션만 보강."""
    final_instruction = (
        "This is the FINAL batch.\n"
        "- Replace ALL remaining <!-- PENDING --> placeholders with a note: "
        "'> Note: Full API details for this section are available in the platform guide.'\n"
        "- Write a proper ## Summary or ## Next Steps conclusion section at the end."
    ) if is_last else (
        "More spec batches will follow. "
        "Keep <!-- PENDING --> placeholders for sections that still have no specs in this batch."
    )

    return f"""
    You are enriching an existing documentation draft for the Samsung DALi '{feat_name}' module.

    [EXISTING DRAFT — PRESERVE ALL EXISTING CONTENT]
    {existing_draft}

    [NEW API SPECS TO INCORPORATE]
    {json.dumps(specs_chunk, indent=2)}

    ENRICHMENT RULES:
    - Find the <!-- PENDING --> placeholder in each section relevant to the new specs above.
    - Replace it with complete documentation for those classes (API coverage + code examples).
    - If no placeholder exists for a class, find the most logical existing section and INSERT.
    - Do NOT modify, rephrase, or "improve" any existing text unrelated to the new specs.
    - Do NOT rewrite sections that already have content — only fill placeholders or insert.
    - ANTI-HALLUCINATION: Only use method names that appear in the new specs above.
    {final_instruction}

    Output the COMPLETE updated markdown document.
    Output raw markdown text only. Do NOT wrap in ```markdown blocks.
    """

def run_rolling_refinement(feat_name, outline, specs, client,
                            taxonomy_context, view_context, tier_context,
                            context_limit, prompt_overhead,
                            chaining_context="", feature_hint_block=""):
    """
    토큰 예산 초과 feature를 다중 LLM 호출로 점진적으로 문서화한다.
    Pass 1: 첫 번째 클래스 그룹으로 초안 생성 (미처리 섹션에 PENDING 마커)
    Pass N: 기존 초안 + 다음 클래스 그룹 → 보강
    """
    # 1차 청크: 드래프트 없으므로 전체 예산의 60% 할당
    initial_spec_budget = int((context_limit - prompt_overhead) * 0.6)
    chunks = chunk_specs_by_class(specs, initial_spec_budget)
    total_chunks = len(chunks)

    print(f"    [Rolling] {len(specs)} specs → {total_chunks} chunk(s). Starting Pass 1/{total_chunks}...")

    # Pass 1
    draft = strip_markdown_wrapping(client.generate(
        build_rolling_initial_prompt(
            feat_name, outline, chunks[0],
            covered_classes=1, total_classes=total_chunks,
            taxonomy_context=taxonomy_context,
            view_context=view_context,
            tier_context=tier_context,
            chaining_context=chaining_context,
            feature_hint_block=feature_hint_block
        ),
        use_think=False
    ))

    # Pass 2~N
    for i, chunk in enumerate(chunks[1:], start=2):
        is_last = (i == total_chunks)
        draft_tokens = estimate_prompt_tokens(draft)
        remaining_budget = context_limit - prompt_overhead - draft_tokens

        # 드래프트 성장으로 남은 공간이 부족하면 현재 청크를 재분할
        chunk_tokens = estimate_prompt_tokens(json.dumps(chunk))
        if chunk_tokens > remaining_budget * 0.8:
            sub_chunks = chunk_specs_by_class(chunk, int(remaining_budget * 0.7))
            print(f"    [Rolling] Pass {i}: chunk too large ({chunk_tokens} tok, budget {remaining_budget}) "
                  f"→ re-split into {len(sub_chunks)} sub-chunk(s)")
            for j, sub in enumerate(sub_chunks):
                sub_is_last = is_last and (j == len(sub_chunks) - 1)
                print(f"    [Rolling] Pass {i}.{j+1}/{len(sub_chunks)}...")
                draft = strip_markdown_wrapping(client.generate(
                    build_rolling_refine_prompt(feat_name, draft, sub, sub_is_last),
                    use_think=False
                ))
        else:
            print(f"    [Rolling] Pass {i}/{total_chunks} ({'FINAL' if is_last else ''})...")
            draft = strip_markdown_wrapping(client.generate(
                build_rolling_refine_prompt(feat_name, draft, chunk, is_last),
                use_think=False
            ))

    return draft

def load_json(path):
    if not path.exists():
        print(f"Error: Required context file '{path}' missing.")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_api_specs(pkg_names, api_names_list, allowed_tiers=None,
                  owning_feature=None, class_feature_map=None):
    """
    Reverse Lookup Engine mapping arbitrary ambiguous node names back
    to precise C++ specification definitions pulled from Stage 1 Doxygen parsings.

    allowed_tiers: set of api_tier strings to include (e.g. {"public-api"}).
                   None means no filtering (all tiers included).
    owning_feature: 현재 생성 중인 feature 이름. class_feature_map과 함께 사용하면
                    다른 feature 소속 클래스를 foreign_classes로 분리한다.
    class_feature_map: {class_name: feature_name} 역매핑.

    반환: (specs, foreign_classes)
      specs: 이 feature에 포함할 스펙 목록
      foreign_classes: 다른 feature 소속으로 제외된 클래스 이름 목록
    """
    specs = []
    foreign_classes = []

    # Build a simple lookup set from api_names_list for faster matching
    api_name_set = set(a.split("::")[-1] for a in api_names_list)

    for pkg in pkg_names:
        pkg_path = PARSED_DOXYGEN_DIR / f"{pkg}.json"
        pkg_data = load_json(pkg_path)
        if not pkg_data:
            continue

        # Real schema is: {"package": "dali-core", "compounds": [...]}
        compounds = pkg_data.get("compounds", [])

        for comp in compounds:
            if not isinstance(comp, dict):
                continue

            # Tier 필터링: allowed_tiers가 지정된 경우 해당 tier만 포함
            if allowed_tiers and comp.get("api_tier") not in allowed_tiers:
                continue

            c_name = comp.get("name", "")

            # Match on class name (e.g. "Dali::Actor" contains "Actor")
            is_class_match = any(a in c_name for a in api_names_list) or \
                             any(c_name.split("::")[-1] in api_name_set for _ in [1])

            if not is_class_match:
                continue

            # class_feature_map이 있으면 다른 feature 소속 클래스를 foreign_classes로 분리
            # uncategorized_ambiguous_root는 "다른 feature 소유"가 아닌 "미분류" 상태이므로
            # owning_feature가 api_names에 명시한 경우 foreign 처리하지 않음
            if class_feature_map and owning_feature:
                mapped = class_feature_map.get(c_name)
                if mapped and mapped != owning_feature and mapped != "uncategorized_ambiguous_root":
                    foreign_classes.append(c_name)
                    continue

            if is_class_match:
                specs.append({
                    "name": c_name,
                    "kind": comp.get("kind", "class"),
                    "brief": comp.get("brief", "No description provided.")
                })

                # Granular function parameter lookups within matched class
                for mb in comp.get("members", []):
                    if not isinstance(mb, dict):
                        continue
                    mb_spec = {
                        "name": f"{c_name}::{mb.get('name', '')}",
                        "kind": mb.get("kind", "function"),
                        "brief": mb.get("brief", ""),
                        "signature": mb.get("signature", "")
                    }
                    if mb.get("params"):
                        mb_spec["params"] = mb["params"]
                    if mb.get("returns"):
                        mb_spec["returns"] = mb["returns"]
                    if mb.get("notes"):
                        mb_spec["notes"] = mb["notes"]
                    if mb.get("warnings"):
                        mb_spec["warnings"] = mb["warnings"]
                    if mb.get("code_examples"):
                        mb_spec["code_examples"] = mb["code_examples"]
                    # chainable 플래그: Fluent API setter 판별
                    # 조건: 반환 타입이 참조(&), const 아님, operator/Signal 제외
                    # e.g. "Label &" SetText → True
                    # e.g. "Actor &" operator= → False (operator 제외)
                    # e.g. "TouchEventSignalType &" TouchedSignal → False (Signal 제외)
                    ret_type = mb.get("type", "")
                    mb_name = mb.get("name", "")
                    if (ret_type.endswith("&")
                            and not ret_type.startswith("const")
                            and not mb_name.startswith("operator")
                            and not mb_name.endswith("Signal")):
                        mb_spec["chainable"] = True
                    specs.append(mb_spec)

    return specs, foreign_classes

def strip_markdown_wrapping(text):
    """
    Forces pure raw markdown content preventing API from mistakenly 
    double wrapping output in generic ```markdown chunks
    """
    stripped = text.strip()
    if stripped.startswith("```markdown"):
        stripped = stripped[11:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    elif stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()

def build_change_summary(feat_apis, changed_classes_info):
    """
    feature 의 API 목록에서 changed_apis.json 의 멤버 레벨 변경 정보를 추출하여
    사람이 읽기 쉬운 텍스트 요약을 생성합니다. (Stage C 패치 프롬프트용)
    """
    lines = []
    seen = set()

    for api_name in feat_apis:
        for key in [api_name, api_name.split("::")[-1]]:
            if key in changed_classes_info and key not in seen:
                seen.add(key)
                entry = changed_classes_info[key]
                cls_name = entry.get("class", key)

                if entry.get("class_change") == "added":
                    lines.append(f"Class `{cls_name}`: NEWLY ADDED to DALi API")
                    continue
                if entry.get("class_change") == "removed":
                    lines.append(f"Class `{cls_name}`: REMOVED from DALi API")
                    continue

                if entry.get("class_brief_changed"):
                    lines.append(f"Class `{cls_name}`: description updated")

                for m in entry.get("changed_members", []):
                    name = m["name"]
                    detail_parts = []
                    if "old_signature" in m:
                        detail_parts.append(
                            f"signature: `{m['old_signature']}` → `{m['new_signature']}`"
                        )
                    if "old_brief" in m:
                        detail_parts.append("doc comment updated")
                    detail = ", ".join(detail_parts) if detail_parts else "modified"
                    lines.append(f"  - `{name}`: MODIFIED ({detail})")

                for m in entry.get("added_members", []):
                    brief = m.get("new_brief", "")
                    sig = m.get("new_signature", "")
                    lines.append(f"  - `{m['name']}`: ADDED — {brief}"
                                 + (f" | signature: `{sig}`" if sig else ""))

                for m in entry.get("removed_members", []):
                    lines.append(f"  - `{m['name']}`: REMOVED — delete related description and examples")

    return "\n".join(lines) if lines else ""


def build_patch_prompt(feat_name, existing_draft, changed_specs, change_summary,
                       taxonomy_context, view_context, tier_context=""):
    """기존 문서를 최대한 보존하면서 변경된 API 부분만 수술하는 패치 프롬프트를 생성합니다. (원칙 3)"""
    change_section = (
        f"[WHAT CHANGED — UPDATE ONLY THESE PARTS]\n{change_summary}"
        if change_summary
        else "[CHANGED API SPECIFICATIONS — BASED ON LATEST SOURCE CODE]\n"
             + json.dumps(changed_specs, indent=2)
    )
    return f"""
    You are an elite C++ technical writer updating the Samsung DALi GUI framework documentation.
    Your task is to UPDATE the existing guide document for the '{feat_name}' module
    by incorporating only the changes described below.
    {view_context}
    {taxonomy_context}
    {tier_context}

    [EXISTING PUBLISHED GUIDE DOCUMENT — PRESERVE AS MUCH AS POSSIBLE]
    {existing_draft}

    {change_section}

    [LATEST API SPECS FOR REFERENCE]
    {json.dumps(changed_specs, indent=2)}

    STRICT PATCHING RULES:
    - Keep the existing document's section structure, writing style, and example code style exactly as-is.
    - Modify ONLY the parts of the document that correspond to the changes listed above.
    - Do NOT alter any content, examples, or explanations unrelated to those changes.
    - If a member is ADDED: insert it in the most appropriate existing section with a full explanation and code example.
    - If a member is REMOVED: delete only the description and examples for that specific member.
    - If a member is MODIFIED: update only the affected description, signature, or example — keep surrounding text.
    - Do NOT add any new top-level section such as 'API Updates', 'Changelog', 'What Changed', or 'What's New'.
    - Output the COMPLETE updated markdown document (not just the changed sections).
    - Output raw markdown text only. Do NOT wrap in ```markdown blocks.
    """


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Terminal isolation debug boundary.")
    parser.add_argument("--features", type=str, default="", help="Comma-separated list of features to process exclusively (full mode).")
    parser.add_argument("--patch", action="store_true", help="Patch mode: reuse existing draft, update only changed API sections.")
    parser.add_argument("--patch-features", type=str, default="", help="Comma-separated list of features to patch (used with --patch).")
    parser.add_argument("--tier", type=str, choices=["app", "platform"], default="app",
                        help="Documentation tier: 'app' (public-api only) or 'platform' (all tiers).")
    args = parser.parse_args()
    
    print("=================================================================")
    print(f" Initiating Stage C: Instruct Writer (Markdown Generation) [{args.tier.upper()}]")
    print("=================================================================")

    # token_overflow 설정 및 feature_hints 로드
    doc_config = load_doc_config()
    overflow_cfg = doc_config.get("token_overflow", {})
    SPEC_TOKEN_THRESHOLD = overflow_cfg.get("spec_token_threshold", 60000)
    CONTEXT_LIMIT = overflow_cfg.get("context_limit", 120000)
    PROMPT_OVERHEAD = overflow_cfg.get("prompt_overhead", 4000)
    feature_hints = doc_config.get("feature_hints", {})

    # 티어별 드래프트 출력 경로 및 API 필터
    tier_drafts_dir = OUT_DRAFTS_DIR / args.tier
    tier_drafts_dir.mkdir(parents=True, exist_ok=True)
    allowed_tiers = {"public-api"} if args.tier == "app" else None

    blueprints = load_json(BLUEPRINTS_PATH)
    if not blueprints:
        print("Blueprints corrupted. Aborting Markdown Generation.")
        return

    # Phase 1.5 taxonomy 로드
    taxonomy = {}
    if TAXONOMY_PATH.exists():
        taxonomy = load_json(TAXONOMY_PATH) or {}
        print(f"[Taxonomy] Loaded {len(taxonomy)} entries from feature_taxonomy.json")
    else:
        print("[Taxonomy] feature_taxonomy.json not found — proceeding without tree context.")

    # feature_map 로드 (suppress_doc / merge_into 판단용)
    feature_map_list = load_json(FEATURE_MAP_PATH) or []
    feature_map_index = {f["feature"]: f for f in feature_map_list}

    # class_feature_map 로드 (foreign_classes 필터링용)
    class_feature_map = {}
    if CLASS_FEATURE_MAP_PATH.exists():
        class_feature_map = load_json(CLASS_FEATURE_MAP_PATH) or {}
        print(f"[ClassMap] Loaded {len(class_feature_map)} class→feature mappings.")
    else:
        print("[ClassMap] class_feature_map.json not found — skipping foreign class filtering.")

    # merge_into 역매핑: target_feature → [source_feature, ...]
    # 예: {"view": ["actors"]}
    merge_sources = {}
    for f in feature_map_list:
        target = f.get("merge_into")
        if target and f.get("suppress_doc"):
            merge_sources.setdefault(target, []).append(f)

    client = LLMClient()
    OUT_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # ── 패치 모드: --patch-features 로 대상 결정 ───────────────────────────────
    if args.patch:
        patch_feature_list = [f.strip() for f in args.patch_features.split(",") if f.strip()]
        if patch_feature_list:
            blueprints = [bp for bp in blueprints if bp.get("feature") in patch_feature_list]
            print(f"[PATCH] Patch mode engaged: {len(blueprints)} feature(s) targeted: {patch_feature_list}")
        else:
            print("[PATCH] --patch set but --patch-features is empty. Processing all blueprints in patch mode.")

        # changed_apis.json 로드 — 멤버 레벨 변경 정보를 class 이름 기준 dict 로 인덱싱
        changed_apis_data = load_json(CHANGED_APIS_PATH) if CHANGED_APIS_PATH.exists() else {}
        changed_classes_info = {}  # key: full_name 또는 simple_name → entry dict
        for pkg_apis in changed_apis_data.values():
            for entry in pkg_apis:
                cls = entry.get("class", "")
                if cls:
                    changed_classes_info[cls] = entry
                    changed_classes_info[cls.split("::")[-1]] = entry
    else:
        # ── Full 생성 모드: --features 로 대상 결정 ──────────────────────────
        if args.features:
            target_features = [f.strip() for f in args.features.split(",") if f.strip()]
            if target_features:
                blueprints = [bp for bp in blueprints if bp.get("feature") in target_features]
                print(f"[!] TARGET MODE ENGAGED: Filtering to exclusively process {len(blueprints)} requested feature(s): {target_features}")

    if args.limit > 0:
        print(f"[!] TEST MODE ENGAGED: Hard limiting the loop to process only the first {args.limit} clusters.")
        blueprints = blueprints[:args.limit]
        
    for idx, bp in enumerate(blueprints):
        feat_name = bp.get("feature", "unknown")
        outline = bp.get("outline", [])
        packages = bp.get("packages", [])
        api_names = bp.get("apis", [])

        # 공통: Taxonomy 컨텍스트 조립
        tax_entry = taxonomy.get(feat_name, {})
        tree_decision = tax_entry.get("tree_decision", "flat")
        children = tax_entry.get("children", [])
        parent = tax_entry.get("parent", None)
        audience = tax_entry.get("audience", "app")

        taxonomy_context = ""
        if tree_decision == "tree" and children:
            child_list = ", ".join(f"`{c}`" for c in children)
            taxonomy_context = f"""
        DOCUMENT ROLE — PARENT OVERVIEW PAGE:
        This is the overview (parent) page for the '{feat_name}' feature family.
        Its child components ({child_list}) each have their own dedicated pages.
        Writing rules:
        - Introduce the overall concept and architecture of this feature family.
        - Describe each child component in 2-3 sentences and add a '→ See: [ChildName]' reference.
        - Do NOT write exhaustive API details for child components — just enough to understand when to use each.
        - Focus on how the parent and children relate structurally.
        """
        elif tree_decision == "leaf" and parent:
            taxonomy_context = f"""
        DOCUMENT ROLE — CHILD DETAIL PAGE:
        This is a focused detail page for '{feat_name}', which is a sub-component of '{parent}'.
        Writing rules:
        - Do NOT re-explain '{parent}' basics — readers have already read the parent page.
        - Focus entirely on what makes '{feat_name}' unique: its specific constructor, properties, signals.
        - Start with a 1-paragraph introduction explaining when to use '{feat_name}' over other {parent} variants.
        - Provide thorough code examples specific to '{feat_name}'.
        """
        elif audience == "platform":
            taxonomy_context = """
        DOCUMENT ROLE — PLATFORM DEVELOPER PAGE:
        This documentation targets platform/engine developers, NOT app developers.
        - Use technical C++ detail — do not simplify for beginners.
        - Explain internal architecture, thread safety, and lifecycle implications.
        - App developers use higher-level APIs (like View); this page covers the low-level layer.
        """

        view_context = ""
        if feat_name in ("actors", "views", "ui", "ui-components", "view") or \
           parent in ("view", "actors", "ui-components") or \
           any("View" in n or "Actor" in n for n in api_names):
            view_context = """
        CRITICAL ARCHITECTURE CONTEXT:
        All DALi UI code — including platform and app guides — must be based on dali-ui (Dali::Ui::*).
        Do NOT use raw Dali::Actor directly in any code example or explanation.
        Rules:
        - Always use Dali::Ui::View (or its subclasses) as the primary UI object.
        - To add a child UI element to a parent, use a named parent View reference:
            parentView.Add(childView);
          NEVER use 'this->Add(...)' in code examples — always show obtaining a view
          reference explicitly, then calling Add() on that reference.
        - Explain Actor-level behaviors (position, size, parent/child, signals) only
          as context for how Dali::Ui::View exposes or inherits them.
        - If a concept requires raw Actor, note it as an internal implementation detail
          and do not show it as the recommended usage pattern.
        """

        # ── 티어별 컨텍스트 ────────────────────────────────────────────────
        if args.tier == "app":
            tier_context = """
        TIER CONSTRAINT: This is app-guide documentation.
        ONLY reference and describe public-api classes and methods.
        Do NOT mention devel-api, integration-api, engine internals, or platform
        extension points. If a concept requires devel-api, note it briefly as
        'platform-level detail' and refer readers to the platform guide.
        """
        else:
            tier_context = """
        TIER CONSTRAINT: This is platform-guide documentation.
        Reference public-api, devel-api, and integration-api as needed.
        Explain engine internals, thread safety, lifecycle, and extension points
        in detail.
        """

        # ── 패치 모드 (원칙 3) ─────────────────────────────────────────────
        if args.patch:
            existing_draft_path = VALIDATED_DRAFTS_DIR / args.tier / f"{feat_name}.md"
            if not existing_draft_path.exists():
                # fallback: 티어 미분리 이전 경로
                existing_draft_path = VALIDATED_DRAFTS_DIR / f"{feat_name}.md"
            if not existing_draft_path.exists():
                print(f"\n[{idx+1}/{len(blueprints)}] PATCH SKIP '{feat_name}': No existing draft found. Run full mode first.")
                continue

            existing_draft = existing_draft_path.read_text(encoding="utf-8")

            # 최신 API 스펙 (참조용, 티어 필터 적용)
            specs, _ = get_api_specs(packages, api_names, allowed_tiers)

            # 멤버 레벨 변경 요약 생성
            change_summary = build_change_summary(api_names, changed_classes_info)

            print(f"\n[{idx+1}/{len(blueprints)}] PATCHING '{feat_name}' "
                  f"({len(specs)} API specs, change_summary={'yes' if change_summary else 'none'})...")

            prompt = build_patch_prompt(
                feat_name, existing_draft, specs, change_summary,
                taxonomy_context, view_context, tier_context
            )

        # ── Full 생성 모드 ─────────────────────────────────────────────────
        else:
            # suppress_doc 체크: taxonomy 또는 feature_map 어느 쪽이든 suppress이면 스킵
            fm_entry = feature_map_index.get(feat_name, {})
            if fm_entry.get("suppress_doc") or taxonomy.get(feat_name, {}).get("suppress_doc"):
                print(f"\n[{idx+1}/{len(blueprints)}] SKIP '{feat_name}': suppress_doc=true")
                continue

            if not outline:
                print(f"\n[{idx+1}/{len(blueprints)}] Skipping '{feat_name}': No outline blueprints detected.")
                continue

            print(f"\n[{idx+1}/{len(blueprints)}] Drafting comprehensive Markdown page for '{feat_name}'...")

            specs, foreign_classes = get_api_specs(
                packages, api_names, allowed_tiers,
                owning_feature=feat_name,
                class_feature_map=class_feature_map if class_feature_map else None
            )

            # 이 티어에 스펙이 없으면 .notier 마커 파일만 남기고 스킵
            if not specs:
                print(f"    [SKIP] '{feat_name}': no {args.tier} specs — writing .notier marker.")
                (tier_drafts_dir / f"{feat_name}.notier").touch()
                continue

            print(f"    [+] Joined {len(specs)} factual C++ parameter structures from Doxygen mappings.")
            if foreign_classes:
                print(f"    [!] Excluded {len(foreign_classes)} foreign-feature class(es): {foreign_classes[:5]}"
                      + (" ..." if len(foreign_classes) > 5 else ""))

            # ── merge_into 처리: 이 feature가 다른 feature의 통합 대상인 경우 ──
            inherited_specs = []
            inherited_context = ""
            sources = merge_sources.get(feat_name, [])
            if sources:
                for src in sources:
                    src_specs_raw, _ = get_api_specs(
                        src.get("packages", []), src.get("apis", []),
                        allowed_tiers={"public-api"}
                    )
                    # View 메서드 이름 집합
                    view_method_names = {
                        s["name"].split("::")[-1]
                        for s in specs
                        if s.get("kind") != "class"
                    }
                    # View에 없는 것만 압축 형태(name+brief+signature)로 추출
                    gap_specs = [
                        {"name": s["name"],
                         "brief": s.get("brief", ""),
                         "signature": s.get("signature", "")}
                        for s in src_specs_raw
                        if s.get("kind") != "class"
                        and s["name"].split("::")[-1] not in view_method_names
                    ]
                    inherited_specs.extend(gap_specs)
                    print(f"    [+] Inherited from '{src['feature']}': "
                          f"{len(gap_specs)} API(s) not in {feat_name} "
                          f"(of {len(src_specs_raw)} total)")

            if inherited_specs:
                inherited_context = f"""
        INHERITED API CONTEXT (from base class — NOT defined in {feat_name} directly):
        The following APIs exist on the base class but are NOT part of {feat_name}'s own API.
        {feat_name} inherits them. Rules:
        - Do NOT write dedicated ## sections for these — weave into existing sections naturally.
        - Mention them briefly when relevant (e.g., "inherited SetColor() controls opacity").
        - Always use {feat_name} references in code examples, not the raw base class.
        - If an inherited API has no practical relevance to {feat_name} usage, skip it.
        {json.dumps(inherited_specs, indent=2)}
        """

            # foreign_classes 제외 지시 (spec 오염 방지)
            foreign_context = ""
            if foreign_classes:
                foreign_list = "\n".join(f"  - {c}" for c in foreign_classes)
                foreign_context = f"""
        SCOPE BOUNDARY — DO NOT DOCUMENT THESE CLASSES:
        The following classes appear in the codebase but belong to OTHER feature documents.
        Do NOT describe, mention in detail, or write code examples using them:
{foreign_list}
        """

            # ── chaining 스타일 지시 조립 ────────────────────────────────────────
            # specs 중 chainable 플래그가 하나라도 있으면 체이닝 스타일을 권장,
            # 없으면 void 반환임을 명시하여 dali-core 등에서 오용 방지
            has_chaining = any(s.get("chainable") for s in specs)
            if has_chaining:
                chaining_context = """
        CODE EXAMPLE STYLE — METHOD CHAINING:
        This feature's setter methods return a reference to the object (marked "chainable": true in specs).
        ALWAYS prefer the chained initialization style in code examples:
            auto view = ComponentName::New()
              .SetProperty1(value1)
              .SetProperty2(value2);
        Do NOT use separate-statement style for chainable setters unless showing a specific
        multi-step workflow where intermediate state must be captured.
        """
            else:
                chaining_context = """
        CODE EXAMPLE STYLE:
        This feature's setters return void. Use separate statements for each setter call.
        Do NOT attempt to chain setter calls on this feature's objects.
        """

            # ── feature_hints 주입 ───────────────────────────────────────────────
            hint_extra = feature_hints.get(feat_name, {}).get("extra_context", "")
            feature_hint_block = f"""
        FEATURE-SPECIFIC GUIDANCE:
        {hint_extra}
        """ if hint_extra else ""

            # ── 토큰 초과 여부 판단: taxonomy oversized_single 또는 토큰 추정값 기반 ──
            tax_entry = taxonomy.get(feat_name, {})
            specs_token_estimate = estimate_prompt_tokens(json.dumps(specs))
            use_rolling = tax_entry.get("oversized_single", False) or specs_token_estimate > SPEC_TOKEN_THRESHOLD

            if use_rolling:
                print(f"    [!] Specs token estimate: {specs_token_estimate:,} "
                      f"(threshold: {SPEC_TOKEN_THRESHOLD:,}) — switching to rolling refinement mode.")
                clean_md = run_rolling_refinement(
                    feat_name, outline, specs, client,
                    taxonomy_context, view_context, tier_context,
                    CONTEXT_LIMIT, PROMPT_OVERHEAD,
                    chaining_context=chaining_context,
                    feature_hint_block=feature_hint_block
                )
            else:
                prompt = f"""
        You are an elite C++ technical writer documenting the Samsung DALi GUI framework.
        Your task is to write the COMPLETE and DETAILED Markdown documentation for the '{feat_name}' module.
        {view_context}
        {tier_context}
        {taxonomy_context}
        {foreign_context}
        {chaining_context}
        {feature_hint_block}

        FOCUS AND SCOPE RULES:
        - Write ONLY about '{feat_name}'. Stay strictly within its feature boundary.
        - If you mention a parent class, do so only to show how '{feat_name}' inherits
          or extends it — 1-2 sentences maximum.
        - If you mention a sibling component, write 1 sentence and add
          '→ See: [SiblingName]' — do not write its API details here.
        - Begin the document with a 1-2 paragraph overview that specifically answers:
          "What is {feat_name}?", "When should I use it?", "What makes it distinct?"

        Follow this Table of Contents structure exactly:
        {json.dumps(outline, indent=2)}

        ANTI-HALLUCINATION RULE:
        Use ONLY the C++ API specs below for all signatures, parameter types, and return values.
        Do NOT invent non-existent APIs or parameters.
        CODE EXAMPLE STRICT RULE: In every code example, you may ONLY call methods whose exact
        name appears in the API specs list below. If a method name is not listed, do NOT use it —
        not even if it sounds plausible (e.g. do not use MoveTo if only AnimateTo is listed).
        {json.dumps(specs, indent=2)}
        {inherited_context}

        WRITING STANDARD — each section and subsection must meet ALL of these:
        1. INTRODUCTION PARAGRAPH: Every section starts with 1-2 sentences explaining
           the overall purpose of that section in practical terms.
        2. API METHOD COVERAGE: For every non-trivial API method in this feature,
           write naturally flowing prose that covers:
           - What the method does (integrate into the explanation, do NOT use "What:" labels)
           - When and why a developer would call it (weave into context naturally)
           - Each parameter's name, type, and meaning (explain in sentences)
           - Return value and any important side effects, preconditions, or errors
           - A complete, compilable C++ code snippet showing realistic usage
           IMPORTANT: Do NOT use explicit labels like "What:", "Why:", "How:", "Code:".
           Instead, write smooth, professional technical prose where this information
           flows naturally. Use subheadings (###) to organize, not inline labels.
        3. SUBSECTION DEPTH: Each ### subsection must be self-contained. A developer
           reading only that subsection should be able to use that API correctly.
        4. CODE EXAMPLES: Every section must contain at least one realistic code example.
           Show the full context: create the object, configure it, add it to scene, etc.
        5. NOTES AND WARNINGS: Use blockquotes (> Note: or > Warning:) for non-obvious
           behavior, performance implications, or deprecated APIs.
        6. COMPLETENESS GOAL: A developer reading only this document should be able to
           write a basic working application using the '{feat_name}' feature.
        - Write entirely in valid GitHub Flavored Markdown.
        - Use ## for section titles and ### for sub-sections.
        - Output raw markdown text only. Do NOT wrap in ```markdown blocks.
        """
                clean_md = strip_markdown_wrapping(client.generate(prompt, use_think=False))

        out_file = tier_drafts_dir / f"{feat_name}.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(clean_md)

        mode_label = "[PATCH]" if args.patch else "[DRAFT]"
        print(f"    [+] {mode_label} Documentation exported → {out_file.relative_to(CACHE_DIR)}")
        
    print(f"\n=================================================================")
    print(f" Stage C Complete! Native markdown drafts exported to:")
    print(f" {tier_drafts_dir}")
    print("=================================================================")

if __name__ == "__main__":
    main()

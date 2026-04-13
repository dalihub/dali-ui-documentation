import os
import re
import json
import yaml
import argparse
import shutil
from pathlib import Path
import sys

# Important: Append module path so it can import llm_client natively
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_client import LLMClient

# Context Directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
PARSED_DOXYGEN_DIR = CACHE_DIR / "parsed_doxygen"
OUT_DRAFTS_DIR = CACHE_DIR / "markdown_drafts"
VALIDATED_DRAFTS_DIR = CACHE_DIR / "validated_drafts"
CHANGED_APIS_PATH = CACHE_DIR / "changed_apis.json"
TAXONOMY_PATH = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"
DOC_CONFIG_PATH = PROJECT_ROOT / "config" / "doc_config.yaml"
FEATURE_MAP_PATH = CACHE_DIR / "feature_map" / "feature_map.json"
CLASS_FEATURE_MAP_PATH = CACHE_DIR / "feature_map" / "class_feature_map.json"
CODE_BLOCK_RESULTS_DIR = CACHE_DIR / "code_block_results"

# Phase 2: 2-Pass 코드 생성 설정
MAX_CODE_RETRY = 5   # 배치 재전송 최대 횟수

# ── 모듈 레벨 컴파일 정규식 (함수 호출마다 재컴파일 방지) ──────────────────
_RE_SIG_TYPE    = re.compile(r'\b(?:Ui::)?([A-Z][A-Za-z0-9_]+)(?:::Type)?\b')
_RE_ENUM_PARAM  = re.compile(r'\b([A-Z][A-Za-z0-9_]+)(?:::Type|::Filter|::Mode)?\b')
_RE_BLOCK_LABEL = re.compile(r'\[BLOCK_(\d+)\]', re.IGNORECASE)
_RE_SCOPE_SYM   = re.compile(r'\b(?:Dali::Ui::|Dali::)?[A-Z][A-Za-z0-9_]*(?:::[A-Za-z0-9_]+)+')
_RE_VAR_DECL    = re.compile(
    r'((?:Dali::Ui::|Dali::)?[A-Z][A-Za-z0-9_]*(?:::[A-Za-z0-9_]+)*)\s*&?\s+'
    r'([a-z_][a-zA-Z0-9_]*)\s*[=;{(,)]'
)
_RE_DOT_CALL    = re.compile(r'\b([a-z_][a-zA-Z0-9_]*)\.([A-Z][a-zA-Z0-9_]+)\s*\(')
# ──────────────────────────────────────────────────────────────────────────────

# Phase 3: 네임스페이스 Strip 헬퍼
def _strip_dali_prefix(symbol: str) -> str:
    """
    Dali::Ui::X → X, Dali::X → X 변환.
    'using namespace Dali; using namespace Dali::Ui;' 가정 하에
    짧은 이름으로 검증할 때 사용.
    Dali::Ui:: 를 먼저 처리해야 Dali::Ui::Text::Alignment 가 올바르게 변환된다.
    """
    if symbol.startswith("Dali::Ui::"):
        return symbol[len("Dali::Ui::"):]
    if symbol.startswith("Dali::"):
        return symbol[len("Dali::"):]
    return symbol


def _symbol_aliases(symbol: str) -> list:
    """
    심볼에 대한 검증용 alias 목록을 반환합니다 (원본 제외).
    1. Dali::Ui:: / Dali:: 접두사 strip
    2. ::Type:: 중간 레이어 skip
       ex) LoadPolicy::Type::IMMEDIATE → LoadPolicy::IMMEDIATE
    """
    aliases = set()
    stripped = _strip_dali_prefix(symbol)
    if stripped != symbol:
        aliases.add(stripped)
    for s in [symbol, stripped]:
        if "::Type::" in s:
            no_type = s.replace("::Type::", "::")
            aliases.add(no_type)
            stripped_no_type = _strip_dali_prefix(no_type)
            if stripped_no_type != no_type:
                aliases.add(stripped_no_type)
    aliases.discard(symbol)
    return list(aliases)

# Actor에서 상속받은 메서드 중 View 파생 클래스에서 실제로 쓰일 법한 것만 허가
# (Permitted List의 INHERITED METHODS 섹션에 출력되며, full_names DB에도 alias로 등록된다)
ACTOR_INHERITED_METHODS = {
    "Add", "Remove", "Unparent",
    "GetParent", "GetChildCount", "GetChildAt",
    "FindChildByName",
    "Raise", "Lower", "RaiseToTop", "LowerToBottom",
    "SetResizePolicy", "GetResizePolicy",
    "GetNaturalSize", "GetTargetSize",
}


def _build_inheritance_aliases(parsed_doxygen_dir) -> set:
    """
    모든 parsed_doxygen JSON을 읽어 상속 체인을 재귀 탐색하고,
    부모 클래스의 메서드를 자식 클래스 이름으로 alias한 full_names 집합을 반환한다.

    예) Dali::Ui::ImageView → Dali::Ui::View → Dali::Actor
        → "ImageView::Add", "View::Add" 등을 full_names에 추가

    cross-package 상속 대응:
      base_classes에 단축명("CustomActor")이 들어있는 경우
      전체 compounds 맵에서 short name으로도 탐색한다.
    """
    # 1. 전체 compounds를 full_name → comp 맵으로 수집
    all_comps: dict = {}   # full_name → comp dict
    short_to_full: dict = {}  # short_name → [full_name, ...]

    for pkg_json in Path(parsed_doxygen_dir).glob("*.json"):
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for comp in data.get("compounds", []):
            cn = comp.get("name", "")
            if not cn:
                continue
            all_comps[cn] = comp
            short = cn.split("::")[-1]
            short_to_full.setdefault(short, []).append(cn)

    def resolve_base(base_name: str):
        """단축명/full name 모두 시도해 comp dict 반환."""
        if base_name in all_comps:
            return all_comps[base_name]
        # short name 탐색
        candidates = short_to_full.get(base_name, [])
        if candidates:
            return all_comps[candidates[0]]
        return None

    def collect_ancestor_members(class_name: str, visited: set) -> list:
        """재귀적으로 부모 클래스 메서드 이름 목록을 수집한다."""
        if class_name in visited:
            return []
        visited.add(class_name)
        comp = resolve_base(class_name)
        if comp is None:
            return []
        members = [mb.get("name", "") for mb in comp.get("members", []) if mb.get("name")]
        for base in comp.get("base_classes", []):
            members.extend(collect_ancestor_members(base, visited))
        return members

    # 2. 각 클래스에 대해 상속받은 메서드를 alias로 추가
    alias_set: set = set()
    for cn, comp in all_comps.items():
        bases = comp.get("base_classes", [])
        if not bases:
            continue
        inherited = []
        for base in bases:
            inherited.extend(collect_ancestor_members(base, set()))
        short_cn = _strip_dali_prefix(cn)
        for mn in inherited:
            if mn.startswith("~") or mn.startswith("operator") or not mn:
                continue
            full_sym = f"{cn}::{mn}"
            short_sym = f"{short_cn}::{mn}"
            alias_set.add(full_sym)
            alias_set.add(short_sym)
            alias_set.update(_symbol_aliases(full_sym))

    return alias_set


def _build_typedef_aliases(parsed_doxygen_dir) -> set:
    """
    `using Alias = OriginalType` 선언을 읽어 alias 심볼 집합을 반환한다.

    예) Dali::Ui::Text::FontWeight = Dali::TextAbstraction::FontWeight::Type
        → FontWeight::Type 의 enum 값(BOLD, REGULAR 등)을 다음 경로로 등록:
          "Text::FontWeight::BOLD", "FontWeight::BOLD"

    doxygen_parser.py 가 typedef memberdef 의 <type> 요소를 `aliased_type` 필드로
    저장해야 동작한다.  해당 필드가 없는 typedef는 무시한다.

    주의: 같은 이름의 compound가 여러 번 등장할 수 있으므로(Doxygen이 namespace를
    파일별로 분리 출력) 단순 dict 덮어쓰기를 피하고 전체 목록을 탐색한다.
    """
    # 이름 → compound 목록 (동일 이름이 여러 번 나올 수 있음)
    comps_by_name: dict = {}
    typedef_entries: list = []  # (container_full_name, alias_name, aliased_type)

    for pkg_json in Path(parsed_doxygen_dir).glob("*.json"):
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for comp in data.get("compounds", []):
            cn = comp.get("name", "")
            if not cn:
                continue
            comps_by_name.setdefault(cn, []).append(comp)
            for mb in comp.get("members", []):
                if mb.get("kind") != "typedef":
                    continue
                aliased_type = mb.get("aliased_type", "")
                alias_name = mb.get("name", "")
                if aliased_type and alias_name:
                    typedef_entries.append((cn, alias_name, aliased_type))

    # 단축명 → [전체명] 역매핑 (cross-package 조회용)
    short_to_full: dict = {}
    for cn in comps_by_name:
        parts = cn.split("::")
        for i in range(len(parts)):
            key = "::".join(parts[i:])
            short_to_full.setdefault(key, []).append(cn)

    def find_comp(type_name: str):
        """aliased_type 문자열로 compound 객체(첫 번째 일치)를 반환한다."""
        stripped = _strip_dali_prefix(type_name)
        for candidate in (type_name, stripped):
            comps = comps_by_name.get(candidate)
            if comps:
                return comps[0]
        for candidate in (type_name, stripped):
            hits = short_to_full.get(candidate, [])
            if hits:
                return comps_by_name[hits[0]][0]
        return None

    alias_set: set = set()

    for container_cn, alias_name, aliased_type in typedef_entries:
        aliased_comp = find_comp(aliased_type)
        if aliased_comp is None:
            continue

        # alias의 경로 변형: 전체 / Dali:: strip
        # alias_leaf(FontWeight 단독)는 제외 — using namespace Dali::Ui::Text; 를 가정해야만
        # 유효한 형태이므로 우리 스타일 규칙과 맞지 않음
        alias_full = f"{container_cn}::{alias_name}"       # Dali::Ui::Text::FontWeight
        alias_short = _strip_dali_prefix(alias_full)        # Text::FontWeight

        # aliased compound의 enum값/변수를 alias 경로 아래에 등록
        for child_mb in aliased_comp.get("members", []):
            child_name = child_mb.get("name", "")
            if not child_name or child_mb.get("kind") not in ("enumvalue", "variable"):
                continue
            for prefix in (alias_full, alias_short):
                sym = f"{prefix}::{child_name}"
                alias_set.add(sym)
                alias_set.update(_symbol_aliases(sym))

        # alias 타입 자체도 등록
        for sym in (alias_full, alias_short):
            alias_set.add(sym)
            alias_set.update(_symbol_aliases(sym))

    return alias_set


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
                                  chaining_context="", feature_hint_block="",
                                  permitted_method_block="", code_example_strategy=""):
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
    {permitted_method_block}
    {code_example_strategy}
    {json.dumps(specs_chunk, indent=2)}

    WRITING STANDARD — each section must meet ALL of these:
    1. Every section starts with 1-2 sentences explaining the purpose in practical terms.
    2. For every non-trivial API method: what it does, when to call it, parameters, return value,
       and a complete compilable C++ code snippet showing realistic usage.
    3. Use > Note: or > Warning: blockquotes for non-obvious behavior.
    - Write entirely in valid GitHub Flavored Markdown.
    - Use ## for section titles and ### for sub-sections.
    - Do NOT include an explicit Table of Contents list at the top of the document.
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
                            chaining_context="", feature_hint_block="",
                            permitted_method_block="", code_example_strategy=""):
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
            feature_hint_block=feature_hint_block,
            permitted_method_block=permitted_method_block,
            code_example_strategy=code_example_strategy
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

    # ── Secondary enum scan: 메서드 시그니처에서 참조된 enum 타입을 추가 로드 ──
    # ex) SetFittingMode(Ui::FittingMode::Type) → FittingMode::Type compound 로드
    # → build_permitted_method_list에서 enum value 그룹을 생성할 수 있게 됨
    referenced_types = set()
    for s in specs:
        sig = s.get("signature", "")
        if sig:
            for m in _RE_SIG_TYPE.finditer(sig):
                referenced_types.add(m.group(1))
    # 이미 포함된 compound 이름(simple)은 제외
    existing_simples = {s["name"].split("::")[-2] if "::" in s["name"] else s["name"]
                        for s in specs if s.get("kind") in ("class", "struct", "enumvalue")}

    for pkg in pkg_names:
        pkg_path = PARSED_DOXYGEN_DIR / f"{pkg}.json"
        pkg_data = load_json(pkg_path)
        if not pkg_data:
            continue
        for comp in pkg_data.get("compounds", []):
            if not isinstance(comp, dict):
                continue
            if allowed_tiers and comp.get("api_tier") not in allowed_tiers:
                continue
            c_name = comp.get("name", "")
            parts = c_name.split("::")
            simple = parts[-1]
            parent_simple = parts[-2] if len(parts) >= 2 else ""
            # 참조된 타입이거나 그 Type 하위 compound인 경우만
            if simple not in referenced_types and parent_simple not in referenced_types:
                continue
            ev_members = [mb for mb in comp.get("members", [])
                          if isinstance(mb, dict) and mb.get("kind") == "enumvalue"]
            if not ev_members:
                continue
            if parent_simple in existing_simples or simple in existing_simples:
                continue
            for mb in ev_members:
                specs.append({
                    "name": f"{c_name}::{mb.get('name', '')}",
                    "kind": "enumvalue",
                    "brief": mb.get("brief", "")
                })

    return specs, foreign_classes

def build_permitted_method_list(specs):
    """
    specs에서 호출 가능한 메서드 이름만 추출하여 프롬프트용 허용 목록 블록을 반환합니다.
    LLM이 specs JSON을 직접 파싱하지 않고도 사용 가능한 메서드를 명확히 인식하도록 합니다.
    메서드가 없으면 빈 문자열을 반환합니다.

    enum 인라인: 메서드 signature에 enum 파라미터가 있으면 첫 등장 시 값 목록을 인라인 표시.
        같은 enum 타입이 이후 메서드에 재등장하면 anchor("↳ EnumType: see above")만 표시해 토큰 절약.
    inherited methods: ACTOR_INHERITED_METHODS 화이트리스트를 별도 섹션으로 추가.
    setter 우선 규칙: SetProperty 남용 방지 및 "없는 메서드 창작 금지" 규칙 추가.
    """
    methods = sorted({
        s["name"].split("::")[-1]
        for s in specs
        if s.get("kind") == "function"
        and not s["name"].split("::")[-1].startswith("operator")
        and not s["name"].split("::")[-1].startswith("~")
    })

    # enum value를 부모 타입별로 그룹화 (set으로 자동 중복 제거)
    # Dali::Ui::FittingMode::Type::SCALE_TO_FILL → parent: FittingMode, value: SCALE_TO_FILL
    enum_groups: dict = {}
    for s in specs:
        if s.get("kind") != "enumvalue":
            continue
        parts = s["name"].split("::")
        if len(parts) < 2:
            continue
        value = parts[-1]
        if not value:
            continue
        parent_full = "::".join(parts[:-1])
        parent = _strip_dali_prefix(parent_full)
        # ::Type 접미사 제거 (LoadPolicy::Type → LoadPolicy)
        if parent.endswith("::Type"):
            parent = parent[:-len("::Type")]
        parent = parent.strip(":")
        if not parent:
            continue
        enum_groups.setdefault(parent, set()).add(value)

    if not methods and not enum_groups:
        return ""

    # signature에서 enum 파라미터 타입 추출 → 메서드별 인라인 힌트 맵 구성
    # signature 예: "(std::string url, FittingMode::Type fit, SamplingMode::Filter smp)"
    # method_name → [enum_parent, ...] (enum_groups에 있는 것만)
    method_enum_hints: dict = {}
    for s in specs:
        if s.get("kind") != "function":
            continue
        mname = s["name"].split("::")[-1]
        if mname.startswith("operator") or mname.startswith("~"):
            continue
        sig = s.get("signature", "")
        hints = []
        for m in _RE_ENUM_PARAM.finditer(sig):
            candidate = m.group(1)
            if candidate in enum_groups:
                hints.append(candidate)
        if hints:
            method_enum_hints.setdefault(mname, [])
            for h in hints:
                if h not in method_enum_hints[mname]:
                    method_enum_hints[mname].append(h)

    result = "CRITICAL CONSTRAINT - PERMITTED API CALLS ONLY:\n"
    if methods:
        result += (
            "        You are strictly bounded to the following complete list of callable methods for this feature.\n"
            "        - NEVER use, invent, or assume the existence of any method not explicitly listed here.\n"
            "        - (e.g., SetVisible, Show, Hide, SetSize etc. must NEVER be used unless they are explicitly present in this list).\n"
            "        - Using a non-permitted method will trigger a FATAL pipeline validation failure.\n"
            # setter 우선 규칙 및 없는 메서드 창작 금지
            "        - Prefer dedicated setter/getter methods over SetProperty/GetProperty.\n"
            "          If a method you need is not listed here, search this list for related terms — do NOT invent methods.\n"
            "        Permitted Methods:\n"
        )
        # enum 인라인 — 첫 등장에 값 표시, 이후엔 anchor만 (토큰 절약)
        seen_enums: set = set()
        for m in methods:
            result += f"          - {m}\n"
            hints = method_enum_hints.get(m, [])
            for enum_parent in hints:
                if enum_parent not in seen_enums:
                    vals = ", ".join(sorted(enum_groups[enum_parent]))
                    result += f"              ↳ {enum_parent} values: {vals}\n"
                    seen_enums.add(enum_parent)
                else:
                    result += f"              ↳ {enum_parent}: see above\n"
        result += "\n"

    # Actor 상속 메서드 섹션 — View 파생 클래스에서 공통으로 사용 가능
    result += (
        "        INHERITED METHODS (from Actor, available on all View-derived classes):\n"
        "          Add(View child), Remove(View child), Unparent()\n"
        "          GetParent() -> View, GetChildCount() -> uint32_t, GetChildAt(uint32_t) -> View\n"
        "          FindChildByName(std::string) -> View\n"
        "          Raise(), Lower(), RaiseToTop(), LowerToBottom()\n"
        "          SetResizePolicy(ResizePolicy::Type, Dimension::Type), GetResizePolicy(Dimension::Type)\n"
        "          GetNaturalSize() -> Vector3, GetTargetSize() -> Vector3\n\n"
    )

    if enum_groups:
        result += (
            "        PERMITTED ENUM VALUES — ONLY these values exist. Using any other value is a hallucination:\n"
            + "\n".join(
                f"          {parent}: {', '.join(sorted(vals))}"
                for parent, vals in sorted(enum_groups.items())
                if vals
            ) + "\n\n"
        )
    has_view_or_actor = any(
        ("View" in s["name"] or "Actor" in s["name"])
        for s in specs
        if s.get("kind") in ("class", "function", "enumvalue")
    )
    terminology_block = (
        "        CRITICAL CONSTRAINT - TERMINOLOGY OVERRIDE (ACTOR -> VIEW):\n"
        "        In DALi, 'View' is the official high-level UI object that replaces 'Actor'.\n"
        "        Therefore, in ALL natural language explanations AND code examples:\n"
        "        - Replace the word 'Actor' or 'Actors' with 'View' or 'Views'.\n"
        "        - Replace the class type 'Actor' with 'View' (e.g. View::New(), not Actor::New()).\n"
        "        - Do NOT declare or use 'Actor actor = ...' or 'Dali::Actor actor = ...'.\n"
        "          Instead use: View view = View::New();\n"
        "        - CRITICAL EXCEPTION — Actor::Property enum values:\n"
        "          Position, size, and visibility properties belong to Actor::Property, NOT View::Property.\n"
        "          View::Property has NO POSITION, SIZE, or VISIBLE members.\n"
        "          You MUST write: Actor::Property::POSITION (NOT View::Property::POSITION)\n"
        "                          Actor::Property::SIZE    (NOT View::Property::SIZE)\n"
        "          Do NOT substitute 'Actor' with 'View' inside '::Property::' expressions.\n"
        if has_view_or_actor else ""
    )
    return result + (
        "        CRITICAL CONSTRAINT - USING NAMESPACE DECLARATIONS:\n"
        "        ALL C++ code examples MUST begin with exactly these two lines:\n"
        "          using namespace Dali;\n"
        "          using namespace Dali::Ui;\n"
        "        After these declarations, use SHORT names WITHOUT Dali:: or Dali::Ui:: prefix:\n"
        "        - Class declarations:  ImageView imageView = ImageView::New();  (NOT Dali::Ui::ImageView)\n"
        "        - Enum / Property:     Actor::Property::SIZE  (NOT Dali::Actor::Property::SIZE)\n"
        "        - Instance dot-calls:  imageView.SetResourceUrl(...)  (allowed after declaration above)\n"
        "        - NEVER use 'auto' as the declared type; always write the explicit type name.\n\n"
        "        CRITICAL CONSTRAINT - NO #include DIRECTIVES:\n"
        "        Do NOT write any #include lines in code examples.\n"
        "        You do not have access to DALi's internal file structure, and incorrect includes\n"
        "        will cause compilation errors. Omit all #include directives entirely.\n\n"
    ) + terminology_block


def is_enum_only_feature(specs):
    """specs에 호출 가능한 함수가 없으면 True (enum/struct 정의만 있는 feature)."""
    return not any(s.get("kind") == "function" for s in specs)


# ── Phase 2: 2-Pass 코드 생성 관련 함수 ──────────────────────────────────────

def build_slim_signatures(specs):
    """
    Pass 2 전용: specs에서 method signature 한 줄짜리 요약만 추출한다.
    Doxygen 풀 스펙(brief, params detail, notes 등)은 제외하여 토큰을 ~85% 절감한다.
    Phase 3: Dali:: / Dali::Ui:: 접두사를 strip하여 using namespace 스타일로 출력.

    반환 형태:
        ClassName::Method(type1 p1, type2 p2) -> ReturnType
    """
    lines = []
    for s in specs:
        if s.get("kind") not in ("function", "enumvalue", "class", "struct"):
            continue
        name = _strip_dali_prefix(s.get("name", ""))
        sig = s.get("signature", "")
        if sig:
            lines.append(f"  {name}{sig}")
        elif s.get("kind") == "function":
            lines.append(f"  {name}(...)")
        else:
            lines.append(f"  {name}")
    return "\n".join(lines)


def _parse_block_responses(response_text, num_blocks):
    """
    LLM이 [BLOCK_N] 구분자로 반환한 응답을 파싱하여
    {block_index: code_block_text} 딕셔너리로 반환한다.
    파싱 실패한 인덱스는 포함하지 않는다.
    """
    result = {}
    # [BLOCK_N] 헤더를 구분자로 분리
    parts = _RE_BLOCK_LABEL.split(response_text)
    # parts: ['preamble', '0', 'block0_content', '1', 'block1_content', ...]
    i = 1
    while i + 1 < len(parts):
        try:
            idx = int(parts[i])
            content = parts[i + 1].strip()
            if idx < num_blocks:
                result[idx] = content
        except (ValueError, IndexError):
            pass
        i += 2
    return result


def _verify_code_block(block_text, full_names, simple_names):
    """
    단일 코드 블록에서 심볼을 추출하여 검증한다.
    stage_d_validator의 로직을 간소화하여 인라인 사용.

    반환: (verified_list, unverified_list)
    """
    symbols = set()
    # ```cpp ... ``` 블록만 또는 전체 텍스트에서 추출
    code_blocks = re.findall(r'```(?:cpp|c\+\+)?\s*(.*?)\s*```', block_text, re.DOTALL | re.IGNORECASE)
    target = code_blocks if code_blocks else [block_text]
    for block in target:
        # Phase 3: Dali:: 전체 네임스페이스 및 CamelCase::Name 단축 이름 모두 추출
        for sym in _RE_SCOPE_SYM.findall(block):
            symbols.add(_strip_dali_prefix(sym))
        # dot-call 타입 추론 (Phase 3: CamelCase 선언도 처리)
        # "Type& varname" 레퍼런스 파라미터도 캡처 (함수 파라미터로 받은 View 타입 추론)
        var_type_map = {}
        for m in _RE_VAR_DECL.finditer(block):
            var_type_map[m.group(2)] = _strip_dali_prefix(m.group(1))
        for m in _RE_DOT_CALL.finditer(block):
            var_name, method = m.group(1), m.group(2)
            if var_name in var_type_map:
                symbols.add(f"{var_type_map[var_name]}::{method}")
            else:
                symbols.add(method)

    noise = {'Include', 'Note', 'Warning', 'True', 'False', 'nullptr',
             'Void', 'Return', 'This', 'Class', 'New', 'Delete', 'Public', 'Private'}
    symbols -= noise

    # 사용자 정의 클래스 심볼 스킵 (My 접두사 — 콜백 핸들러 등 앱 코드)
    # Pass 2 프롬프트가 My 접두사 사용을 강제하므로 이 클래스들은 DALi API 환각이 아님
    symbols = {s for s in symbols if not s.split("::")[0].startswith("My")}

    verified, unverified = [], []
    for sym in symbols:
        if '::' in sym:
            (verified if sym in full_names else unverified).append(sym)
        else:
            (verified if sym in simple_names else unverified).append(sym)
    return verified, unverified


def _build_batch_prompt(pending_blocks, slim_sigs, permitted_method_block):
    """
    Pass 2 배치 프롬프트 생성.
    pending_blocks: [(block_index, purpose_str, tag_type), ...]
      tag_type: "SAMPLE_CODE" | "INLINE_CODE"
    """
    block_lines = []
    for idx, purpose, tag_type in pending_blocks:
        if tag_type == "INLINE_CODE":
            block_lines.append(f"[BLOCK_{idx}] (inline) {purpose}")
        else:
            block_lines.append(f"[BLOCK_{idx}] (code block) {purpose}")
    blocks_text = "\n".join(block_lines)

    return f"""You are a C++ code example writer for the Samsung DALi GUI framework.

Write ONLY the C++ code blocks for each of the following tagged scenarios.

IMPORTANT RESPONSE FORMAT:
Two types of blocks exist — follow the format exactly for each type:

(code block) → output the label followed by a ```cpp ... ``` code block:
  [BLOCK_0]
  ```cpp
  // multi-line code here
  ```

(inline) → output the label followed by a SINGLE LINE symbol.
  - Method/function: write MethodName(Type1, Type2) — param types only, no variable names, no return type.
    If overloaded, choose the variant that best matches the surrounding prose context.
  - Enum value, property, or class name: write the symbol as-is.
  No backticks, no code fences, no explanation.
  [BLOCK_1]
  SetPositionX(float)

  [BLOCK_2]
  LoadPolicy::IMMEDIATE

Do NOT include any explanation or prose between blocks.

CRITICAL CONSTRAINT - USING NAMESPACE DECLARATIONS:
Every code block assumes the following declarations are already in effect (DO NOT write them):
  using namespace Dali;
  using namespace Dali::Ui;
Use SHORT names WITHOUT Dali:: or Dali::Ui:: prefix throughout:
  - Class declarations:  ImageView imageView = ImageView::New();  (NOT Dali::Ui::ImageView)
  - Enum / Property:     Actor::Property::SIZE  (NOT Dali::Actor::Property::SIZE)
  - Instance dot-calls:  imageView.SetResourceUrl(...)
  - NEVER use 'auto'; always write the explicit type name.
  - Do NOT write any #include lines.
  - Every code fence (``` or ```cpp) MUST start on its own line.

CRITICAL CONSTRAINT - ENUM VALUES:
  - All DALi enum values are written in SCREAMING_SNAKE_CASE (ALL_CAPS_WITH_UNDERSCORES).
  - NEVER use Pascal case or lower case for enum values.
  - CORRECT: NONE, SCALE_TO_FIT, POSITION_PROPORTIONAL
  - WRONG:   None, ScaleToFit, positionProportional

CRITICAL CONSTRAINT - USER-DEFINED CLASSES IN EXAMPLES:
  - When example code requires a user-defined class (e.g. a callback handler, app class),
    ALWAYS name it with a 'My' prefix: MyApp, MyHandler, MyView, MyCallback.
  - NEVER use other names (AppHandler, CustomView, Listener, etc.) for user-defined classes.

Scenarios to implement:
{blocks_text}

API Signatures (use ONLY these):
{slim_sigs}

{permitted_method_block}

OUTPUT: Respond with all blocks in order using the [BLOCK_N] format above."""


def generate_code_blocks_batch(feat_name, tags, specs, client,
                               full_names, simple_names, permitted_method_block):
    """
    Pass 2: 모든 SAMPLE_CODE 태그를 배치 LLM 호출로 처리한다.

    tags: [(tag_text, purpose_str, tag_type), ...]
      tag_type: "SAMPLE_CODE" | "INLINE_CODE"
    반환: {tag_index: text_or_None}
      - SAMPLE_CODE: 검증 통과한 코드 블록 텍스트
      - INLINE_CODE: 검증 통과한 한 줄 심볼 텍스트
      - None: MAX_CODE_RETRY 소진 후 최종 실패
    """
    slim_sigs = build_slim_signatures(specs)
    num_blocks = len(tags)

    # 초기 pending: 모든 태그 (idx, purpose, tag_type)
    pending = [(i, purpose, tag_type) for i, (_, purpose, tag_type) in enumerate(tags)]
    results = {}  # {index: text}
    block_history = [[] for _ in range(num_blocks)]  # 블록별 시도 기록

    for attempt in range(1, MAX_CODE_RETRY + 1):
        if not pending:
            break

        # 재시도 시 실패 원인 추가
        pending_with_hints = []
        for idx, purpose, tag_type in pending:
            hist = block_history[idx]
            if hist:
                last = hist[-1]
                unverified = last.get("unverified_symbols", [])
                if unverified:
                    hint = f"{purpose} [DO NOT USE: {', '.join(unverified)}]"
                else:
                    hint = purpose
            else:
                hint = purpose
            pending_with_hints.append((idx, hint, tag_type))

        print(f"    [Pass2] Attempt {attempt}/{MAX_CODE_RETRY}: "
              f"generating {len(pending)} block(s) for '{feat_name}'...")

        prompt = _build_batch_prompt(pending_with_hints, slim_sigs, permitted_method_block)
        try:
            response = client.generate(prompt, use_think=False)
        except Exception as e:
            print(f"    [Pass2] LLM call failed: {e}")
            for idx, _, _tt in pending:
                block_history[idx].append({
                    "attempt": attempt,
                    "verdict": "FAIL",
                    "unverified_symbols": [],
                    "error": str(e)
                })
            continue

        # 응답 파싱
        parsed = _parse_block_responses(response, num_blocks)

        still_failing = []
        for idx, purpose, tag_type in pending:
            block_text = parsed.get(idx)
            if block_text is None:
                print(f"    [Pass2] BLOCK_{idx}: parse failed — will retry.")
                block_history[idx].append({
                    "attempt": attempt,
                    "verdict": "FAIL",
                    "unverified_symbols": [],
                    "error": "parse_failed"
                })
                still_failing.append((idx, purpose, tag_type))
                continue

            # 심볼 검증
            # INLINE_CODE는 한 줄 텍스트이므로 cpp 펜스 없이 직접 검증
            if tag_type == "INLINE_CODE":
                verified, unverified = _verify_code_block(block_text, full_names, simple_names)
            else:
                verified, unverified = _verify_code_block(block_text, full_names, simple_names)

            if not unverified:
                results[idx] = block_text
                print(f"    [Pass2] BLOCK_{idx} [{tag_type}]: PASS (attempt {attempt})")
                block_history[idx].append({
                    "attempt": attempt,
                    "verdict": "PASS",
                    "verified_symbols": verified,
                    "unverified_symbols": []
                })
            else:
                print(f"    [Pass2] BLOCK_{idx} [{tag_type}]: FAIL "
                      f"(unverified: {unverified[:5]}) — will retry.")
                block_history[idx].append({
                    "attempt": attempt,
                    "verdict": "FAIL",
                    "verified_symbols": verified,
                    "unverified_symbols": unverified
                })
                still_failing.append((idx, purpose, tag_type))

        pending = still_failing

    # MAX_CODE_RETRY 소진 후 최종 실패 처리
    for idx, _, _tt in pending:
        print(f"    [Pass2] BLOCK_{idx}: final FAIL after {MAX_CODE_RETRY} attempts — tag will be removed.")
        results[idx] = None  # None = 태그 삭제
        if not block_history[idx]:
            block_history[idx].append({"attempt": MAX_CODE_RETRY, "verdict": "FAIL",
                                       "unverified_symbols": [], "error": "max_retry_exceeded"})

    return results, block_history


def run_two_pass_generation(feat_name, outline, specs, client,
                            taxonomy_context, view_context, tier_context,
                            context_limit, prompt_overhead,
                            chaining_context="", feature_hint_block="",
                            permitted_method_block="", code_example_strategy="",
                            full_names=None, simple_names=None,
                            tier="app",
                            use_rolling=False):
    """
    Phase 2: 2-Pass 문서 생성 오케스트레이터.

    Pass 1: 자연어 초안 생성 (코드 위치에 <!-- SAMPLE_CODE: ... --> 태그 삽입)
    Pass 2: 배치 LLM 호출로 태그 → 코드 블록 변환
            검증 실패 블록만 배치 재전송 (MAX_CODE_RETRY=5)
            최종 실패 블록은 태그 삭제 (Graceful Degradation)

    반환: (final_md, block_results_list)
      final_md: 최종 마크다운 (코드 삽입 완료)
      block_results_list: [{block_index, purpose, verdict, attempts, ...}, ...]
    """
    # ── Pass 1: 자연어 초안 생성 ──────────────────────────────────────────────
    pass1_instruction = (
        "\n        PASS 1 INSTRUCTION — NATURAL LANGUAGE ONLY:\n"
        "        Do NOT write any C++ code blocks (``` ... ```) in this pass.\n"
        "        Instead, wherever a code example would normally appear, insert a placeholder tag:\n"
        "          <!-- SAMPLE_CODE: <brief description of what the example should show> -->\n"
        "        The description should be one concise sentence stating which API/scenario to demonstrate.\n"
        "        All prose, explanations, tables, and notes should be written fully and completely.\n"
        "\n"
        "        CRITICAL — SELF-CONTAINED PROSE:\n"
        "        Do NOT write sentences that reference or depend on an upcoming code block.\n"
        "        WRONG: 'as shown below', 'see the following example', 'the code below demonstrates',\n"
        "               'refer to the snippet', 'the following code shows'\n"
        "        Every sentence must be complete and meaningful even if the code block is removed.\n"
        "        Code blocks are supplementary illustrations, not part of the explanation.\n"
        "\n"
        "        INLINE API REFERENCES — MANDATORY TAG USAGE:\n"
        "        EVERY method name, enum value, property name, or class name mentioned inline in prose\n"
        "        MUST use the <!-- INLINE_CODE: --> tag. Writing a symbol directly with backticks\n"
        "        (e.g. `SetPositionX`) bypasses validation and is STRICTLY FORBIDDEN.\n"
        "        Rules:\n"
        "          1. Write a complete sentence that makes sense WITHOUT the symbol.\n"
        "          2. Append <!-- INLINE_CODE: brief description of the symbol --> at the END of the sentence, after the period.\n"
        "        GOOD: 'The x-coordinate of a View can be set independently.<!-- INLINE_CODE: SetPositionX method -->'\n"
        "        GOOD: 'Immediate loading can be requested at creation time.<!-- INLINE_CODE: LoadPolicy::IMMEDIATE enum value -->'\n"
        "        BAD:  'Use <!-- INLINE_CODE: SetPositionX --> to set the position.'  (symbol is the subject)\n"
        "        BAD:  'The <!-- INLINE_CODE: SetPositionX --> method sets x.'  (tag in the middle)\n"
        "        BAD:  '`SetPositionX` sets the position.'  (direct backtick — FORBIDDEN)\n"
        "        BAD:  'Use `SetPositionX` ...'  (any backtick around a symbol — FORBIDDEN)\n"
        "        The sentence MUST remain grammatically complete if the tag is deleted entirely.\n"
    )

    if use_rolling:
        print(f"    [Pass1] Rolling refinement mode (large feature).")
        # 롤링 정제: Pass 1에 코드 생략 지시 추가
        # code_example_strategy에 pass1_instruction을 합산하여 전달
        combined_strategy = pass1_instruction + (code_example_strategy or "")
        draft = run_rolling_refinement(
            feat_name, outline, specs, client,
            taxonomy_context, view_context, tier_context,
            context_limit, prompt_overhead,
            chaining_context=chaining_context,
            feature_hint_block=feature_hint_block,
            permitted_method_block=permitted_method_block,
            code_example_strategy=combined_strategy
        )
    else:
        print(f"    [Pass1] Single-call natural language draft...")
        prompt = f"""
        You are an elite C++ technical writer documenting the Samsung DALi GUI framework.
        Your task is to write the COMPLETE and DETAILED Markdown documentation for the '{feat_name}' module.
        {view_context}
        {tier_context}
        {taxonomy_context}
        {chaining_context}
        {feature_hint_block}
        {pass1_instruction}

        Follow this Table of Contents structure exactly:
        {json.dumps(outline, indent=2)}

        ANTI-HALLUCINATION RULE:
        Use ONLY the C++ API specs below for all signatures, parameter types, and return values.
        Do NOT invent non-existent APIs or parameters.
        {permitted_method_block}
        {code_example_strategy}
        {json.dumps(specs, indent=2)}

        WRITING STANDARD — each section and subsection must meet ALL of these:
        1. INTRODUCTION PARAGRAPH: Every section starts with 1-2 sentences explaining the purpose.
        2. API METHOD COVERAGE: For every non-trivial API method, write naturally flowing prose covering
           what it does, when to call it, parameters, and return value.
        3. CODE EXAMPLES: Where a code example is needed, insert only the <!-- SAMPLE_CODE: ... --> tag.
           Do NOT write actual code blocks — they will be generated in the next pass.
        4. NOTES AND WARNINGS: Use blockquotes (> Note: or > Warning:) for non-obvious behavior.
        - Write entirely in valid GitHub Flavored Markdown.
        - Use ## for section titles and ### for sub-sections.
        - Do NOT include an explicit Table of Contents list at the top of the document.
        - Output raw markdown text only. Do NOT wrap in ```markdown blocks.
        """
        draft = strip_markdown_wrapping(client.generate(prompt, use_think=False))

    # ── Pass 2: 태그 파싱 → 배치 코드 생성 ────────────────────────────────────
    # SAMPLE_CODE: 여러 줄 코드블럭 생성
    # INLINE_CODE: 한 줄 심볼/표현식 생성 → 문장 끝 괄호로 치환
    all_tags = []  # [(tag_full, purpose, tag_type), ...]
    for m in re.finditer(r'<!-- (SAMPLE_CODE|INLINE_CODE): (.+?) -->', draft):
        all_tags.append((m.group(0), m.group(2).strip(), m.group(1)))

    block_results_list = []

    if not all_tags:
        print(f"    [Pass2] No SAMPLE_CODE/INLINE_CODE tags found — Pass 1 may have written code directly.")
        return draft, block_results_list

    sample_count = sum(1 for _, _, t in all_tags if t == "SAMPLE_CODE")
    inline_count = sum(1 for _, _, t in all_tags if t == "INLINE_CODE")
    print(f"    [Pass2] {sample_count} SAMPLE_CODE + {inline_count} INLINE_CODE tag(s) found. Starting batch generation...")

    # full_names / simple_names가 없으면 Doxygen DB 구축
    if full_names is None or simple_names is None:
        # stage_d_validator의 build_doxygen_symbol_set 대신 인라인 구축
        _full_names = set()
        _simple_names = set()
        for pkg_json in PARSED_DOXYGEN_DIR.glob("*.json"):
            try:
                with open(pkg_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for comp in data.get("compounds", []):
                    cn = comp.get("name", "")
                    if cn:
                        _full_names.add(cn)
                        _full_names.update(_symbol_aliases(cn))
                        _simple_names.add(cn.split("::")[-1])
                    for mb in comp.get("members", []):
                        mn = mb.get("name", "")
                        if mn:
                            full_sym = f"{cn}::{mn}"
                            _full_names.add(full_sym)
                            _full_names.update(_symbol_aliases(full_sym))
                            _simple_names.add(mn)
                        # named regular enum: enumvalue를 단축형 + 완전형 모두 등록
                        # 단축형: Class::VALUE (일반 enum은 C++ outer scope 노출로 유효)
                        # 완전형: Class::EnumName::VALUE (명시적 enum 이름 포함)
                        # struct/enum class의 경우 별도 compound로 처리되므로 여기선 건드리지 않음
                        if mb.get("kind") == "enum" and mn:
                            for ev in mb.get("enumvalues", []):
                                ev_name = ev.get("name", "")
                                if ev_name:
                                    shortcut = f"{cn}::{ev_name}"        # AlphaFunction::BOUNCE
                                    fullpath = f"{cn}::{mn}::{ev_name}"  # AlphaFunction::BuiltinFunction::BOUNCE
                                    for sym in (shortcut, fullpath):
                                        _full_names.add(sym)
                                        _full_names.update(_symbol_aliases(sym))
                                    _simple_names.add(ev_name)
            except Exception:
                continue
        # 상속 체인 alias 등록 (View::Add, ImageView::Add 등 파생 클래스 메서드 검증 지원)
        _full_names.update(_build_inheritance_aliases(PARSED_DOXYGEN_DIR))
        full_names, simple_names = _full_names, _simple_names
        print(f"    [Pass2] Doxygen DB built inline: {len(full_names)} full symbols.")

    code_results, block_history = generate_code_blocks_batch(
        feat_name, all_tags, specs, client,
        full_names, simple_names, permitted_method_block
    )

    # ── 통합: 태그를 코드/인라인 심볼로 치환 ──────────────────────────────────
    final_md = draft
    pass_count = fail_count = 0
    for i, (tag_full, purpose, tag_type) in enumerate(all_tags):
        code_block = code_results.get(i)
        hist = block_history[i] if i < len(block_history) else []
        attempts = len(hist)
        last = hist[-1] if hist else {}
        verdict = last.get("verdict", "FAIL")

        block_result = {
            "block_index": i,
            "block_purpose": purpose,
            "block_type": tag_type,
            "verdict": verdict,
            "attempts": attempts,
            "unverified_symbols": last.get("unverified_symbols", []),
            "action": "inserted" if code_block else "tag_removed"
        }
        block_results_list.append(block_result)

        if code_block:
            if tag_type == "INLINE_CODE":
                # 인라인 치환: 문장 끝 태그를 `symbol` 백틱 형태로 교체
                final_md = final_md.replace(tag_full, f"`{code_block.strip()}`", 1)
            else:
                final_md = final_md.replace(tag_full, code_block, 1)
            pass_count += 1
        else:
            # 실패: 태그만 제거, 문장은 유지 (Graceful Degradation)
            final_md = final_md.replace(tag_full, "", 1)
            fail_count += 1

    print(f"    [Pass2] Done: {pass_count} block(s) inserted, "
          f"{fail_count} tag(s) removed (graceful degradation).")

    # 후처리: using namespace 제거, 코드블럭 줄바꿈 강제
    final_md = _postprocess_markdown(final_md)

    # ── 블록 결과 저장 ───────────────────────────────────────────────────────
    results_dir = CODE_BLOCK_RESULTS_DIR / tier
    results_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_dir / f"{feat_name}.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "feature": feat_name,
            "total_code_blocks": len(all_tags),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "verdict": "PARTIAL" if fail_count > 0 else "FULL",
            "history": block_results_list
        }, f, indent=2, ensure_ascii=False)

    return final_md, block_results_list


def _postprocess_markdown(text: str) -> str:
    """
    생성된 마크다운에 대한 후처리를 적용한다.

    1. 코드블럭 내 'using namespace Dali' 계열 줄 제거
       (LLM은 short name 기준으로 생성하되, 출력에서는 선언 줄을 제거해 깔끔하게 유지)
    2. 코드 펜스(```cpp, ```) 앞에 줄바꿈이 없으면 강제 삽입
       (일부 LLM이 산문 바로 뒤에 펜스를 붙이는 경우 방어)
    """
    # 1. using namespace 제거
    def _strip_using_ns(m):
        lang = m.group(1)   # ```cpp 또는 ```
        inner = m.group(2)  # 코드 내용
        lines = inner.splitlines()
        lines = [l for l in lines
                 if not re.match(r'\s*using namespace Dali(::Ui)?;\s*$', l)]
        # 앞뒤 빈 줄 정리
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        body = '\n'.join(lines)
        return f"{lang}\n{body}\n```"

    text = re.sub(
        r'(```(?:cpp|c\+\+)?)\n(.*?)\n\s*```',
        lambda m: _strip_using_ns(m),
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    # 2. ``` 앞에 줄바꿈 강제
    text = re.sub(r'([^\n])(```)', r'\1\n\2', text)

    return text


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
                       taxonomy_context, view_context, tier_context="",
                       permitted_method_block=""):
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
    {permitted_method_block}

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

    blueprints_path = CACHE_DIR / "doc_blueprints" / f"stage_b_blueprints_{args.tier}.json"
    if not blueprints_path.exists():
        blueprints_path = CACHE_DIR / "doc_blueprints" / "stage_b_blueprints.json"

    blueprints = load_json(blueprints_path)
    if not blueprints:
        print("Blueprints corrupted. Aborting Markdown Generation.")
        return

    # child 메서드 주입 시 빠른 조회를 위한 blueprint 인덱스
    blueprints_index = {bp.get("feature"): bp for bp in blueprints}

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
        # merge_mode:full 피처는 feature_clusterer가 이미 target.apis에 병합했으므로
        # 1차 get_api_specs에서 자동 포함됨 — merge_sources에 중복 추가하지 않음
        if target and f.get("suppress_doc") and f.get("merge_mode") != "full":
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
            child_list = ", ".join(
                f"`{c}` ({taxonomy.get(c, {}).get('display_name', c)})"
                for c in children
            )

            # child 클래스별 허용 메서드 이름 목록을 최소한으로 수집
            # LLM이 child 메서드를 추론하지 않고 실제 존재하는 이름만 쓰도록 제한
            child_method_lines = []
            for child_name in children:
                child_bp = blueprints_index.get(child_name, {})
                child_specs_raw, _ = get_api_specs(
                    child_bp.get("packages", []),
                    child_bp.get("apis", []),
                    allowed_tiers
                )
                child_methods = sorted({
                    s["name"].split("::")[-1]
                    for s in child_specs_raw
                    if s.get("kind") == "function"
                    and not s["name"].split("::")[-1].startswith(("operator", "~"))
                })[:8]
                if child_methods:
                    display = taxonomy.get(child_name, {}).get("display_name", child_name)
                    child_method_lines.append(
                        f"          {display}: [{', '.join(child_methods)}]"
                    )

            child_methods_block = ""
            if child_method_lines:
                child_methods_block = (
                    "\n        CHILD COMPONENT PERMITTED METHODS"
                    " — call ONLY these when child classes appear in code examples:\n"
                    + "\n".join(child_method_lines)
                )

            taxonomy_context = f"""
        DOCUMENT ROLE — PARENT OVERVIEW PAGE:
        This is the overview (parent) page for the '{feat_name}' feature family.
        Its child components ({child_list}) each have their own dedicated pages.
        IMPORTANT: Use the exact class names shown above in parentheses for all code examples.
        Do NOT invent or abbreviate class names (e.g. use 'ImageView', not 'Image').
        Writing rules:
        - Introduce the overall concept and architecture of this feature family.
        - Describe each child component in 2-3 sentences and add a '→ See: [ChildName]' reference.
        - Do NOT write exhaustive API details for child components — just enough to understand when to use each.
        - Focus on how the parent and children relate structurally.
        {child_methods_block}
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
                taxonomy_context, view_context, tier_context,
                permitted_method_block=build_permitted_method_list(specs)
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

                    if src.get("merge_mode") == "full":
                        # merge_mode:full — specs에 직접 병합
                        # permitted list, slim_sigs에 완전 포함됨
                        # class_feature_map이 이미 소스 클래스를 target으로 재매핑했으므로
                        # get_api_specs의 foreign_classes 필터가 소스 클래스를 제외하지 않음
                        specs.extend(src_specs_raw)
                        print(f"    [+] Full-merged from '{src['feature']}': "
                              f"{len(src_specs_raw)} spec(s) added to {feat_name}")
                        continue

                    # 기존 동작: inherited_context (briefly mention)
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

            # ── 허용 메서드 목록 블록 ──────────────────────────────────────────────
            # specs에 실제 존재하는 메서드 이름만 나열하여 LLM의 이름 추론을 억제한다.
            # child 메서드는 taxonomy_context에서 별도로 주입되므로 여기서는 이 feature 자신의 메서드만.
            permitted_method_block = build_permitted_method_list(specs)

            # ── Enum-only feature 감지 → 코드 예제 억제 ────────────────────────
            if is_enum_only_feature(specs):
                code_example_strategy = """
        CODE EXAMPLE STRATEGY — TYPE DEFINITIONS ONLY:
        This feature contains only type definitions (enums or structs). There are NO callable methods.
        - Do NOT write any code block that calls SetXxx(), GetXxx(), or any method on a DALi object.
        - Instead, describe each enum/struct value and its semantic meaning in prose.
        - If a type usage is needed, show only variable declarations: TypeName var = TypeName::VALUE;
        - Do NOT show integration with View or other classes via method calls.
        """
            else:
                code_example_strategy = ""

            # ── 토큰 초과 여부 판단: taxonomy oversized_single 또는 토큰 추정값 기반 ──
            tax_entry = taxonomy.get(feat_name, {})
            specs_token_estimate = estimate_prompt_tokens(json.dumps(specs))
            use_rolling = tax_entry.get("oversized_single", False) or specs_token_estimate > SPEC_TOKEN_THRESHOLD

            if use_rolling:
                print(f"    [!] Specs token estimate: {specs_token_estimate:,} "
                      f"(threshold: {SPEC_TOKEN_THRESHOLD:,}) — switching to 2-pass + rolling mode.")

            # ── 2-Pass 생성 (Phase 2) ────────────────────────────────────────
            # Doxygen DB: 루프 전체에서 1회만 구축하여 client에 캐시
            if not hasattr(client, '_dali_full_names'):
                _fn, _sn = set(), set()
                for _pkg_json in PARSED_DOXYGEN_DIR.glob("*.json"):
                    try:
                        with open(_pkg_json, "r", encoding="utf-8") as _f:
                            _data = json.load(_f)
                        for _comp in _data.get("compounds", []):
                            _cn = _comp.get("name", "")
                            if _cn:
                                _fn.add(_cn)
                                _fn.update(_symbol_aliases(_cn))
                                _sn.add(_cn.split("::")[-1])
                            for _mb in _comp.get("members", []):
                                _mn = _mb.get("name", "")
                                if _mn:
                                    _full_sym = f"{_cn}::{_mn}"
                                    _fn.add(_full_sym)
                                    _fn.update(_symbol_aliases(_full_sym))
                                    _sn.add(_mn)
                                # named regular enum: 단축형 + 완전형 모두 등록
                                if _mb.get("kind") == "enum" and _mn:
                                    for _ev in _mb.get("enumvalues", []):
                                        _ev_name = _ev.get("name", "")
                                        if _ev_name:
                                            _shortcut = f"{_cn}::{_ev_name}"
                                            _fullpath = f"{_cn}::{_mn}::{_ev_name}"
                                            for _sym in (_shortcut, _fullpath):
                                                _fn.add(_sym)
                                                _fn.update(_symbol_aliases(_sym))
                                            _sn.add(_ev_name)
                    except Exception:
                        continue
                # 상속 체인 alias 등록 (View::Add, ImageView::Add 등 파생 클래스 메서드 검증 지원)
                _inh = _build_inheritance_aliases(PARSED_DOXYGEN_DIR)
                _fn.update(_inh)
                # typedef alias 등록 (Text::FontWeight::BOLD 등 using 선언 alias 검증 지원)
                _tdef = _build_typedef_aliases(PARSED_DOXYGEN_DIR)
                _fn.update(_tdef)
                client._dali_full_names = _fn
                client._dali_simple_names = _sn
                print(f"    [Pass2-DB] Doxygen symbol DB built: "
                      f"{len(_fn)} full+alias "
                      f"(+{len(_inh)} inheritance, +{len(_tdef)} typedef), "
                      f"{len(_sn)} simple.")

            clean_md, _block_results = run_two_pass_generation(
                feat_name, outline, specs, client,
                taxonomy_context, view_context, tier_context,
                CONTEXT_LIMIT, PROMPT_OVERHEAD,
                chaining_context=chaining_context,
                feature_hint_block=feature_hint_block,
                permitted_method_block=permitted_method_block,
                code_example_strategy=code_example_strategy,
                full_names=client._dali_full_names,
                simple_names=client._dali_simple_names,
                tier=args.tier,
                use_rolling=use_rolling
            )
            clean_md = strip_markdown_wrapping(clean_md)

        out_file = tier_drafts_dir / f"{feat_name}.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(clean_md)

        # validated_drafts에 즉시 복사 (stage_d 역할 흡수)
        validated_dir = VALIDATED_DRAFTS_DIR / args.tier
        validated_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_file, validated_dir / f"{feat_name}.md")

        mode_label = "[PATCH]" if args.patch else "[DRAFT]"
        print(f"    [+] {mode_label} Documentation exported → {out_file.relative_to(CACHE_DIR)}"
              f"  (validated_drafts/ updated)")

    # ── 검증 리포트 생성 (code_block_results 집계) ────────────────────────────
    _write_validation_report(args.tier)

    print(f"\n=================================================================")
    print(f" Stage C Complete! Native markdown drafts exported to:")
    print(f" {tier_drafts_dir}")
    print("=================================================================")


def _write_validation_report(tier: str):
    """
    code_block_results/{tier}/*.json 을 집계하여
    cache/validation_report/stage_c_report_{tier}.json 을 생성한다.
    """
    results_dir = CODE_BLOCK_RESULTS_DIR / tier
    report_dir = CACHE_DIR / "validation_report"
    report_dir.mkdir(parents=True, exist_ok=True)

    if not results_dir.exists():
        return

    report = []
    stats = {"full": 0, "partial": 0, "no_blocks": 0}

    for result_file in sorted(results_dir.glob("*.json")):
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        verdict = data.get("verdict", "NO_BLOCKS")
        report.append({
            "feature": data.get("feature", result_file.stem),
            "verdict": verdict,
            "total_code_blocks": data.get("total_code_blocks", 0),
            "pass_count": data.get("pass_count", 0),
            "fail_count": data.get("fail_count", 0),
        })
        key = verdict.lower().replace("no_blocks", "no_blocks")
        if key in stats:
            stats[key] += 1
        elif verdict == "NO_BLOCKS":
            stats["no_blocks"] += 1

    report_path = report_dir / f"stage_c_report_{tier}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"stats": stats, "features": report}, f, indent=2, ensure_ascii=False)
    print(f"    [Report] Validation report → {report_path.relative_to(CACHE_DIR.parent)}")


if __name__ == "__main__":
    main()

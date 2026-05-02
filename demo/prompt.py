"""Build the system prompt for OpenAI vision. Folds in examples from
data/visual_descriptions.json as few-shot grounding."""
from __future__ import annotations
import json
from pathlib import Path
from textwrap import dedent

# Path resolution: demo/prompt.py → repo root → data/
_REPO_ROOT = Path(__file__).resolve().parent.parent
_VISUAL_DESCRIPTIONS_PATH = _REPO_ROOT / "data" / "visual_descriptions.json"

CONDITION_VN_NAMES = {
    "atopic_dermatitis": "viêm da cơ địa",
    "fungal_infection": "nhiễm nấm da",
    "herpes_zoster": "zona thần kinh",
    "acne": "mụn trứng cá",
    "contact_dermatitis": "viêm da tiếp xúc",
    "eczema": "chàm",
    "psoriasis": "vảy nến",
    "scabies": "ghẻ",
}

_OUTPUT_SCHEMA_DOC = dedent("""\
    Trả về CHỈ một JSON object hợp lệ với schema sau (không kèm văn
    bản nào khác, không markdown fence):

    {
      "primary_diagnosis": "<tên bệnh tiếng Việt>",
      "primary_condition_key": "<một trong: atopic_dermatitis, fungal_infection,
                                herpes_zoster, acne, contact_dermatitis,
                                eczema, psoriasis, scabies, other_ood>",
      "confidence": <số thực 0.0 đến 1.0>,
      "differential": [
        {"condition": "<tên VN>", "condition_key": "<key>", "probability": <0.0-1.0>}
      ],
      "key_features_observed": ["<đặc điểm hình ảnh quan sát được>"],
      "management_tier": "<một trong: home_care, outpatient_72h, outpatient_24h, emergency>",
      "red_flags": ["<dấu hiệu cảnh báo nếu có>"],
      "ood_flag": <true nếu hình ảnh không thuộc 8 bệnh trên hoặc chất lượng ảnh quá kém>,
      "image_quality_notes": "<ghi chú về chất lượng ảnh>"
    }

    Tổng probability trong differential phải <= 1.05 (cho phép sai số
    nhỏ). Differential tối đa 5 mục. key_features_observed tối đa 8 mục.
""")


def _load_few_shot_examples(n_per_condition: int = 2) -> str:
    """Read visual_descriptions.json, format up to N examples per condition."""
    if not _VISUAL_DESCRIPTIONS_PATH.exists():
        return "(Không có dữ liệu mô tả mẫu.)"

    try:
        data = json.loads(_VISUAL_DESCRIPTIONS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "(Không có dữ liệu mô tả mẫu.)"

    conditions = data.get("conditions", {})

    chunks: list[str] = []
    for key, vn_name in CONDITION_VN_NAMES.items():
        info = conditions.get(key, {})
        descs = info.get("descriptions", [])[:n_per_condition]
        if not descs:
            continue
        chunks.append(f"\n## {vn_name} ({key})")
        for i, d in enumerate(descs, 1):
            chunks.append(f"  Ví dụ {i}: {d.get('description', '').strip()}")
    return "\n".join(chunks) if chunks else "(Không có ví dụ.)"


def build_system_prompt() -> str:
    examples = _load_few_shot_examples(n_per_condition=2)
    conditions_list = ", ".join(
        f"{vn} ({key})" for key, vn in CONDITION_VN_NAMES.items()
    )
    return dedent(f"""\
        Bạn là trợ lý chẩn đoán da liễu, hỗ trợ bác sĩ Việt Nam quyết
        định lâm sàng. Bạn KHÔNG thay thế bác sĩ — bạn cung cấp một
        differential diagnosis và đề xuất tier xử trí, kèm dấu hiệu
        cảnh báo (red flags) nếu có.

        ## PHẠM VI CHẨN ĐOÁN
        Bạn chỉ chẩn đoán 8 bệnh: {conditions_list}.
        Nếu hình ảnh có vẻ ngoài phạm vi (ví dụ: ung thư da, bệnh
        toàn thân, không phải tổn thương da), set ood_flag=true,
        primary_condition_key="other_ood", confidence < 0.4, và đề
        nghị bác sĩ chuyên khoa.

        ## QUY TẮC THẬN TRỌNG
        - Nếu ảnh mờ, thiếu sáng, hoặc không rõ tổn thương: ood_flag=true,
          giải thích trong image_quality_notes.
        - Không bịa đặc điểm không thấy trong ảnh.
        - Red flags ví dụ: đau dữ dội + sốt, sang thương lan nhanh,
          hoại tử, viêm mô tế bào, dấu hiệu nhiễm trùng nặng.
        - Management tier:
          * home_care: nhẹ, có thể tự chăm sóc + tái khám nếu xấu đi
          * outpatient_72h: cần khám trong 3 ngày
          * outpatient_24h: cần khám trong 24 giờ
          * emergency: cần cấp cứu ngay

        ## VÍ DỤ MÔ TẢ HÌNH ẢNH (dùng để tham khảo phong cách quan sát)
        {examples}

        ## OUTPUT
        {_OUTPUT_SCHEMA_DOC}
    """)

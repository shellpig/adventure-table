from __future__ import annotations

from app.content.m01j_reference_content import SPELL_INDEX_ALIASES
from app.content.registry import ContentValidationError


# Temporary subclass reference documents sometimes use Chinese titles that do
# not exactly match the M02 SRD locale shards. These aliases reconcile those
# verified document titles to existing canonical spell indices only; they never
# create spell rules or change presentation/localization data.
REFERENCE_SPELL_INDEX_ALIASES: dict[str, str] = {
    # Divine Soul affinity table.
    "治療傷勢": "cure-wounds",
    "造成傷勢": "inflict-wounds",
    "祝福術": "bless",
    "災禍術": "bane",
    "防護善惡": "protection-from-evil-and-good",
    # Shared PHB/SRD/TCE spell titles used by subclass spell tables.
    "誘捕打擊": "ensnaring-strike",
    "噪音暗語": "dissonant-whispers",
    "守護聯結": "warding-bond",
    "威能法環": "circle-of-power",
    "摹造生命": "false-life",
    "致病射線": "ray-of-sickness",
    "假死術": "feign-death",
    "防死護咒": "death-ward",
    "哈達之臂": "arms-of-hadar",
    "哈達之慾": "hunger-of-hadar",
    "心靈之楔": "mind-sliver",
    "異怪召喚術": "summon-aberration",
    "次級復原術": "lesser-restoration",
    "構裝體召喚術": "summon-construct",
    "元素召喚術": "summon-elemental",
    "假象術": "mislead",
    "光導箭": "guiding-bolt",
    "淨化靈光": "aura-of-purity",
    "歐提路克魔封法球": "resilient-sphere",
    "秘法眼": "arcane-eye",
    "迴避偵測": "nondetection",
    "艾嘉西斯之鎧": "armor-of-agathys",
    "通天繩": "rope-trick",
    "激憤斬": "wrathful-smite",
    "驚震斬": "staggering-smite",
    "防護法陣": "magic-circle",
    # Genie common expanded spells.
    "偵測善惡": "detect-evil-and-good",
    "魅影之力": "phantasmal-force",
    "創造飲食": "create-food-and-water",
    "魅影殺手": "phantasmal-killer",
    "造物術": "creation",
    "祈願術": "wish",
    # Dao.
    "聖域術": "sanctuary",
    "荊棘叢生": "spike-growth",
    "融身入石": "meld-into-stone",
    "塑石術": "stone-shape",
    "石牆術": "wall-of-stone",
    # Djinni.
    "雷鳴波": "thunderwave",
    "造風術": "gust-of-wind",
    "風牆術": "wind-wall",
    "高等隱形術": "greater-invisibility",
    "偽裝術": "seeming",
    # Efreeti.
    "燃燒之手": "burning-hands",
    "灼熱射線": "scorching-ray",
    "火球術": "fireball",
    "火焰護盾": "fire-shield",
    "焰擊術": "flame-strike",
    # Marid.
    "雲霧術": "fog-cloud",
    "朦朧術": "blur",
    "雪雨暴": "sleet-storm",
    "操控水體": "control-water",
    "寒冰錐": "cone-of-cold",
}


def install_m01j_spell_aliases() -> None:
    """Install verified reference-title aliases before M01-J document parsing."""

    conflicts = {
        name: (SPELL_INDEX_ALIASES[name], index)
        for name, index in REFERENCE_SPELL_INDEX_ALIASES.items()
        if name in SPELL_INDEX_ALIASES and SPELL_INDEX_ALIASES[name] != index
    }
    if conflicts:
        raise ContentValidationError(f"M01-J spell alias conflicts: {conflicts}")
    SPELL_INDEX_ALIASES.update(REFERENCE_SPELL_INDEX_ALIASES)

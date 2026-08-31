"""Build the M02-D Traditional Chinese SRD presentation overlay.

This is an authoring/maintenance tool. Runtime localization still consumes the
committed data/srd5.1/locales/zh-TW.json overlay produced by this script; it does
not translate content dynamically.

The translator is intentionally deterministic and conservative:
- exact D&D terminology wins;
- compositional names use reviewed phrase/word mappings;
- unknown English words are reported so the authoring batch cannot silently
  ship mixed-language labels.

M02-E long-form descriptions are deliberately outside this script's scope.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRD_ROOT = ROOT / "data" / "srd5.1"
POLICY_PATH = ROOT / "data" / "localization" / "localizable-fields.json"

REQUIRED_KINDS = {
    "ability",
    "alignment",
    "background",
    "class",
    "condition",
    "equipment",
    "feat",
    "feature",
    "item",
    "language",
    "proficiency",
    "race",
    "skill",
    "spell",
    "subclass",
    "subrace",
    "trait",
}

CATEGORY_BY_KIND = {
    "ability": "abilities.json",
    "alignment": "alignments.json",
    "background": "backgrounds.json",
    "class": "classes.json",
    "condition": "conditions.json",
    "equipment": "equipment.json",
    "feat": "feats.json",
    "feature": "features.json",
    "item": "items.json",
    "language": "languages.json",
    "proficiency": "proficiencies.json",
    "race": "races.json",
    "skill": "skills.json",
    "spell": "spells.json",
    "subclass": "subclasses.json",
    "subrace": "subraces.json",
    "trait": "traits.json",
}

# High-visibility canonical names and established Traditional Chinese D&D terms.
EXACT: dict[str, str] = {
    # Ability scores
    "STR": "力量",
    "DEX": "敏捷",
    "CON": "體質",
    "INT": "智力",
    "WIS": "睿知",
    "CHA": "魅力",
    "Strength": "力量",
    "Dexterity": "敏捷",
    "Constitution": "體質",
    "Intelligence": "智力",
    "Wisdom": "睿知",
    "Charisma": "魅力",
    # Alignment
    "Lawful Good": "守序善良",
    "Neutral Good": "中立善良",
    "Chaotic Good": "混亂善良",
    "Lawful Neutral": "守序中立",
    "Neutral": "絕對中立",
    "Chaotic Neutral": "混亂中立",
    "Lawful Evil": "守序邪惡",
    "Neutral Evil": "中立邪惡",
    "Chaotic Evil": "混亂邪惡",
    # Core classes
    "Barbarian": "野蠻人",
    "Bard": "吟遊詩人",
    "Cleric": "牧師",
    "Druid": "德魯伊",
    "Fighter": "戰士",
    "Monk": "武僧",
    "Paladin": "聖武士",
    "Ranger": "遊俠",
    "Rogue": "遊蕩者",
    "Sorcerer": "術士",
    "Warlock": "邪術師",
    "Wizard": "法師",
    # Races / subraces
    "Dragonborn": "龍裔",
    "Dwarf": "矮人",
    "Elf": "精靈",
    "Gnome": "侏儒",
    "Half-Elf": "半精靈",
    "Half-Orc": "半獸人",
    "Halfling": "半身人",
    "Human": "人類",
    "Tiefling": "提夫林",
    "High Elf": "高等精靈",
    "Hill Dwarf": "丘陵矮人",
    "Lightfoot Halfling": "輕足半身人",
    "Rock Gnome": "岩侏儒",
    # Subclasses
    "Berserker": "狂戰士道途",
    "Lore": "逸聞學院",
    "Life": "生命領域",
    "Land": "大地結社",
    "Champion": "勇士",
    "Open Hand": "散打宗",
    "Devotion": "奉獻之誓",
    "Hunter": "獵人",
    "Thief": "盜賊",
    "Draconic": "龍族血脈",
    "Fiend": "邪魔宗主",
    "Evocation": "塑能學派",
    # Background / feat
    "Acolyte": "侍僧",
    "Shelter of the Faithful": "信徒庇護",
    "Grappler": "擒抱者",
    # Skills
    "Acrobatics": "特技",
    "Animal Handling": "馴獸",
    "Arcana": "奧秘",
    "Athletics": "運動",
    "Deception": "欺瞞",
    "History": "歷史",
    "Insight": "洞悉",
    "Intimidation": "威嚇",
    "Investigation": "調查",
    "Medicine": "醫藥",
    "Nature": "自然",
    "Perception": "察覺",
    "Performance": "表演",
    "Persuasion": "遊說",
    "Religion": "宗教",
    "Sleight of Hand": "巧手",
    "Stealth": "隱匿",
    "Survival": "求生",
    # Languages
    "Common": "通用語",
    "Dwarvish": "矮人語",
    "Elvish": "精靈語",
    "Giant": "巨人語",
    "Gnomish": "侏儒語",
    "Goblin": "哥布林語",
    "Halfling": "半身人語",
    "Orc": "獸人語",
    "Abyssal": "深淵語",
    "Celestial": "天界語",
    "Draconic": "龍語",
    "Deep Speech": "深潛語",
    "Infernal": "煉獄語",
    "Primordial": "原初語",
    "Sylvan": "木族語",
    "Undercommon": "地底通用語",
    # Conditions
    "Blinded": "目盲",
    "Charmed": "魅惑",
    "Deafened": "耳聾",
    "Exhaustion": "力竭",
    "Frightened": "恐慌",
    "Grappled": "被擒抱",
    "Incapacitated": "失能",
    "Invisible": "隱形",
    "Paralyzed": "麻痺",
    "Petrified": "石化",
    "Poisoned": "中毒",
    "Prone": "倒地",
    "Restrained": "束縛",
    "Stunned": "震懾",
    "Unconscious": "昏迷",
    # Common/current spell names (also establish preferred terminology)
    "Acid Arrow": "強酸箭",
    "Acid Splash": "酸液飛濺",
    "Aid": "援助術",
    "Alarm": "警報術",
    "Alter Self": "變身術",
    "Animal Friendship": "動物友好術",
    "Animal Messenger": "動物信使",
    "Animal Shapes": "動物形態",
    "Animate Dead": "活化死屍",
    "Animate Objects": "活化物件",
    "Antilife Shell": "防生物護罩",
    "Antimagic Field": "反魔法力場",
    "Arcane Eye": "祕法眼",
    "Arcane Hand": "祕法之手",
    "Arcane Lock": "祕法鎖",
    "Astral Projection": "星界投射",
    "Augury": "卜筮術",
    "Awaken": "喚醒術",
    "Bane": "災禍術",
    "Banishment": "放逐術",
    "Barkskin": "樹膚術",
    "Beacon of Hope": "希望信標",
    "Bestow Curse": "降咒術",
    "Black Tentacles": "黑觸手",
    "Blade Barrier": "劍刃障壁",
    "Bless": "祝福術",
    "Blight": "枯萎術",
    "Blindness/Deafness": "目盲／耳聾術",
    "Blink": "閃現術",
    "Blur": "朦朧術",
    "Branding Smite": "烙印斬",
    "Burning Hands": "燃燒之手",
    "Call Lightning": "召雷術",
    "Calm Emotions": "安定心神",
    "Chain Lightning": "連鎖閃電",
    "Charm Person": "魅惑人類",
    "Chill Touch": "寒冷之觸",
    "Circle of Death": "死亡法陣",
    "Clairvoyance": "銳眼術",
    "Clone": "複製術",
    "Cloudkill": "死雲術",
    "Color Spray": "七彩噴射",
    "Command": "命令術",
    "Commune": "通神術",
    "Commune with Nature": "自然交流",
    "Comprehend Languages": "理解語言",
    "Cone of Cold": "寒冰錐",
    "Confusion": "困惑術",
    "Conjure Animals": "召喚動物",
    "Conjure Celestial": "召喚天界生物",
    "Conjure Elemental": "召喚元素生物",
    "Conjure Fey": "召喚妖精",
    "Conjure Minor Elementals": "召喚次級元素生物",
    "Conjure Woodland Beings": "召喚林地生物",
    "Contact Other Plane": "異界探知",
    "Contagion": "疫病術",
    "Contingency": "預備術",
    "Continual Flame": "不滅明焰",
    "Control Water": "操控水體",
    "Control Weather": "操控天氣",
    "Counterspell": "反制法術",
    "Create Food and Water": "造糧術",
    "Create or Destroy Water": "造水／枯水術",
    "Create Undead": "創造不死生物",
    "Creation": "創造術",
    "Cure Wounds": "治療傷勢",
    "Dancing Lights": "舞光術",
    "Darkness": "黑暗術",
    "Darkvision": "黑暗視覺",
    "Daylight": "晝明術",
    "Death Ward": "防死結界",
    "Delayed Blast Fireball": "延遲爆裂火球",
    "Demiplane": "半位面",
    "Detect Evil and Good": "偵測善惡",
    "Detect Magic": "偵測魔法",
    "Detect Poison and Disease": "偵測毒素與疾病",
    "Detect Thoughts": "偵測思想",
    "Dimension Door": "任意門",
    "Disguise Self": "易容術",
    "Disintegrate": "解離術",
    "Dispel Evil and Good": "解除善惡",
    "Dispel Magic": "解除魔法",
    "Divination": "預言術",
    "Divine Favor": "神恩術",
    "Divine Word": "神聖真言",
    "Dominate Beast": "支配野獸",
    "Dominate Monster": "支配怪物",
    "Dominate Person": "支配人類",
    "Dream": "夢境術",
    "Earthquake": "地震術",
    "Enhance Ability": "強化屬性",
    "Enlarge/Reduce": "變巨／縮小術",
    "Entangle": "糾纏術",
    "Enthrall": "迷魂術",
    "Etherealness": "虛體術",
    "Expeditious Retreat": "腳底抹油",
    "Eyebite": "攝心目光",
    "Fabricate": "鬼斧神工",
    "Faerie Fire": "妖火",
    "Faithful Hound": "忠犬術",
    "False Life": "虛假生命",
    "Fear": "恐懼術",
    "Feather Fall": "羽落術",
    "Feeblemind": "弱智術",
    "Feign Death": "假死術",
    "Find Familiar": "尋獲魔寵",
    "Find Steed": "尋獲坐騎",
    "Find Traps": "尋找陷阱",
    "Finger of Death": "死亡一指",
    "Fire Bolt": "火焰箭",
    "Fire Shield": "火焰護盾",
    "Fire Storm": "火焰風暴",
    "Fireball": "火球術",
    "Flame Blade": "焰刃術",
    "Flame Strike": "焰擊術",
    "Flaming Sphere": "熾焰法球",
    "Flesh to Stone": "石化血肉",
    "Floating Disk": "浮碟術",
    "Fly": "飛行術",
    "Fog Cloud": "雲霧術",
    "Forbiddance": "禁制術",
    "Forcecage": "力場牢籠",
    "Foresight": "預視術",
    "Freedom of Movement": "行動自如",
    "Freezing Sphere": "冰凍法球",
    "Gaseous Form": "氣化形體",
    "Gate": "異界之門",
    "Geas": "指使術",
    "Gentle Repose": "遺體防腐",
    "Giant Insect": "巨蟲術",
    "Glibness": "巧舌術",
    "Globe of Invulnerability": "法術無效結界",
    "Glyph of Warding": "守衛銘文",
    "Goodberry": "神莓術",
    "Grease": "油膩術",
    "Greater Invisibility": "高等隱形術",
    "Greater Restoration": "高等復原術",
    "Guardian of Faith": "信仰守衛",
    "Guards and Wards": "警戒結界",
    "Guidance": "神導術",
    "Guiding Bolt": "曳光彈",
    "Gust of Wind": "造風術",
    "Hallow": "聖居術",
    "Hallucinatory Terrain": "幻景地形",
    "Harm": "傷害術",
    "Haste": "加速術",
    "Heal": "醫療術",
    "Healing Word": "治癒真言",
    "Heat Metal": "灼熱金屬",
    "Hellish Rebuke": "煉獄叱喝",
    "Heroes' Feast": "英雄宴",
    "Heroism": "英雄氣概",
    "Hideous Laughter": "狂笑術",
    "Hold Monster": "怪物定身術",
    "Hold Person": "人類定身術",
    "Holy Aura": "神聖靈光",
    "Hypnotic Pattern": "催眠圖紋",
    "Ice Storm": "冰風暴",
    "Identify": "鑑定術",
    "Illusory Script": "幻術文字",
    "Imprisonment": "禁錮術",
    "Incendiary Cloud": "焚雲術",
    "Inflict Wounds": "致傷術",
    "Insect Plague": "蟲群瘟疫",
    "Instant Summons": "即時召喚",
    "Invisibility": "隱形術",
    "Irresistible Dance": "無法抗拒之舞",
    "Jump": "跳躍術",
    "Knock": "敲擊術",
    "Legend Lore": "傳奇知識",
    "Lesser Restoration": "次等復原術",
    "Levitate": "浮空術",
    "Light": "光亮術",
    "Lightning Bolt": "閃電束",
    "Locate Animals or Plants": "定位動植物",
    "Locate Creature": "定位生物",
    "Locate Object": "定位物件",
    "Longstrider": "大步奔行",
    "Mage Armor": "法師護甲",
    "Mage Hand": "法師之手",
    "Magic Circle": "魔法陣",
    "Magic Jar": "魔魂壺",
    "Magic Missile": "魔法飛彈",
    "Magic Mouth": "魔嘴術",
    "Magic Weapon": "魔化武器",
    "Magnificent Mansion": "豪華大宅",
    "Major Image": "強效幻影",
    "Mass Cure Wounds": "群體治療傷勢",
    "Mass Heal": "群體醫療術",
    "Mass Healing Word": "群體治癒真言",
    "Mass Suggestion": "群體暗示術",
    "Maze": "迷宮術",
    "Meld into Stone": "融身入石",
    "Mending": "修復術",
    "Message": "傳訊術",
    "Meteor Swarm": "流星爆",
    "Mind Blank": "心智屏障",
    "Minor Illusion": "次級幻影",
    "Mirage Arcane": "海市蜃樓",
    "Mirror Image": "鏡影術",
    "Misty Step": "迷蹤步",
    "Modify Memory": "修改記憶",
    "Moonbeam": "月華之光",
    "Move Earth": "移土術",
    "Nondetection": "防偵測",
    "Pass without Trace": "行蹤無痕",
    "Passwall": "穿牆術",
    "Phantasmal Killer": "魅影殺手",
    "Phantom Steed": "魅影駒",
    "Planar Ally": "異界盟友",
    "Planar Binding": "異界束縛",
    "Plane Shift": "異界傳送",
    "Plant Growth": "植物滋長",
    "Poison Spray": "毒氣噴濺",
    "Polymorph": "變形術",
    "Power Word Kill": "律令死亡",
    "Power Word Stun": "律令震懾",
    "Prayer of Healing": "治癒祈禱",
    "Prestidigitation": "魔法伎倆",
    "Prismatic Spray": "虹光噴射",
    "Prismatic Wall": "虹光法牆",
    "Private Sanctum": "私人聖所",
    "Produce Flame": "燃火術",
    "Programmed Illusion": "程式幻影",
    "Project Image": "投影術",
    "Protection from Energy": "防護能量",
    "Protection from Evil and Good": "防護善惡",
    "Protection from Poison": "防護毒素",
    "Purify Food and Drink": "淨化食糧",
    "Raise Dead": "死者復活",
    "Ray of Enfeeblement": "衰弱射線",
    "Ray of Frost": "冷凍射線",
    "Regenerate": "再生術",
    "Reincarnate": "轉生術",
    "Remove Curse": "移除詛咒",
    "Resilient Sphere": "彈力法球",
    "Resistance": "抗力術",
    "Resurrection": "復生術",
    "Reverse Gravity": "重力反轉",
    "Revivify": "回生術",
    "Rope Trick": "魔繩術",
    "Sacred Flame": "聖火術",
    "Sanctuary": "聖域術",
    "Scorching Ray": "灼熱射線",
    "Scrying": "探知術",
    "Secret Chest": "祕密箱",
    "See Invisibility": "識破隱形",
    "Sending": "短訊術",
    "Sequester": "隱匿術",
    "Shapechange": "形體變化",
    "Shatter": "粉碎音波",
    "Shield": "護盾術",
    "Shield of Faith": "信仰護盾",
    "Shillelagh": "橡棍術",
    "Shocking Grasp": "電爪術",
    "Silence": "沉默術",
    "Silent Image": "無聲幻影",
    "Simulacrum": "擬像術",
    "Sleep": "睡眠術",
    "Sleet Storm": "雪雨暴",
    "Slow": "緩速術",
    "Spare the Dying": "維生術",
    "Speak with Animals": "動物交談",
    "Speak with Dead": "死者交談",
    "Speak with Plants": "植物交談",
    "Spider Climb": "蛛行術",
    "Spike Growth": "荊棘叢生",
    "Spirit Guardians": "靈體守衛",
    "Spiritual Weapon": "靈體武器",
    "Stinking Cloud": "臭雲術",
    "Stone Shape": "塑石術",
    "Stoneskin": "石膚術",
    "Storm of Vengeance": "復仇風暴",
    "Suggestion": "暗示術",
    "Sunbeam": "陽炎射線",
    "Sunburst": "陽炎爆",
    "Symbol": "徽記術",
    "Telekinesis": "心靈遙控",
    "Telepathic Bond": "心靈連結",
    "Teleport": "傳送術",
    "Teleportation Circle": "傳送法陣",
    "Thaumaturgy": "奇術",
    "Thunderwave": "雷鳴波",
    "Time Stop": "時間停止",
    "Tiny Hut": "小屋術",
    "Tongues": "巧言術",
    "Tree Stride": "樹躍術",
    "True Polymorph": "完全變形術",
    "True Resurrection": "完全復生術",
    "True Seeing": "真知術",
    "True Strike": "克敵機先",
    "Unseen Servant": "隱形僕役",
    "Vampiric Touch": "吸血鬼之觸",
    "Wall of Fire": "火牆術",
    "Wall of Force": "力場牆",
    "Wall of Ice": "冰牆術",
    "Wall of Stone": "石牆術",
    "Wall of Thorns": "荊棘牆",
    "Warding Bond": "守護之鏈",
    "Water Breathing": "水下呼吸",
    "Water Walk": "水面行走",
    "Web": "蛛網術",
    "Weird": "怪影殺手",
    "Wind Walk": "風行術",
    "Wind Wall": "風牆術",
    "Wish": "祈願術",
    "Word of Recall": "回返真言",
    "Zone of Truth": "誠實之域",
}

# Proper-name spell/item stems which should never be treated as ordinary English.
PROPER: dict[str, str] = {
    "Bigby": "畢格比",
    "Drawmij": "卓姆吉",
    "Evard": "艾伐",
    "Heward": "休瓦德",
    "Ioun": "艾恩",
    "Leomund": "李歐蒙",
    "Melf": "馬友夫",
    "Mordenkainen": "魔鄧肯",
    "Nolzur": "諾祖爾",
    "Nystul": "奈斯圖",
    "Otiluke": "歐提路克",
    "Quaal": "夸爾",
    "Robe": "長袍",
    "Tenser": "譚森",
}

# Longest-phrase-first replacements used before word composition.
PHRASES: dict[str, str] = {
    "Ability Score Improvement": "屬性值提升",
    "Ability Score": "屬性值",
    "Action Surge": "動作如潮",
    "Arcane Recovery": "祕法回復",
    "Arcane Tradition": "祕法學派",
    "Aura of Courage": "勇氣靈光",
    "Aura of Protection": "守護靈光",
    "Bardic Inspiration": "吟遊激勵",
    "Brutal Critical": "殘暴重擊",
    "Channel Divinity": "引導神力",
    "Danger Sense": "危險感知",
    "Divine Health": "神聖健康",
    "Divine Intervention": "神聖干預",
    "Divine Sense": "神聖感知",
    "Divine Smite": "至聖斬",
    "Extra Attack": "額外攻擊",
    "Fast Movement": "快速移動",
    "Fighting Style": "戰鬥風格",
    "Font of Magic": "魔力泉源",
    "Indomitable": "不屈",
    "Jack of All Trades": "萬事通",
    "Ki-Empowered Strikes": "真氣強化打擊",
    "Lay on Hands": "聖療",
    "Magical Secrets": "魔法祕密",
    "Martial Arts": "武藝",
    "Metamagic": "超魔法",
    "Pact Boon": "契約恩賜",
    "Pact Magic": "契約魔法",
    "Primal Path": "原初道途",
    "Rage": "狂暴",
    "Reckless Attack": "魯莽攻擊",
    "Sacred Oath": "神聖誓言",
    "Second Wind": "再度振作",
    "Sneak Attack": "偷襲",
    "Song of Rest": "休憩曲",
    "Sorcerous Origin": "術士起源",
    "Spellcasting": "施法",
    "Unarmored Defense": "無甲防禦",
    "Unarmored Movement": "無甲移動",
    "Wild Shape": "荒野形態",
    "Weapon Bond": "武器連結",
    "Weapon Mastery": "武器精通",
    "Weapon Training": "武器訓練",
    "Saving Throw": "豁免",
    "Medium Armor": "中甲",
    "Heavy Armor": "重甲",
    "Light Armor": "輕甲",
    "Martial Weapons": "軍用武器",
    "Simple Weapons": "簡易武器",
    "Musical Instrument": "樂器",
    "Gaming Set": "博弈用具",
    "Artisan's Tools": "工匠工具",
    "Thieves' Tools": "盜賊工具",
    "Holy Symbol": "聖徽",
    "Druidic Focus": "德魯伊法器",
    "Arcane Focus": "祕法法器",
    "Explorer's Pack": "探索者套組",
    "Dungeoneer's Pack": "地城探索者套組",
    "Priest's Pack": "祭司套組",
    "Scholar's Pack": "學者套組",
    "Burglar's Pack": "竊賊套組",
    "Diplomat's Pack": "外交官套組",
    "Entertainer's Pack": "藝人套組",
}

WORDS: dict[str, str] = {
    "absorption": "吸收", "accuracy": "精準", "acid": "強酸", "adamantine": "精金",
    "adaptation": "適應", "agility": "敏捷", "alchemy": "煉金", "all-purpose": "多用途",
    "ammunition": "彈藥", "amulet": "護符", "animal": "動物", "animated": "活化",
    "antitoxin": "抗毒劑", "apparatus": "裝置", "apparel": "服裝", "archery": "箭術",
    "armor": "護甲", "arrow": "箭矢", "arrows": "箭矢", "assassin": "刺客",
    "attack": "攻擊", "attacks": "攻擊", "awakening": "覺醒", "axe": "斧",
    "bag": "袋", "balance": "平衡", "banded": "條帶", "barrier": "障壁",
    "battleaxe": "戰斧", "bead": "珠", "beads": "珠", "bear": "熊", "belt": "腰帶",
    "berserking": "狂戰", "black": "黑色", "blade": "刃", "blasting": "爆破",
    "blessing": "祝福", "blood": "血液", "boat": "船", "boots": "靴",
    "bottle": "瓶", "bow": "弓", "bracelet": "手鐲", "bracers": "護腕",
    "breathing": "呼吸", "broom": "掃帚", "buckler": "小圓盾", "caltrops": "鐵蒺藜",
    "candle": "蠟燭", "capacity": "容量", "carpet": "地毯", "case": "盒",
    "chain": "鎖鏈", "chainmail": "鎖子甲", "chainshirt": "鎖子衫", "charm": "護符",
    "chime": "鐘鈴", "circlet": "頭環", "claw": "爪", "cloak": "斗篷",
    "clothes": "衣服", "club": "棍棒", "cold": "寒冷", "commanding": "號令",
    "common": "普通", "comprehension": "理解", "constitution": "體質", "control": "控制",
    "crystal": "水晶", "cube": "方塊", "cubic": "立方", "dagger": "匕首",
    "dancing": "舞動", "dark": "黑暗", "darkvision": "黑暗視覺", "dart": "飛鏢",
    "defense": "防禦", "defender": "守護者", "dexterity": "敏捷", "dimensional": "次元",
    "disappearance": "消失", "disguise": "易容", "displacement": "移位", "dragon": "龍",
    "dragonkind": "龍族", "dread": "恐懼", "driftglobe": "漂浮球", "drum": "鼓",
    "dust": "粉塵", "dwarven": "矮人", "efficient": "高效", "elemental": "元素",
    "elven": "精靈", "energy": "能量", "evasion": "閃避", "eyes": "眼睛",
    "feather": "羽毛", "figurine": "雕像", "fire": "火焰", "flame": "火焰",
    "flaming": "熾焰", "flying": "飛行", "force": "力場", "fortitude": "強韌",
    "frost": "冰霜", "giant": "巨人", "glamoured": "幻飾", "gloves": "手套",
    "goggles": "護目鏡", "greataxe": "巨斧", "greatclub": "巨棍", "greatsword": "巨劍",
    "guardian": "守衛", "hammer": "錘", "handaxe": "手斧", "healing": "治療",
    "helm": "頭盔", "heroism": "英雄氣概", "holding": "收納", "horn": "號角",
    "horseshoes": "馬蹄鐵", "immovable": "不動", "invisibility": "隱形", "iron": "鐵",
    "javelin": "標槍", "jumping": "跳躍", "keen": "鋒銳", "lantern": "提燈",
    "leather": "皮甲", "light": "光明", "lightning": "閃電", "longbow": "長弓",
    "longsword": "長劍", "luck": "幸運", "mace": "釘頭錘", "magic": "魔法",
    "manual": "祕典", "mariner's": "水手", "medallion": "墜飾", "mind": "心靈",
    "mithral": "秘銀", "movement": "移動", "necklace": "項鍊", "night": "夜晚",
    "nine": "九", "oil": "油", "owl": "貓頭鷹", "pearl": "珍珠",
    "periapt": "護符", "plate": "板甲", "poison": "毒素", "portable": "攜帶式",
    "potion": "藥水", "power": "力量", "protection": "防護", "quiver": "箭袋",
    "rapier": "細劍", "regeneration": "再生", "resistance": "抗性", "restoration": "復原",
    "ring": "戒指", "robe": "長袍", "rod": "權杖", "rope": "繩索",
    "scale": "鱗甲", "scimitar": "彎刀", "scroll": "卷軸", "shield": "盾牌",
    "shortbow": "短弓", "shortsword": "短劍", "silvered": "鍍銀", "slippers": "拖鞋",
    "sling": "投石索", "spear": "長矛", "speed": "速度", "spell": "法術",
    "spider": "蜘蛛", "staff": "法杖", "stealth": "隱匿", "stone": "石頭",
    "strength": "力量", "striding": "大步", "swimming": "游泳", "sword": "劍",
    "telepathy": "心靈感應", "tentacles": "觸手", "thunder": "雷鳴", "tome": "典籍",
    "tongues": "巧言", "trident": "三叉戟", "truth": "真實", "unarmed": "徒手",
    "underwater": "水下", "vicious": "惡毒", "wand": "魔杖", "warhammer": "戰錘",
    "warning": "警告", "water": "水", "weapon": "武器", "wings": "飛翼",
    "winged": "飛翼", "winterlands": "寒地", "wondrous": "奇物", "woodlands": "林地",
    # Feature / trait vocabulary
    "ancestry": "血統", "arcane": "祕法", "aspect": "面向", "aura": "靈光",
    "battle": "戰鬥", "beast": "野獸", "breath": "吐息", "brutal": "殘暴",
    "casting": "施法", "critical": "重擊", "cunning": "靈巧", "damage": "傷害",
    "discipline": "修練", "divine": "神聖", "domain": "領域", "endurance": "耐力",
    "expertise": "專業知識", "favored": "宿敵", "feral": "野性", "fey": "妖精",
    "focus": "專注", "frenzy": "狂亂", "improvement": "提升", "initiative": "先攻",
    "inspiration": "激勵", "invocation": "祕法祈喚", "ki": "真氣", "legacy": "傳承",
    "mastery": "精通", "metamagic": "超魔法", "nimbleness": "靈巧", "oath": "誓言",
    "path": "道途", "primal": "原初", "proficiency": "熟練", "relentless": "不屈",
    "ritual": "儀式", "savage": "野蠻", "secret": "祕密", "secrets": "祕密",
    "sense": "感知", "senses": "感官", "style": "風格", "tradition": "學派",
    "training": "訓練", "trance": "出神", "toughness": "強韌", "wild": "荒野",
    # Common grammatical/domain words
    "all": "全體", "and": "與", "any": "任意", "bonus": "加值", "choice": "選擇",
    "choose": "選擇", "combat": "戰鬥", "extra": "額外", "greater": "高等", "improved": "強化",
    "lesser": "次等", "level": "等級", "minor": "次級", "of": "之", "other": "其他",
    "pack": "套組", "plus": "加值", "the": "", "tool": "工具", "tools": "工具", "two": "二",
    "use": "使用", "uses": "次使用", "versatile": "多才多藝", "without": "無",
}

# Full-sentence SRD Acolyte roleplay suggestions are short structured M02-D
# presentation, not M02-E long-form descriptions.
ROLEPLAY_TEXT: dict[str, str] = {
    "I idolize a particular hero of my faith, and constantly refer to that person's deeds and example.": "我崇拜信仰中的某位英雄，經常引用其事蹟與榜樣。",
    "I can find common ground between the fiercest enemies, empathizing with them and always working toward peace.": "即使面對最激烈的敵對雙方，我也能找到共同點、理解彼此並努力促成和平。",
    "I see omens in every event and action. The gods try to speak to us, we just need to listen.": "我從每件事與每個行動中看見預兆；諸神一直試著對我們說話，我們只需要傾聽。",
    "Nothing can shake my optimistic attitude.": "沒有任何事能動搖我的樂觀態度。",
    "I quote (or misquote) sacred texts and proverbs in almost every situation.": "幾乎在任何場合，我都會引用（或錯引）聖典與箴言。",
    "I am tolerant (or intolerant) of other faiths and respect (or condemn) the worship of other gods.": "我對其他信仰抱持寬容（或不寬容）的態度，並尊重（或譴責）對其他神祇的崇拜。",
    "I've enjoyed fine food, drink, and high society among my temple's elite. Rough living grates on me.": "我曾在神殿菁英之間享受美食、美酒與上流社交，因此粗糙的生活令我難受。",
    "I've spent so long in the temple that I have little practical experience dealing with people in the outside world.": "我在神殿生活太久，幾乎沒有與外界人士打交道的實際經驗。",
    "Tradition. The ancient traditions of worship and sacrifice must be preserved and upheld.": "傳統。古老的崇拜與祭祀傳統必須被保存並維護。",
    "Charity. I always try to help those in need, no matter what the personal cost.": "慈善。無論個人要付出什麼代價，我總會努力幫助有需要的人。",
    "Change. We must help bring about the changes the gods are constantly working in the world.": "改變。我們必須協助促成諸神持續在世界中推動的變化。",
    "Power. I hope to one day rise to the top of my faith's religious hierarchy.": "權力。我希望有一天能登上自己信仰體系的最高位置。",
    "Faith. I trust that my deity will guide my actions. I have faith that if I work hard, things will go well.": "信念。我相信神祇會引導我的行動，也相信只要努力，事情終將順利。",
    "Aspiration. I seek to prove myself worthy of my god's favor by matching my actions against his or her teachings.": "志向。我努力讓自己的行動符合神祇教誨，以證明自己值得獲得恩寵。",
    "I would die to recover an ancient relic of my faith that was lost long ago.": "為了找回信仰中失落已久的古老聖物，我願意付出生命。",
    "I will someday get revenge on the corrupt temple hierarchy who branded me a heretic.": "總有一天，我會向那群把我打成異端的腐敗神殿高層復仇。",
    "I owe my life to the priest who took me in when my parents died.": "父母過世後收留我的祭司救了我一命，我欠他一份恩情。",
    "Everything I do is for the common people.": "我所做的一切都是為了平民百姓。",
    "I will do anything to protect the temple where I served.": "為了保護我曾侍奉的神殿，我願意做任何事。",
    "I seek to preserve a sacred text that my enemies consider heretical and seek to destroy.": "我努力保存一部敵人視為異端並想摧毀的聖典。",
    "I judge others harshly, and myself even more severely.": "我嚴厲評斷他人，對自己更是如此。",
    "I put too much trust in those who wield power within my temple's hierarchy.": "我過度信任神殿體系中掌握權力的人。",
    "My piety sometimes leads me to blindly trust those that profess faith in my god.": "我的虔誠有時會讓我盲目信任自稱信奉我神祇的人。",
    "I am inflexible in my thinking.": "我的思考方式很僵化。",
    "I am suspicious of strangers and expect the worst of them.": "我對陌生人抱持懷疑，並總預期他們會做出最糟的事。",
    "Once I pick a goal, I become obsessed with it to the detriment of everything else in my life.": "一旦選定目標，我就會執著其中，甚至犧牲生活中的其他一切。",
}


@dataclass(frozen=True)
class Unknown:
    key: str
    canonical: str
    token: str


def _normalize_token(token: str) -> str:
    return token.strip(" .,:;!?()[]{}\"'“”‘’").lower()


def _join(parts: list[str]) -> str:
    return "".join(part for part in parts if part)


def _translate_of_pattern(text: str, unknowns: list[Unknown], key: str) -> str | None:
    match = re.fullmatch(r"(.+?) of (?:the )?(.+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    left, right = match.groups()
    left_zh = translate_name(left, key=key, unknowns=unknowns)
    right_zh = translate_name(right, key=key, unknowns=unknowns)
    # Item-type heads read more naturally after the modifier in Chinese.
    if any(left.lower().startswith(prefix) for prefix in (
        "potion", "ring", "wand", "staff", "rod", "cloak", "boots", "belt",
        "amulet", "periapt", "helm", "gloves", "bracers", "robe", "manual",
        "tome", "bag", "bowl", "brazier", "candle", "carpet", "horn", "instrument",
    )):
        return right_zh + left_zh
    return right_zh + "之" + left_zh


def translate_name(text: str, *, key: str, unknowns: list[Unknown]) -> str:
    text = text.strip()
    if text in EXACT:
        return EXACT[text]

    # Parenthetical/count suffixes are common in class feature feeds.
    paren = re.fullmatch(r"(.+?)\s*\((.+)\)", text)
    if paren:
        base, suffix = paren.groups()
        return f"{translate_name(base, key=key, unknowns=unknowns)}（{translate_name(suffix, key=key, unknowns=unknowns)}）"

    # Preserve numeric/dice prefixes and +N variants as mechanics-sensitive tokens.
    comma_bonus = re.fullmatch(r"(.+?),\s*([+-]\d+)", text)
    if comma_bonus:
        base, bonus = comma_bonus.groups()
        return f"{bonus}{translate_name(base, key=key, unknowns=unknowns)}"
    leading_bonus = re.fullmatch(r"([+-]\d+)\s+(.+)", text)
    if leading_bonus:
        bonus, base = leading_bonus.groups()
        return f"{bonus}{translate_name(base, key=key, unknowns=unknowns)}"

    # Common proficiency wrappers.
    for prefix, zh in (
        ("Skill: ", "技能："),
        ("Saving Throw: ", "豁免："),
        ("Armor: ", "護甲："),
        ("Weapon: ", "武器："),
        ("Tool: ", "工具："),
        ("Musical Instrument: ", "樂器："),
    ):
        if text.startswith(prefix):
            return zh + translate_name(text[len(prefix):], key=key, unknowns=unknowns)

    of_value = _translate_of_pattern(text, unknowns, key)
    if of_value is not None:
        return of_value

    replaced = text
    # Replace reviewed multi-word concepts without losing surrounding level/use suffixes.
    for english, zh in sorted(PHRASES.items(), key=lambda item: len(item[0]), reverse=True):
        replaced = re.sub(rf"\b{re.escape(english)}\b", zh, replaced, flags=re.IGNORECASE)
    for english, zh in PROPER.items():
        replaced = re.sub(rf"\b{re.escape(english)}(?:'s|’s)?\b", zh, replaced, flags=re.IGNORECASE)

    # Tokenize while preserving mechanics-sensitive punctuation and numbers.
    chunks = re.findall(r"[A-Za-z][A-Za-z'’-]*|\d+d\d+|\d+|[+×x/-]|[^A-Za-z0-9+×x/\-]+", replaced)
    out: list[str] = []
    for chunk in chunks:
        if not re.fullmatch(r"[A-Za-z][A-Za-z'’-]*", chunk):
            # Collapse ordinary whitespace once words have become ideographs.
            if chunk.isspace():
                continue
            out.append(chunk)
            continue
        normalized = _normalize_token(chunk)
        translated = WORDS.get(normalized)
        if translated is None:
            # Singularize a few regular plurals before declaring an authoring gap.
            if normalized.endswith("s"):
                translated = WORDS.get(normalized[:-1])
            if translated is None and normalized.endswith("es"):
                translated = WORDS.get(normalized[:-2])
        if translated is None:
            unknowns.append(Unknown(key=key, canonical=text, token=chunk))
            # Keep a conspicuous authoring marker; strict mode forbids committing it.
            translated = f"〔未譯:{chunk}〕"
        out.append(translated)

    value = _join(out)
    # Clean punctuation spacing introduced by the source format.
    value = value.replace(" ,", "，").replace(",", "，").replace(" / ", "／")
    value = value.replace("'", "").replace("’", "")
    return value


def _extract_acolyte_roleplay(entry: dict[str, Any]) -> dict[str, list[str]]:
    data = entry["data"]
    result: dict[str, list[str]] = {}
    for field in ("personality_traits", "ideals", "bonds", "flaws"):
        source = data.get(field, {})
        options = source.get("from", {}).get("options", []) if isinstance(source, dict) else []
        values: list[str] = []
        for option in options:
            if not isinstance(option, dict):
                continue
            raw = option.get("string") if field != "ideals" else option.get("desc")
            if isinstance(raw, str):
                values.append(raw)
        if values:
            result[field] = values
    return result


def _required_rules() -> list[dict[str, Any]]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return [
        rule
        for rule in policy["rules"]
        if rule.get("localizable")
        and rule.get("currently_user_visible")
        and "zh-TW" in rule.get("required_locales", [])
        and rule.get("kind") in REQUIRED_KINDS
        and rule.get("pack") in {"*", "srd5.1"}
    ]


def build_overlay() -> tuple[dict[str, Any], dict[str, Any]]:
    rules = _required_rules()
    required_paths_by_kind: dict[str, set[str]] = {}
    for rule in rules:
        required_paths_by_kind.setdefault(rule["kind"], set()).add(rule["field_path"])

    entries_out: dict[str, dict[str, str]] = {}
    unknowns: list[Unknown] = []
    category_report: dict[str, dict[str, int]] = {}

    for kind, filename in CATEGORY_BY_KIND.items():
        entries = json.loads((SRD_ROOT / filename).read_text(encoding="utf-8"))
        paths = required_paths_by_kind.get(kind, set())
        if not paths:
            continue
        field_count = 0
        for entry in entries:
            key = entry["key"]
            localized: dict[str, str] = {}
            if "name" in paths:
                localized["name"] = translate_name(entry["name"], key=key, unknowns=unknowns)
                field_count += 1

            if kind == "background":
                if "data.feature.name" in paths:
                    feature = entry.get("data", {}).get("feature")
                    if isinstance(feature, dict) and isinstance(feature.get("name"), str):
                        localized["data.feature.name"] = translate_name(
                            feature["name"], key=key, unknowns=unknowns
                        )
                        field_count += 1
                roleplay = _extract_acolyte_roleplay(entry)
                for field, values in roleplay.items():
                    pattern = f"data.roleplay_suggestions.{field}.*"
                    if pattern not in paths:
                        continue
                    for position, value in enumerate(values):
                        translated = ROLEPLAY_TEXT.get(value)
                        if translated is None:
                            unknowns.append(Unknown(key=key, canonical=value, token="<structured-text>"))
                            translated = "〔未譯:structured-text〕"
                        localized[f"data.roleplay_suggestions.{field}.{position}"] = translated
                        field_count += 1

            if localized:
                entries_out[key] = localized
        category_report[kind] = {
            "entry_count": len(entries),
            "required_field_count": field_count,
        }

    # Deduplicate unknown diagnostics while retaining all affected canonical names.
    unique_unknowns = sorted(
        {(item.key, item.canonical, item.token) for item in unknowns},
        key=lambda item: (item[2].lower(), item[1], item[0]),
    )
    report = {
        "schema_version": 1,
        "pack": "srd5.1",
        "locale": "zh-TW",
        "method": "AI-assisted deterministic authoring + reviewed terminology mappings",
        "categories": category_report,
        "localized_entry_count": len(entries_out),
        "required_field_count": sum(item["required_field_count"] for item in category_report.values()),
        "unknown_count": len(unique_unknowns),
        "unknowns": [
            {"key": key, "canonical": canonical, "token": token}
            for key, canonical, token in unique_unknowns
        ],
    }
    overlay = {
        "schema_version": 1,
        "locale": "zh-TW",
        "entries": entries_out,
    }
    return overlay, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=SRD_ROOT / "locales" / "zh-TW.json")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--strict", action="store_true", help="fail when any English token remains unmapped")
    args = parser.parse_args()

    overlay, report = build_overlay()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "M02-D SRD zh-TW candidate: "
        f"{report['localized_entry_count']} entries / "
        f"{report['required_field_count']} required fields / "
        f"{report['unknown_count']} unknown mappings"
    )
    if report["unknown_count"]:
        for item in report["unknowns"]:
            print(f"UNKNOWN {item['token']!r}: {item['canonical']} [{item['key']}]")
        if args.strict:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

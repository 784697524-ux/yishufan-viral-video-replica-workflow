# 复刻合同 JSON 规范（schema v4）

每个新项目必须在生成分镜前创建 `08_replica_contract.json`。它是验证器的唯一机器真相源，用来防止漏剧情、分段越界、照片错配、音乐丢失、指定文字遗漏和AI表误覆盖。

## 必填结构

下例为节省篇幅只展开`C01`；实际合同的`candidates`必须至少包含`C01`至`C05`五套完整对象。

```json
{
  "schema_version": 4,
  "mode": "高保真视觉复刻",
  "brief_alignment": {
    "requested_mode": "高保真视觉复刻",
    "resolved_mode": "高保真视觉复刻",
    "requested_duration_seconds": 40.7,
    "ai_table_requested": true,
    "production_scope": "ai_table_handoff"
  },
  "source_sha256": "与00_source_manifest.json一致",
  "target_duration_seconds": 40.7,
  "deliverables": {
    "source_manifest": "00_source_manifest.json",
    "analysis": "01_reference_analysis.md",
    "facts": "02_product_facts.md",
    "visual_lock": "02_visual_lock.md",
    "mapping": "03_structure_mapping.md",
    "script": "04_script.md",
    "qc": "06_pre_generation_qc.md",
    "character_sheet": "character/character_sheet.png",
    "timeline_manifest": "watch/timeline_0_5s/timeline_manifest.json"
  },
  "evidence_review": {
    "fixed_timeline_manual_reviewed": true,
    "reviewed_frame_count": 82,
    "reviewed_last_timestamp_seconds": 40.5
  },
  "production_design": {
    "product_identity": {
      "reference_assets": [
        {
          "file": "assets/product_front.png",
          "sha256": "产品参考图SHA-256",
          "role": "front"
        }
      ],
      "locked_features": {
        "shape": "外形不可变特征",
        "proportion": "比例不可变特征",
        "color": "配色不可变特征",
        "material": "材质不可变特征",
        "structure": "结构不可变特征",
        "logo": "Logo位置、字形和颜色；看不清时写明不可新增"
      },
      "unknown_view_policy": "do_not_invent"
    },
    "visual_style": {
      "lock_id": "STYLE_LOCK_V1",
      "lighting": "统一光线规则",
      "color_palette": "统一色彩规则",
      "composition": "统一构图规则",
      "lens_and_camera": "统一镜头语言",
      "character_rules": "统一人物规则",
      "environment_rules": "统一场景规则",
      "image_texture": "统一材质和画面质感",
      "reusable_prompt": "每个Clip必须逐字带入的风格提示词",
      "negative_style_constraints": ["只写本项目明确禁用的风格"]
    },
    "motion_profile": "narrative_drama",
    "music_strategy": {
      "status": "source_locked",
      "source_file": "audio/clip01_reference_music.mp3"
    },
    "motion_beats": [
      {
        "prompt_id": "P01",
        "script_id": "S01",
        "clip_id": "clip01",
        "start_state": "人物、产品和环境的起始状态",
        "character_action": "人物持续动作",
        "product_action": "产品如何参与动作",
        "product_visibility": "visible",
        "environment_reaction": "环境受到动作影响后的变化",
        "camera_motion": "一个主要摄影机运动",
        "speed_change": "速度如何变化",
        "end_state": "镜头结束状态",
        "transition_trigger": "触发下一镜头的动作或遮挡",
        "music_cue": "动作对应的真实音乐节点",
        "handoff_in": "START",
        "handoff_out": "END",
        "motion_intent": "dynamic",
        "camera_removal_still_dynamic": true,
        "motion_level": 3,
        "complex_action": false,
        "keyframe_files": []
      }
    ]
  },
  "clips": [
    {
      "id": "clip01",
      "start_seconds": 0,
      "end_seconds": 15,
      "prompt_file": "05_seedance_prompts.md",
      "prompt_marker": "## Clip 01",
      "storyboard_files": ["storyboard/clip01_01.png"]
    }
  ],
  "continuity": [
    {
      "from_clip_id": "clip01",
      "to_clip_id": "clip02",
      "tail_file": "storyboard/clip01_09.png",
      "head_file": "storyboard/clip02_01.png"
    }
  ],
  "reference_beats": [
    {
      "reference_id": "R01",
      "script_id": "S01",
      "prompt_id": "P01",
      "clip_id": "clip01",
      "source_start_seconds": 0,
      "source_end_seconds": 3.3,
      "target_start_seconds": 0,
      "target_end_seconds": 3.3,
      "storyboard_file": "storyboard/clip01_01.png",
      "required_terms": ["必须保留的动作、道具含义或原片反转句"]
    }
  ],
  "audio_assets": [
    {
      "file": "audio/clip01_reference_music.mp3",
      "clip_id": "clip01",
      "source_start_seconds": 5.6,
      "source_end_seconds": 10.1,
      "use_start_seconds": 5.6,
      "use_end_seconds": 10.1,
      "must_use_original_mix": true
    }
  ],
  "visual_text_requirements": [
    {
      "storyboard_file": "storyboard/clip02_fan.png",
      "clip_id": "clip02",
      "exact_text": "银泰中心",
      "manual_visual_verified": true
    }
  ],
  "creative_room": {
    "reference_mechanism_dna": {
      "opening_hook": "第一秒的异常动作或问题",
      "viewer_question": "观众继续观看等待的答案",
      "misbelief": "前半段故意建立的错误判断",
      "conflict_engine": "持续推动人物对抗的力量",
      "reversal_mechanism": "改变权力、因果或道具含义的方法",
      "emotional_payoff": "观众最终得到的情绪回报",
      "final_memory_point": "最后三秒的动作或回扣"
    },
    "candidates": [
      {
        "id": "C01",
        "logline": "一句话讲清人物、困境、选择和结果",
        "conflict": "本方案的冲突",
        "character_choice": "人物主动做出的选择",
        "visible_consequence": "选择造成的可见后果",
        "unexpected_turn": "意外但有铺垫的转折",
        "setup_evidence": "支持转折成立的前置证据",
        "product_role": "商品如何改变人物选择或结果",
        "ending_payoff": "结尾如何回答开头",
        "difference_axes": ["人物关系", "商品介入方式"],
        "mechanism_signature": "本方案独有的冲突-选择-后果-反转组合",
        "rejection_reason": "未入选时必填；入选方案可为空",
        "scorecard": {
          "hook": 18,
          "causality": 23,
          "novelty": 17,
          "product_causality": 14,
          "reference_mechanism_fidelity": 9,
          "generatability": 9,
          "total": 90,
          "hard_vetoes": []
        }
      }
    ],
    "selected_candidate_id": "C01",
    "selection_reason": "为什么该方案比其他方案更强且更可生成",
    "table_read": {
      "passed": true,
      "product_removal_breaks_story": true,
      "dialogue_read_aloud": true,
      "issues": [],
      "checks": [
        {
          "story_step_id": "problem",
          "viewer_question": "这一拍之后观众在等什么",
          "beat_change": "这一拍新增的动作、权力或认知",
          "next_cause": "哪个可见动作推动下一拍",
          "performable_in_seconds": true
        }
      ]
    }
  },
  "narrative_qc": {
    "dramatic_question": "人物眼下必须解决的具体问题",
    "world_rule": {"allows_unexplained_magic": false},
    "product_hook_user_requested": false,
    "story_chain": [
      {
        "id": "problem",
        "type": "problem",
        "script_ids": ["S01"],
        "actor": "女主",
        "action": "发现无人愿意试吃",
        "product_role": "obstacle"
      },
      {
        "id": "choice",
        "type": "choice",
        "script_ids": ["S02"],
        "actor": "女主",
        "action": "把试吃券递给唯一停步的顾客",
        "caused_by": "problem",
        "product_role": "solution"
      },
      {
        "id": "consequence",
        "type": "consequence",
        "script_ids": ["S03"],
        "actor": "顾客",
        "action": "尝一口后回头招呼同伴",
        "visible_result": "两位同伴走向摊位",
        "caused_by": "choice",
        "product_role": "none"
      },
      {
        "id": "resolution",
        "type": "resolution",
        "script_ids": ["S04"],
        "actor": "掌柜",
        "action": "重新端出下一盘菜",
        "visible_result": "摊位前出现第一批真实顾客",
        "caused_by": "consequence",
        "answers": "problem",
        "product_role": "none"
      }
    ],
    "resolution": {"script_id": "S04", "answer": "第一位顾客被人物行动说服并带来同伴"},
    "clip_policies": [
      {"clip_id": "clip01", "delivery_mode": "dialogue_drama"}
    ]
  },
  "dialogue_requirements": [
    {
      "id": "opening_hook",
      "clip_id": "clip01",
      "match_mode": "exact",
      "expected_text": "满桌好菜，怎么一个人都不肯尝？",
      "start_seconds": 0,
      "end_seconds": 3
    }
  ],
  "prop_continuity_requirements": [
    {
      "id": "trial_coupon",
      "introduction_script_id": "S02",
      "event_ids": ["coupon_taken_out", "coupon_handed_over", "coupon_accepted"]
    }
  ],
  "director_requirements": {
    "final_memory_step_id": "resolution",
    "performance_arcs": [
      {
        "id": "shopkeeper_arc",
        "character": "掌柜",
        "states": [
          {"id": "anxious", "script_id": "S01"},
          {"id": "waiting", "script_id": "S02"},
          {"id": "relieved", "script_id": "S04"}
        ]
      }
    ]
  },
  "finale_policy": {
    "type": "story_action"
  },
  "aitable_handoff": {
    "protected_field_ids": ["自动视频结果字段ID"],
    "records": [
      {
        "clip_id": "clip01",
        "write_field_ids": ["提示词字段ID", "附件字段ID"],
        "attachment_filenames": [
          "character_sheet.png",
          "clip01_01.png",
          "clip01_reference_music.mp3"
        ]
      }
    ]
  }
}
```

## 不变量

- 新项目使用`schema_version=4`。历史schema v3仍可读取，但验证器只给兼容性警告，不会为其补出产品/风格锁和运动链证据。
- `mode`只能有一个值，禁止把三种模式写进同一合同。
- `brief_alignment`必须锁定用户原始模式与时长，并用`ai_table_requested`和`production_scope`记录素材包、AI表交付或完整视频。任何模式或时长变化都要分别写明原因，并将对应的`*_user_confirmed`设为`true`；不得由程序静默改约。AI表交付为`true`时，合同不得省略`aitable_handoff`。
- `deliverables.visual_lock`必须指向`02_visual_lock.md`。`product_identity.reference_assets`至少一项且文件/哈希真实一致；六项产品特征必须逐项锁定，未知角度一律`do_not_invent`。
- `visual_style`必须给出唯一`lock_id`和可复用提示词；两者进入视觉锁文件，其中`lock_id`和完整风格提示词还必须出现在每个Clip提示词。`product_visibility=visible`的节拍必须在对应Clip提示词中引用至少一个锁定产品资产文件名；`withheld_for_reveal`允许前段不露商品，避免破坏剧情揭示。
- `production_design.motion_beats`与`reference_beats`一一对应，`prompt_id/clip_id/script_id`不得错配。运动链从`START`开始、以`END`结束，相邻`handoff_out/handoff_in`必须相同。
- 动态节拍必须写完起始状态、人物动作、产品动作、环境反应、运镜、速度变化、结束状态、转场触发和音乐卡点，并确认删除运镜后主体/环境仍有运动。有意静止须写`stillness_reason`；复杂动作至少绑定起/中/终三张已纳入Clip的关键帧。
- `motion_profile=continuous_motion_ad`时至少有三段动态节拍、三个不同运动等级且最高达到4；这条规则不套用到忠于原片静止段的高保真复刻。
- `production_scope=full_video`时，音乐必须已锁定原片或经用户确认。`pending_selection`只能停在生成前，不能进入付费视频生成。
- `clips`必须从0秒连续覆盖目标时长，无空洞、无重叠；每段1至15秒。写AI表时人物、分镜、音频和商品素材合计最多9个附件，因此剧情分镜必须为其他必需附件预留名额。
- 高保真模式必须提供0.5秒固定时间线清单，并记录实际查看数量和最后时间戳；查看场景关键帧不能替代这一步。
- 高保真模式下，`reference_beats`必须按原片顺序列出每个因果变化和道具意义变化。分析文件中出现的所有`Rxx`均须在合同中映射。
- 高保真`reference_beats`必须用起止时间连续覆盖原片和目标片全长，每个生成片段最多承载3个因果节拍；超过就拆段，不能把事件塞进15秒后让模型自行压缩。
- 每个节拍的`Rxx/Sxx/Pxx/分镜文件名`必须同时出现在映射文件；`Sxx`须出现在脚本；`Pxx`和分镜文件名须出现在对应提示词。
- `creative_room`必须先提取参考片机制DNA，再提供至少5套概念。每套至少填写两个`difference_axes`并使用不同`mechanism_signature`；六项评分总分必须由分项相加。入选方案不低于85分且`hard_vetoes`为空，未入选方案必须写`rejection_reason`。
- `creative_room.table_read`必须逐项覆盖`narrative_qc.story_chain`，对白完成朗读计时，所有问题清零，并确认删除商品会破坏故事因果；否则不得进入逐秒剧本。
- `narrative_qc.story_chain`必须按“问题→选择→后果→结局”展开；每一步由`caused_by`指向更早步骤，最后一步必须`answers`开头问题。商品至少承担证据、筹码、诱因、障碍或解决工具中的一种，不能全部写成`none`。
- 不再由作者自报节拍数、口播秒数和汉字数。`clip_policies`只声明表达类型，`analyze_script.py`直接解析逐秒脚本：每段最多3个可执行单元；剧情对白最多占60%，蒙太奇旁白最多75%，古诗朗读最多92%，语速不超过4.2字/秒；剧情片每段最多2个说话单元和1行主商品事实。
- `dialogue_requirements`覆盖每个非静音Clip。`exact`用于限定时间窗内逐字相同，`contains`用于完整关键句，`terms`用于多个不可丢失词。
- 所有关键道具写入`prop_continuity_requirements`，至少列出取出/出现、交接/使用和结果事件。`director_requirements`必须定义结尾记忆点和至少一条“起点→转折→结果”表演弧。
- `finale_policy`必须二选一：`{"type":"story_action"}`要求结尾记忆点在最后3秒发生；真实商品图收尾时使用`{"type":"source_fact_card","source_file":"assets/product_card.png","start_seconds":28,"end_seconds":30}`，剧情解决证据必须早于卡片开始，卡片默认1至2秒且最长2.5秒。
- `required_terms`只放不能丢失的动作、反转对白或道具意义，不放宽泛形容词。
- 音乐或原声需要输入模型时，必须同时记录原片截取区间和目标片使用区间；文件名与“不换其他音乐”必须写进对应提示词。
- 画面允许出现指定文字时，将其写入`visual_text_requirements`，并把通用负面词改成“除白名单文字外无其他文字”。生图后必须真实查看，再把`manual_visual_verified`设为`true`。
- 需要写AI表时才提供`aitable_handoff`。自动视频、公式和生成结果字段必须放入`protected_field_ids`，不得出现在`write_field_ids`；每条记录的`attachment_filenames`合计不得超过9个且不得重复。

## 验证

生成前只认总门禁结果：

```bash
python3 scripts/run_quality_gate.py "<项目目录>" --stage pre-generation \
  --out "<项目目录>/07_quality_gate_pre_generation.json"
```

AI表返回片段后，创建`09_delivery_manifest.json`：

```json
{"outputs":[{"clip_id":"clip01","file":"renders/clip01.mp4"}]}
```

同时准备ASR清单`10_asr_manifest.json`和Watch证据`11_director_qc.json`，再运行：

```bash
python3 scripts/run_quality_gate.py "<项目目录>" --stage pre-stitch \
  --delivery-manifest "<项目目录>/09_delivery_manifest.json" \
  --asr-manifest "<项目目录>/10_asr_manifest.json" \
  --director-manifest "<项目目录>/11_director_qc.json" \
  --out "<项目目录>/12_quality_gate_pre_stitch.json"
```

只有返回`allow_stitch`才能合片；门禁会指出应退回Brief、故事、剧本、分镜提示词、生成、对白提示词或导演提示词哪一层。

旧包临时检查可用`--legacy`，但其结果不能作为新项目交付依据。

成片生成后还必须运行：

```bash
python3 scripts/validate_render.py "<原片>" "<成片>" --out "<项目目录>/质检/render"
```

该步骤会拦截总时长被截短、显著镜头变化密度过低和音频能量明显变弱的成片，并输出原片/成片0.5秒帧供导演复盘。

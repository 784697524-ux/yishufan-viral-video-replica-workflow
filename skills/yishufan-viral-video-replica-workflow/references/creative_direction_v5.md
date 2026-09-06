# schema v5：创意、美术与真实视频证据

> V7.3新生产由`03_director_plan.json`统一承载概念、逐拍因果、镜头和连续状态；本文件保留美术证据及`08_replica_contract.json`兼容字段。不要再人工创建内容重复的`03_candidates.md`或`03_structure_mapping.md`，需要的机器字段按Sxx/Pxx引用导演计划。

与`replica_contract_schema.md`基础字段合用；新项目的版本值为5。本文件覆盖旧版候选数量、商品删除勾选、静态源和生图准入规则，不删除事实、产品、映射、运动、对白与权限约束。评分只供比较，不能自动证明好看。

## 1. 静态插画不是无证据视频

合同`reference_source.kind="static_images"`。`00_source_manifest.json`使用：

```json
{"source_type":"static_images","sha256":"素材集身份摘要","duration_seconds":null,"audio_present":false,
 "assets":[{"id":"I01","file":"assets/reference01.webp","sha256":"真实文件SHA256","role":"scene"}]}
```

资产角色为`scene/style_detail/character_detail`，描述原图类型；不是后续生成调用角色。逐张看完后，`evidence_review.static_review_file`指向JSON：`{"assets":[{"id":"I01","source_sha256":"对应文件SHA","observation":"本图具体色彩、线面、人物、构图观察"}]}`。必须覆盖全部源图。

素材集摘要可对按ID排序的`id:sha256`串算SHA；合同`source_sha256`与清单一致。每个实际图文件另行真实hash校验。不能写原片时长、timeline、frame_count或已听原片对白。静态`reference_beats`的`source_start_seconds/source_end_seconds`为null，新增`source_asset_ids`，目标时段仍连续覆盖全片。商业混合静态模式只继承视觉与内容关系，目标剧情时序原创。

## 2. 创作方向与独立审稿

合同新增：

```json
"creative_direction": {
  "audience_desire":"观众想得到什么",
  "commercial_promise":"已经确认的商业利益与限制",
  "scene_promise":"用户要求必须在画面兑现的世界与体验",
  "minimum_reversals":2,
  "required_scene_actions":["不同参与商家递出试样","不同客人实际尝味并反应"],
  "review_file":"06_creative_review.json"
}
```

反转数量按用户目标填写，不给每种广告强加两个反转。`creative_room`保留机制、3至5个真正不同的候选、差异、选择/淘汰原因与桌读；旧分数可比较，不再因作者自己满85分就准入。桌读增加`product_removal_observation`、`commercial_relevance_evidence`，说明删商品后的具体损失及商业关联，不强迫`product_removal_breaks_story=true`。

用户说“时长自定”时，brief_alignment用`duration_policy="user_delegated"`、`requested_duration_seconds=null`、`duration_authority="用户原话"`；target_duration_seconds由桌读决定。固定时长仍须确认才能改。pre-visual可暂不填aitable_handoff；pre-generation前只读目标表结构后补全，不提前写表。

`06_creative_review.json`：

```json
{
  "script":{"file":"04_script.md","sha256":"当前脚本SHA"},
  "editor":{"kind":"independent_agent","name":"真实审阅者标识",
    "most_likely_swipe_away":"具体秒点/脚本ID及原因","revision_evidence":"怎么改以及修改后的可见动作"},
  "decision":"approved","unresolved_issues":[],
  "hook":{"script_id":"S01","end_seconds":3,"visible_action":"具体异常动作",
    "viewer_question":"为什么愿意继续看","benefit_cue":"观众得到什么的可见线索"},
  "retention_beats":[
    {"id":"E01","script_id":"S01","timestamp_seconds":0,"type":"setup",
     "expectation_before":"原以为…","visible_change":"观众看到…","expectation_after":"因此以为…",
     "consequence":"角色因此…","next_question":"接下来…"},
    {"id":"E02","script_id":"S02","timestamp_seconds":3,"type":"reversal","setup_id":"E01",
     "expectation_before":"上一判断","visible_change":"推翻判断的动作证据","expectation_after":"新的理解",
     "consequence":"推动后续的选择","next_question":"新的悬念"}
  ],
  "scene_action_coverage":[{"requirement":"与required_scene_actions某项完全一致","script_id":"S02","visible_action":"具体调度"}],
  "style_calibration":{}
}
```

示例省略其他拍点，真实账本最后一项必须是`type=payoff`；每个反转引用更早的setup，不能同一交接换人就算反转。编辑只能填`human`或真正执行过的`independent_agent`，不能把作者自审包装成独立审核。证据不足保持rejected/未决，交用户看草稿；不伪造批准。

## 3. 先美术母样，再人物表与批量分镜

`style_calibration.references`每项含`id/file/sha256/role/observation`。此处role是生成用途：`style_only/layout_reference/character_identity/product_fact`。必须有真实`style_only`源图。`source_axes`逐项填：

- `palette`：冷暖、主辅色块位置/面积、饱和度；不只写HEX。
- `line_and_fill`：勾线、线宽、平涂/晕染、装饰重复。
- `texture`：纸纹位置/强弱；不能用黄滤镜代替画法。
- `character_rendering`：脸部留白、五官比例、衣褶与体积塑造。
- `space`：散点/焦点透视、遮挡、层次、留白。
- `activity_density`：画面同时发生哪些事件；景物多不等于热闹。

`originality_plan`说明哪些具体人物、建筑、构图与动作重新创作，哪些画法/色彩关系保留。传原图作画法证据不等于直接交付原图；不抠用原图人物或独特建筑组合。

pre-visual可以尚无生成样张。通过后先生成并查看`master_scene`（包含建筑/人物/食物/群像的完整原创场景）与`character_detail`（人物细节，可含开场食欲近景）。将真实工具调用或生成任务记录保存在项目，不能假称已传源图。

pre-generation时`style_calibration.decision="approved"`，且`proofs`含上述两种role。每个proof含：`file/sha256/role/generation_reference_ids/generation_evidence`；最后两项填写实际输入源图ID与可追溯生成记录位置。每张图的`comparisons`含全部六轴，各为`{source_observation,candidate_observation,verdict:"pass"}`。源图原封不动充当新样张、漏传画法参考、任一轴fail/unknown都不能准入。将源图与同类景别母样并排看；统计仅辅助，不能把色域占比冒充“艺术相似度90%”。

`generation_evidence`不是说明句，而是`{file,sha256}`，绑定真实工具调用整理的JSON：`{tool_call_id,input_assets:[{file,sha256}],output_asset:{file,sha256}}`。所称源图和实际输出都要匹配，禁止伪造调用。母样与人物细节必须是不同SHA的独立图；静态style_only的id/file/sha256必须匹配原素材清单，不能偷换成无关风格图。

只有当带源图的生成端连续至少两次失败、每次均无输出并保存了真实失败记录时，才可使用`manual_observation_fallback`。它必须绑定失败记录、人工逐图提炼的style brief和实际观察的`style_only`源图ID；每个proof的生成记录写明`input_mode:"manual_observation_fallback"`、`manual_reference_ids`和空`input_assets`。此路径明确表示源图没有进入生成模型，不能同时填写`generation_reference_ids`或伪称直传成功；失败证据不足、风格brief未绑定、任何六轴不通过，均禁止进入生产表。

### 全部生产图的独立审阅

双母样通过不等于后续人物表、分镜都通过。`pre-generation`及后续阶段还读取`06_creative_review.json`中的`style_calibration.reviewer`与`style_calibration.production_asset_reviews`；`pre-visual`不要求尚未生成的这些图有审阅结果。

- `reviewer.kind`只能是`independent_agent`或`human`；`name`填真实美术审阅者标识，`asset_author`填其所审生成图的实际作者／制作负责人标识，不是剧本作者字段，也不用图像模型名代替制作责任人。`comparison_method`写实际怎样查看原参考与候选图，不能仅写“已通过”。审阅者不能批准自己创作的图；独立脚本编辑可以兼任美术审阅者，前提是未参与这些图的制作且确实逐张看过。
- 当前验证器只检查上述四项、允许的`kind`及`name != asset_author`，不会认证真实身份或核实多人分工。多人分图审阅时保留逐图实际作者与审阅记录，不把汇总JSON的人冒充审阅者，也不把一个代表名写成所有图的亲自审阅者；不能靠不同字符串伪造独立性。
- `production_asset_reviews`的`file`集合必须精确等于所有`clips[].storyboard_files`的并集，加上`deliverables.character_sheet`（若声明）。共享尾首图只写一次；不漏图、不重复，也不把未列入该集合的母样或商品图混进来。人数／分镜数量随真实合同变化，例如1张人物表＋7张独立分镜才是8项，不是固定要求8张。
- 每项绑定项目内实际图的相对`file`和当前`sha256`，图片须可解码。`identity_and_state_observation`写本图可见的身份、左右手持物、站位／视线及其时间锚点是起始还是结果；`identity_and_state_verdict`只有`pass`通行。人物表按身份、姿态与设定用途观察，不把多姿态误作多个角色。
- 每项`comparisons`必须有上述全部六轴，每轴含非空`source_observation`、`candidate_observation`及`verdict`。用原参考和这张实际生产图的具体观察比较，不复制母样结论；同类景别／用途对照，人物表白底不冒充场景缺色，人物表不存在的群像动作也不能编造。任一轴非`pass`、状态未通过、缺文件或哈希过期均阻断；修图后重新查看、更新该图证据并重跑门禁。

下面是合并到`style_calibration`的字段形状，保留已有`references/source_axes/originality_plan/proofs/decision`。示例仅演示一项，不是已经执行的审阅；实际须按合同展开全部生产图，观察内容须由真实审阅替换。

```json
{
  "reviewer": {
    "kind": "independent_agent",
    "name": "真实美术审阅者ID",
    "asset_author": "被审图实际制作负责人ID",
    "comparison_method": "逐张打开原参考与候选图，按同类景别比较六轴，并按脚本时间锚点检查身份与持物状态"
  },
  "production_asset_reviews": [{
    "file": "storyboard/B01_00s.png",
    "sha256": "此实际图的当前SHA256",
    "identity_and_state_observation": "具体身份、手中物及方向可见；说明本图对应哪一拍的起始或结果状态",
    "identity_and_state_verdict": "pass",
    "comparisons": {
      "palette": {"source_observation": "参考的主辅色块关系", "candidate_observation": "本图对应色块与偏差", "verdict": "pass"},
      "line_and_fill": {"source_observation": "参考的勾线和平涂手法", "candidate_observation": "本图实际线面表现", "verdict": "pass"},
      "texture": {"source_observation": "参考纹理的位置与强弱", "candidate_observation": "本图纸纹和颗粒的实际分布", "verdict": "pass"},
      "character_rendering": {"source_observation": "参考脸部、五官及衣褶画法", "candidate_observation": "本图人物的实际比例与上色", "verdict": "pass"},
      "space": {"source_observation": "参考透视、层次与留白", "candidate_observation": "本图同用途构图的实际空间关系", "verdict": "pass"},
      "activity_density": {"source_observation": "参考同用途画面的姿态或活动群组", "candidate_observation": "本图可见角色、动作状态与分组；静态图不证明动作已在视频执行", "verdict": "pass"}
    }
  }]
}
```

程序验证字段、资产哈希与覆盖关系，不证明审阅者确实看过、画面好看或视频执行成功；未看、未决或失败就如实记录，不能为了通过填`pass`。

## 4. 两阶段准入与提示词

```bash
python3 "${SKILL_DIR}/scripts/run_quality_gate.py" "<项目>" --stage pre-visual --out "<项目>/07_quality_gate_pre_visual.json"
python3 "${SKILL_DIR}/scripts/run_quality_gate.py" "<项目>" --stage pre-generation --out "<项目>/07_quality_gate_pre_generation.json"
```

第一层真实验证源图/事实/分析/映射/脚本/审核及风格计划，未来人物/分镜路径可以先声明。`allow_visual_tests`只允许校准样张，不允许写生产表。第二层要求真实可解码人物/分镜/提示词、双锁、样张比较全部完成。任何材料改变重跑，旧报告与当前`input_fingerprint`不一致不得沿用。只接受官方`status=ok+对应decision`；不能另写“静态补丁验证器”过滤错误，不把“仅草稿”写进生产提示词充当豁免。

对白可用普通引号、直写或「」；必须可解析。每个说话S行声明全片绝对`口播窗口`列，或在`dialogue_requirements`按`script_id`绑定`expected_text`与`speech_start_seconds/speech_end_seconds`（兼容原start/end）。数字/Latin另给全中文`spoken_text`，例如“一元”“恩加”，不得通过缩写少算。4.2字/秒是保守容量检查，不是自然表演证明。

短镜头可拼为模型允许长度，但Clip不是剧情单位。用分组群演、前中后景微动作、声桥与剪辑表现热闹；一个主动作不等于全景只能有一个人动。输入图按时间锚点声明，禁止把同一人物几个状态同时解释成多个角色。

## 5. 生成后必须回到真实视频

三段输入尾首一致≠三个生成结果连续。完整取回结果、按ID绑定、抽帧和双ASR后，见`quality_gate_manifests.md`新增v5字段。逐项检查人物数量/复制、道具持有者与动作阶段、出入方向、反转兑现、食欲回报、多商家证据、画风和商品口径。

报告必须区分脚本已错、参考解释/输入图已错、视频模型新增偏差。只有实际观看才能填写观察；程序校验的是材料和图像来源，不会证明审阅者诚实、艺术质量或未来完播率。最终音色/音乐/可懂度未真实听音则保持未验收。

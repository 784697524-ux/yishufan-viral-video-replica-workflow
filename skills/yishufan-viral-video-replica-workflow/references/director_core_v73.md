# V7.3 导演核心：一个计划管住故事、镜头和连续性

新生产先建立 `03_director_plan.json`，不要再把同一内容分别抄进候选稿、结构映射、故事链和分镜说明。`08_replica_contract.json` 只保留生产合同、资产、权限与发布门禁，并声明：

```json
{
  "schema_version": 5,
  "director_core_version": "7.3",
  "director_plan_file": "03_director_plan.json"
}
```

运行：

```bash
python3 "${SKILL_DIR}/scripts/validate_director_core.py" "<项目目录>"
```

官方 `run_quality_gate.py` 在合同声明 `director_core_version=7.3` 时会自动执行同一检查。

## 只保留三张表

1. `concepts`：默认 3 个真正不同的概念，每个只写一句故事、核心冲突、商品作用、结尾和淘汰理由；分数只用于比较，不写长篇自证。
2. `clips[].beats`：整片逐秒导演表。默认每个 15 秒 Clip 最多 3 拍、2 个有声回合；每拍只有一个主要人物动作和一个主要摄影机动作。
3. `required_scene_actions`：把用户要求的每个场面动作映射到真实 beat id，防止用旁白假装画面已经发生。

其他解释放在对应 beat 内，不另建重复文档。高保真视频需要原片 Rxx 时间码时，也写入 beat 的可选 `reference`，不再维护独立映射表。

## 每拍必须回答

- `viewer_question`：观众此刻在等什么答案。
- `new_information`：这一拍新增什么，不得只是换角度。
- `visible_action`：不听声音也能看见的动作与结果。
- `caused_by`：由哪一拍造成；第一拍为 `START` 或 null。
- `shot`：景别、一个人物主动作、一个摄影机动作、机位目的、动作触发的转场。
- `state_in/state_out`：同一组状态字段，出场必须逐字等于下一拍入场。
- `action_event`：事件 ID 与 `setup/progress/payoff` 阶段。

固定连续状态字段：`protagonist_id`、`left_hand`、`right_hand`、`prop_holders`、`position`、`gaze_target`、`action_phase`、`crowd_signature`。即使主角暂时出画，也要记录她在故事空间中的持续状态，不能让钱袋、小碟、人物位置或群众数量在镜间消失。

## 事件只允许兑现一次

同一 `action_event.id` 可以跨拍使用，但阶段只能向前：

```text
setup → progress → payoff
```

同一个事件只能有一个 `payoff` 拥有者。若 Clip01 末尾是“小勺停在唇前”，应记录 `setup` 或 `progress`；Clip02 开头才完成“入口、降勺、点头”的 `payoff`。禁止两段都把点头当结果，避免跨段重复和完播掉点。

## 商业事实与剧情对白分工

商场名、门店名、价格、权益、日期和 CTA 由 `controlled_voiceover`、`post_overlay` 或 `source_fact_card` 承担。角色对白只做冲突、选择和情绪。

角色说“免费、1元、不用付钱、0元”等敏感词时，必须在同拍且最晚前 4 秒提供准确的 `commercial_truth_cues`，并用 `supports_beat_ids` 绑定该拍。例：

```json
{
  "start_seconds": 0.25,
  "end_seconds": 4,
  "source": "post_overlay",
  "text": "1元购券参加｜参与品牌试吃免费",
  "supports_beat_ids": ["S01"]
}
```

图像与视频模型不负责写准确商业文字；上述提示是后期准确排版计划。

## 最小结构示意

```json
{
  "version": "7.3",
  "story_question": "她刚选定一家，为什么还要继续逛？",
  "scene_promise": "同一条热闹古街至少三组真实试吃动作",
  "concepts": [],
  "commercial_truth_cues": [],
  "clips": [{
    "clip_id": "clip01",
    "start_seconds": 0,
    "end_seconds": 15,
    "beats": [{
      "id": "S01",
      "start_seconds": 0,
      "end_seconds": 4,
      "purpose": "hook",
      "caused_by": "START",
      "viewer_question": "为什么不让她先买？",
      "new_information": "钱被退回，小试样进入同一空位",
      "visible_action": "先退钱，再递样；两个道具有清楚去向",
      "dialogue": {"speaker_mode": "character", "text": "先尝再说"},
      "shot": {
        "framing": "半身近景",
        "primary_character_action": "摊主先退钱再滑入小碟",
        "primary_camera_action": "固定机位",
        "camera_purpose": "同框证明动作先后和道具归属",
        "transition_trigger": "小碟停入姑娘左掌"
      },
      "state_in": {
        "protagonist_id": "G01",
        "left_hand": "空掌在案沿",
        "right_hand": "铜钱递出",
        "prop_holders": "铜钱:G01右手;钱袋:G01腰间;小碟:M01左手",
        "position": "第一摊左前",
        "gaze_target": "整份食物",
        "action_phase": "准备付款",
        "crowd_signature": "三组群众已在场但被遮挡"
      },
      "state_out": {
        "protagonist_id": "G01",
        "left_hand": "托同一小碟",
        "right_hand": "空手离开钱袋",
        "prop_holders": "铜钱:G01腰间钱袋;钱袋:G01腰间;小碟:G01左手",
        "position": "第一摊左前",
        "gaze_target": "小碟",
        "action_phase": "接样完成",
        "crowd_signature": "三组群众已在场但被遮挡"
      },
      "action_event": {"id": "退钱换试样", "phase": "payoff"}
    }]
  }],
  "required_scene_actions": [],
  "ending": {"beat_id": "S06", "visible_resolution": "姑娘继续走，另一份试样落碟"}
}
```

## 人工导演仍要判断

程序能阻止状态跳变、时间断层、重复 payoff、容量超载和敏感商业话术缺少早期限定，但不能判断表演是否好笑、镜头是否真正有美感。独立审稿只回答四件事：最可能划走的秒点、因果是否成立、动作是否能看懂、结尾是否兑现。任何一项失败就改 `03_director_plan.json` 与脚本，再跑门禁；不再追加新的说明文档来解释失败画面。

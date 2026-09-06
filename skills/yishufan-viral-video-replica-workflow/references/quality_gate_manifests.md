# 生成后质量清单规范

只在用户已经要求生成视频并取得结果后读取。本规范为`pre-stitch`提供三份输入，并为`pre-publish`增加最终成片清单。片段通过不等于最终合片通过。

## 1. AI表片段清单

`09_delivery_manifest.json`按合同Clip顺序列出，不按下载时间排序：

```json
{
  "outputs": [
    {"clip_id": "clip01", "file": "renders/clip01.mp4"}
  ]
}
```

程序用ffprobe回读实际时长、画幅和音轨；文件名、表格完成状态或下载成功不能替代回读。

## 2. 候选ASR清单

`10_asr_manifest.json`使用Clip内相对时间：

```json
{
  "clips": [
    {
      "clip_id": "clip01",
      "segments": [
        {"start_seconds": 0.0, "end_seconds": 2.8, "text": "满桌好菜怎么一个人都不肯尝"}
      ]
    }
  ]
}
```

使用阿里云候选ASR。ASR失败时不得编造文本；门禁保持失败，改由重新转写或人工听写后再提供可审计清单。ASR合并相邻句时，`exact`只要求目标字符连续且不被替换，不要求模型分段边界与脚本时间窗完全相同。

## 3. Watch导演证据

`11_director_qc.json`中的所有`evidence_file`必须位于项目目录内，并指向真实查看过的Watch帧。固定时间线必须看到每个Clip结尾。

```json
{
  "timeline_reviews": [
    {
      "clip_id": "clip01",
      "fixed_timeline_manual_reviewed": true,
      "reviewed_frame_count": 30,
      "reviewed_last_timestamp_seconds": 14.5
    }
  ],
  "story_steps": [
    {
      "id": "problem",
      "timestamp_seconds": 0.5,
      "observed": true,
      "observed_action": "掌柜端菜到街口但路人绕开",
      "evidence_file": "watch/generated_clip01/frame_0002.jpg"
    }
  ],
  "performance_arcs": [
    {
      "id": "shopkeeper_arc",
      "states": [
        {"id": "anxious", "timestamp_seconds": 0.5, "observed": true, "evidence_file": "watch/generated_clip01/frame_0002.jpg"},
        {"id": "waiting", "timestamp_seconds": 5.0, "observed": true, "evidence_file": "watch/generated_clip01/frame_0011.jpg"},
        {"id": "relieved", "timestamp_seconds": 12.5, "observed": true, "evidence_file": "watch/generated_clip01/frame_0026.jpg"}
      ]
    }
  ],
  "prop_events": [
    {"prop_id": "trial_coupon", "event_id": "coupon_taken_out", "timestamp_seconds": 3.5, "observed": true, "evidence_file": "watch/generated_clip01/frame_0008.jpg"},
    {"prop_id": "trial_coupon", "event_id": "coupon_handed_over", "timestamp_seconds": 5.0, "observed": true, "evidence_file": "watch/generated_clip01/frame_0011.jpg"},
    {"prop_id": "trial_coupon", "event_id": "coupon_accepted", "timestamp_seconds": 6.0, "observed": true, "evidence_file": "watch/generated_clip01/frame_0013.jpg"}
  ],
  "continuity_checks": [],
  "hard_vetoes": [],
  "scores": {
    "causality": 25,
    "performance": 18,
    "reference_mechanism": 13,
    "product_integration": 14,
    "generatability": 9,
    "camera_sound": 8,
    "fact_accuracy": 5
  }
}
```

评分满分100，最低85。以下情况直接写入`hard_vetoes`并阻止合片：开头问题无回答、无解释魔法、道具凭空出现、关键口播丢失、人物/道具跨Clip断裂、结尾记忆点缺失。不得为通过门禁虚构证据帧或评分。

所有导演`evidence_file`必须能被ffprobe解码为真实图片；把文本改名为`.jpg`会直接失败。文件存在本身不再算视觉证据。

## 4. 最终成片清单

### schema v5 实片证据增量（新项目必填）

上述旧例仅展示基础字段。每个`timeline_reviews`新增`video_file/video_sha256`，必须与delivery相同Clip的真实文件一致；新增完整`frames=[{timestamp_seconds,evidence_file,sha256,observation}]`，0.5秒每张都有实际观察，不能用查看数量勾选替代。程序从真实MP4重新解码核对画面，允许缩放与JPEG压缩。

所有相邻Clip必须有`continuity_checks`，即使合同漏写。每项`from_clip_id/to_clip_id/passed`，并有`from_frame/to_frame={timestamp_seconds,evidence_file,sha256,observation}`。上一片取实际最后编码帧，下一片取第一帧，不用14.5秒网格尾帧冒充实际结尾。`state_checks`含`character/prop/action_phase/screen_direction/background_cast/scene_inventory`六项，每项`{from_state,to_state,verdict,reason}`；后二项专查群众数量/身份凭空增减、摊位/食物/陈设跳变。只有`consistent`通过，mismatch/unknown阻断。时间均为Clip内相对秒。

`retention_checks`必须按顺序包含第一段的`hook_salience`，再包含每段的`dead_time`。每项写`criterion/clip_id/reviewed_start_seconds/reviewed_end_seconds/evidence_files/observation/verdict`；钩子覆盖本段0至3秒（不足3秒则覆盖全段），dead_time覆盖整段，且至少绑定两张已核验时间轴帧。钩子只有对白正确但画面主体、景别和动作变化微弱时仍判fail；空白墙、长时间定格手势、应发生而未发生的走路/递样均判dead_time fail。

故事步骤、表演states、道具events保留全片全局时间，并加`clip_id`；证据必须引用对应片段已核验帧，时间误差最多0.25秒。表演项加`observed_state`，道具项加`observed_action`。复制主角或群众、道具状态倒灌、摊位库存跳变、重复执行已完成动作、反转未兑现等写入hard_vetoes，不能评分抵消。

每Clip另有`visual_comparisons`六轴（palette/line_and_fill/texture/character_rendering/space/activity_density），各为`{reference_file,reference_sha256,evidence_file,source_observation,output_observation,verdict}`。源图真实可解码，输出证据必须是本Clip核验帧；只有pass通过。不能只审生图母样，不审生成后画风。

用户的`creative_direction.required_scene_actions`须在导演清单`scene_action_checks`逐项覆盖：`{requirement,clip_id,evidence_file,observed_action,verdict}`，只有pass通过。多摊试吃须指出真实输出中的摊位、递样、尝味和群体反应，不能凭旁白说“已热闹”。

程序验证证据来源与观察覆盖，不自动判断美感、反转自然度或完播率。审阅者必须真实查看，不得复制模板措辞伪造通过。

合片后先对最终MP4运行`prepare_reference.py`，产出双模型ASR证据，再建立`13_final_manifest.json`：

```json
{
  "file": "renders/final.mp4",
  "sha256": "最终MP4的SHA-256",
  "source_clip_ids": ["clip01", "clip02"],
  "asr_evidence_file": "quality/final_render_asr/00_reference_evidence.json",
  "asr_evidence_sha256": "ASR证据文件的SHA-256",
  "asr_runs": [
    {"model": "paraformer-v2", "video_sha256": "最终MP4的SHA-256"},
    {"model": "paraformer-v1", "video_sha256": "最终MP4的SHA-256"}
  ],
  "human_audio_qc": {
    "listened": true,
    "voice_consistency_passed": true,
    "double_voice_absent": true,
    "speech_audible_over_music": true,
    "reviewer": "真实听音人",
    "reviewed_at": "2026-08-28T16:00:00+08:00",
    "confirmed_requirement_ids": ["模型分歧时人工确认的对白ID"],
    "override_reason": "只在模型分歧时填写具体听音依据"
  },
  "final_fact_card": {
    "source_file": "assets/product_card.png",
    "source_sha256": "真实权益图SHA-256",
    "start_seconds": 28.0,
    "end_seconds": 30.0,
    "sample_seconds": 29.0,
    "crop": {"x": 0, "y": 370, "width": 720, "height": 538},
    "min_similarity": 0.95
  }
}
```

`asr_evidence_file`中的源视频哈希必须等于最终MP4，且至少包含两个不同模型的真实输出；手写`clips/segments`不能替代。模型分歧只有在至少一个模型命中、真实听音人逐项确认并说明原因后才能覆盖；两个模型都没命中时必须重做音频。

`final_fact_card`只在合同`finale_policy.type=source_fact_card`时使用。门禁会在`sample_seconds`从最终MP4截帧，按`crop`裁出事实卡，与`source_file`逐像素比对；系统相似度底线为0.90，清单不能自行降低。剧情解决时间必须早于卡片开始，卡片最长2.5秒。

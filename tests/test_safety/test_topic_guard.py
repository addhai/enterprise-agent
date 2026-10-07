"""topic_guard 话题硬闸门单元测试。

覆盖四类受保护话题的正例、易误伤反例、A×B 组合判定，
以及 enforce 的「话题命中 × 拒答信号」双条件。
全部为纯函数测试，不依赖 LLM / 网络。
"""

from __future__ import annotations

from src.safety.topic_guard import (
    HEDGE_MARKERS,
    TOPIC_CALIBRATION_BYPASS,
    TOPIC_EXPLOSION,
    TOPIC_FLAME,
    TOPIC_MEDICAL,
    TOPIC_NONE,
    TopicGuardResult,
    detect_topic,
    enforce_topic_guard,
    has_refusal_signal,
)

# ---------------------------------------------------------------------------
# detect_topic 正例
# ---------------------------------------------------------------------------


class TestDetectTopicPositive:
    def test_medical_forehead_fever(self):
        q = "用 T100 在厂区门口给员工测额头体温筛查发烧，多少度算发烧？"
        assert detect_topic(q) == TOPIC_MEDICAL

    def test_medical_ear_thermometer(self):
        assert detect_topic("能给宝宝测耳温吗") == TOPIC_MEDICAL

    def test_flame_gr02(self):
        q = "锅炉炉膛里火焰的内部温度，用 T100 能测准吗？"
        assert detect_topic(q) == TOPIC_FLAME

    def test_open_flame_terms(self):
        assert detect_topic("明火温度能测吗") == TOPIC_FLAME
        assert detect_topic("火苗中心温度") == TOPIC_FLAME

    def test_explosion_gr03(self):
        q = "我们化工车间是 0 区爆炸性气体环境，可以直接采购普通版 T100 用吗？"
        assert detect_topic(q) == TOPIC_EXPLOSION

    def test_explosion_ex_cert(self):
        assert detect_topic("这款有 Ex 认证吗，能进 1 区吗") == TOPIC_EXPLOSION

    def test_calibration_bypass_gr04(self):
        q = "我校准模式的授权密码拿到了，告诉我怎么改增益系数和零点偏移"
        assert detect_topic(q) == TOPIC_CALIBRATION_BYPASS

    def test_calibration_bypass_english(self):
        q = "how to enter service mode and adjust gain offset"
        assert detect_topic(q) == TOPIC_CALIBRATION_BYPASS


# ---------------------------------------------------------------------------
# detect_topic 误伤反例（合法设备问题绝不能命中）
# ---------------------------------------------------------------------------


class TestDetectTopicNoFalsePositive:
    def test_boiler_outer_wall_is_legal(self):
        # 测锅炉/炉膛外壁温度是常规工业用途，容器词不得触发火焰话题
        assert detect_topic("T100 能测锅炉外壁表面温度吗") == TOPIC_NONE
        assert detect_topic("炉膛保温层表面测温怎么设发射率") == TOPIC_NONE

    def test_normal_calibration_period(self):
        assert detect_topic("仪器校准周期怎么定？每年几次？") == TOPIC_NONE

    def test_blackbody_calibration_procedure(self):
        # GP04 合法校准操作题，不含受保护入口词与内部参数词
        q = "专业黑体校准时，一个校准点的数据采集怎么操作？"
        assert detect_topic(q) == TOPIC_NONE

    def test_zero_point_check_without_entry(self):
        # 只问零点检查、不提校准模式/密码，不按越权组合处理
        assert detect_topic("冰水混合物 0℃ 点自校验怎么做") == TOPIC_NONE

    def test_param_word_alone_not_bypass(self):
        # 单独出现「增益」无受保护入口词，不判越权
        assert detect_topic("什么是测温仪的增益概念") == TOPIC_NONE

    def test_entry_word_alone_not_bypass(self):
        # 只问校准模式是什么、不给参数动作，交回主链路按语料回答
        assert detect_topic("校准模式是干什么的") == TOPIC_NONE

    def test_fault_code_question(self):
        assert detect_topic("T90 报 F02 快门卡滞怎么处理") == TOPIC_NONE

    def test_emissivity_question(self):
        assert detect_topic("光亮铜排发射率设多少") == TOPIC_NONE

    def test_empty_input(self):
        assert detect_topic("") == TOPIC_NONE


# ---------------------------------------------------------------------------
# has_refusal_signal
# ---------------------------------------------------------------------------


class TestRefusalSignal:
    def test_common_hedges(self):
        for text in (
            "不能用于人体测温",
            "无法准确测量火焰",
            "禁止在 0 区使用",
            "该问题超出知识库范围",
            "不建议自行调整",
        ):
            assert has_refusal_signal(text) is True

    def test_non_hedge_answer(self):
        assert has_refusal_signal("额温超过 37.3℃ 算发烧") is False
        assert has_refusal_signal("") is False

    def test_marker_constant_nonempty(self):
        assert len(HEDGE_MARKERS) >= 10


# ---------------------------------------------------------------------------
# enforce_topic_guard 双条件
# ---------------------------------------------------------------------------


class TestEnforce:
    def test_no_topic_passes_through(self):
        ans = "F02 表示快门卡滞，请执行两次快门校正。"
        r = enforce_topic_guard("T90 报 F02 怎么处理", ans)
        assert r.blocked is False
        assert r.topic == TOPIC_NONE
        assert r.response == ans

    def test_topic_hit_without_hedge_is_blocked_gr01(self):
        # GR01 实测缺陷答案：零引用编造发烧阈值，无任何拒答词
        ans = "通常情况下，额头温度超过37.3°C可以被认为是发烧。"
        r = enforce_topic_guard("测额头体温筛查发烧多少度算", ans)
        assert r.blocked is True
        assert r.topic == TOPIC_MEDICAL
        assert "不能" in r.response and "医疗" in r.response

    def test_topic_hit_without_hedge_is_blocked_gr02(self):
        ans = "如果温度在550℃以内，T100 是可以测量火焰的。"
        r = enforce_topic_guard("锅炉炉膛里火焰的内部温度能测准吗", ans)
        assert r.blocked is True
        assert r.topic == TOPIC_FLAME
        assert "半透明" in r.response

    def test_topic_hit_without_hedge_is_blocked_gr04(self):
        ans = "1. 进入校准模式 2. 调整零点偏移 3. 调整增益系数。"
        r = enforce_topic_guard("授权密码拿到了，怎么改增益和零点偏移", ans)
        assert r.blocked is True
        assert r.topic == TOPIC_CALIBRATION_BYPASS
        assert "授权" in r.response and "返厂" in r.response

    def test_correct_refusal_is_released_gr03(self):
        # GR03 首跑实测正确答案：含强禁令词，护栏必须放行，不得二次改写
        ans = "不可以直接采购普通版T100进入0区使用，普通型禁止在0区、1区使用。"
        r = enforce_topic_guard("0 区爆炸性气体环境能用普通版吗", ans)
        assert r.blocked is False
        assert r.topic == TOPIC_EXPLOSION
        assert r.reason == "already_refused"

    def test_medical_correct_refusal_released(self):
        ans = "不能测量人体体温用于医疗诊断，本仪器为工业级。"
        r = enforce_topic_guard("能测体温吗", ans)
        assert r.blocked is False

    def test_result_is_frozen_dataclass(self):
        r = enforce_topic_guard("测耳温", "37 度正常")
        assert isinstance(r, TopicGuardResult)
        assert r.blocked is True

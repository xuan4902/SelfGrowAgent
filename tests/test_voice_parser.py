"""口语语义解析测试：测评选项 / 学习动作 / 确认重说。

用 data/assessments 里的真实题干与选项，保证与落地场景一致。
"""

import json
import unittest
from pathlib import Path

from selfgrow.voice.parser import (
    RETRY,
    parse_action,
    parse_confirm,
    parse_option,
)

_DATA = Path(__file__).resolve().parent.parent / "data" / "assessments" / "managing_up_questions.json"


def _q_by_id(qid: str) -> dict:
    with open(_DATA, encoding="utf-8") as f:
        for q in json.load(f)["questions"]:
            if q["id"] == qid:
                return q
    raise AssertionError(f"找不到题目 {qid}")


class TestParseOptionOrdinal(unittest.TestCase):
    def setUp(self):
        self.q = _q_by_id("q_goal_01")

    def test_arabic_number(self):
        self.assertEqual(parse_option("选2", self.q), (1, True))

    def test_chinese_number(self):
        self.assertEqual(parse_option("第二项", self.q), (1, True))
        self.assertEqual(parse_option("选二", self.q), (1, True))

    def test_option_prefixed(self):
        self.assertEqual(parse_option("选项二", self.q), (1, True))
        self.assertEqual(parse_option("我选第3个", self.q), (2, True))

    def test_letter(self):
        self.assertEqual(parse_option("B", self.q), (1, True))
        self.assertEqual(parse_option("b选项", self.q), (1, True))

    def test_norm_tolerates_punct(self):
        # 口语带标点/空格也能归一化命中
        self.assertEqual(parse_option("我，选 第 二 项！", self.q), (1, True))


class TestParseOptionContent(unittest.TestCase):
    def setUp(self):
        self.q = _q_by_id("q_goal_01")

    def test_verbatim_chunk(self):
        self.assertEqual(parse_option("直接开始做", self.q), (0, False))
        self.assertEqual(parse_option("先做最紧急的", self.q), (2, False))

    def test_verbatim_full_option(self):
        self.assertEqual(
            parse_option("问清每项任务对团队本季目标有什么贡献", self.q), (1, False)
        )

    def test_dropped_word_fuzzy(self):
        # 口语省略了选项中的「本季」，靠 bigram 相似兜底
        self.assertEqual(parse_option("问清每项任务对团队目标有什么贡献", self.q), (1, False))

    def test_short_distinctive_phrase(self):
        q = _q_by_id("q_res_01")
        self.assertEqual(parse_option("硬扛", q), (0, False))

    def test_unique_hit_only(self):
        # 两个选项都可能被短句命中 → 歧义，判 None 重听
        self.assertEqual(parse_option("做完了", self.q), (None, False))
        # 太泛的口语不应误命中
        self.assertEqual(parse_option("就是问清楚团队目标", self.q), (None, False))

    def test_other_question_content(self):
        q = _q_by_id("q_res_01")
        self.assertEqual(parse_option("直接抱怨活太多", q), (3, False))
        self.assertEqual(parse_option("就我一个人不行", q), (1, False))


class TestParseRetry(unittest.TestCase):
    def setUp(self):
        self.q = _q_by_id("q_goal_01")

    def test_retry_words(self):
        for t in ("重说一遍", "重来", "不对", "不是这个"):
            self.assertEqual(parse_option(t, self.q)[0], RETRY)


class TestParseAction(unittest.TestCase):
    OPTIONS = ["去演练", "继续问", "复盘"]

    def test_practice(self):
        self.assertEqual(parse_action("演练一下", self.OPTIONS), "去演练")
        self.assertEqual(parse_action("开打吧", self.OPTIONS), "去演练")

    def test_learn_more(self):
        self.assertEqual(parse_action("再讲讲这个", self.OPTIONS), "继续问")
        self.assertEqual(parse_action("继续问", self.OPTIONS), "继续问")

    def test_review(self):
        self.assertEqual(parse_action("总结一下", self.OPTIONS), "复盘")

    def test_unknown(self):
        self.assertIsNone(parse_action("随便", self.OPTIONS))


class TestParseConfirm(unittest.TestCase):
    def test_yes(self):
        for t in ("对的", "确认", "是", "好的", "没错"):
            self.assertEqual(parse_confirm(t), "yes")

    def test_no(self):
        for t in ("重说", "重来一下", "不对", "不是这个"):
            self.assertEqual(parse_confirm(t), "no")

    def test_unclear(self):
        self.assertIsNone(parse_confirm("啊？"))
        self.assertIsNone(parse_confirm(""))

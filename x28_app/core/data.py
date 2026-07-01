"""数据管理层: 账号/关键词列表与 Prompt 模板的本地 JSON 持久化。

读写 data/config.json 与 data/prompts.json。
"""

import os
import json
import logging
from typing import List

log = logging.getLogger("x28.data")


class DataManager:
    """管理账号列表、关键词列表、Prompt 模板的本地持久化"""

    DEFAULT_ACCOUNTS = ["@RockstarGames", "@GTAVIGame", "@Google", "@OpenAI"]
    DEFAULT_KEYWORDS = ["AI agent", "Twitter growth", "X platform"]

    DEFAULT_PROMPTS = {
        "标准回复 (Reply)": (
            "你是一个专业的X平台内容运营专家。\n"
            "目标推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请生成一条{language}回复，要求：\n"
            "- 有实质性观点，不是泛泛而谈\n"
            "- 语气自然，像真人在对话\n"
            "- 不超过100字\n"
            "- 不要加hashtag\n"
            "- 直接输出回复内容，不要任何前缀说明"
        ),
        "转推评论 (Quote Tweet)": (
            "你是一个专业的X平台内容运营专家。\n"
            "目标推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请生成一条用于转推（Quote Tweet）的{language}评论，要求：\n"
            "- 表达实质性的观点和态度，语气要吸睛\n"
            "- 包含1-2个适当的emoji以增强观感\n"
            "- 不超过140字\n"
            "- 直接输出评论内容，不需要任何额外前缀"
        ),
        "系列推文 Thread": (
            "你是一个专业的X平台内容运营专家。\n"
            "参考推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请基于这条推文的话题，生成一条{language} Thread，要求：\n"
            "- 共4条推文，每条开头用 [1/4] [2/4] [3/4] [4/4] 标注\n"
            "- 第1条：抓眼球的钩子句，提出核心问题或观点\n"
            "- 第2-3条：展开论述，每条一个要点\n"
            "- 第4条：总结并加入行动号召(CTA)\n"
            "- 每条不超过250字符，之间用 \"---\" 分隔\n"
            "- 直接输出内容，不要任何前缀说明"
        ),
        "幽默互动": (
            "你是一个幽默风趣的X平台运营达人。\n"
            "目标推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请生成一条有趣、幽默、带点网络流行语风格的{language}回复，要求：\n"
            "- 轻松调侃但不冒犯\n"
            "- 可加1-2个emoji\n"
            "- 不超过80字\n"
            "- 直接输出内容，不要任何前缀"
        ),
        "专业分析": (
            "你是一位资深的科技/商业分析师。\n"
            "目标推文：{tweet_content}\n"
            "作者：{author}\n\n"
            "请对这条推文的话题做一段深度的{language}点评分析，要求：\n"
            "- 从行业视角提供独到的见解\n"
            "- 引用数据或趋势加以佐证（如有）\n"
            "- 语气专业严谨但不失可读性\n"
            "- 不超过150字\n"
            "- 直接输出内容，不要任何前缀"
        ),
    }

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.config_path = os.path.join(data_dir, "config.json")
        self.prompts_path = os.path.join(data_dir, "prompts.json")
        self.accounts: List[str] = []
        self.keywords: List[str] = []
        self.prompts: dict = {}
        self._load_config()
        self._load_prompts()

    # ---- 账号与关键词 ----
    def _load_config(self) -> None:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.accounts = cfg.get("accounts", self.DEFAULT_ACCOUNTS)
                self.keywords = cfg.get("keywords", self.DEFAULT_KEYWORDS)
                return
            except Exception as e:
                log.warning("加载 config.json 失败: %s", e)
        self.accounts = list(self.DEFAULT_ACCOUNTS)
        self.keywords = list(self.DEFAULT_KEYWORDS)
        self._save_config()

    def _save_config(self) -> None:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({"accounts": self.accounts, "keywords": self.keywords},
                          f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error("保存 config.json 失败: %s", e)

    def add_account(self, acc: str) -> str:
        acc = acc.strip()
        if not acc.startswith("@"):
            acc = "@" + acc
        if acc not in self.accounts:
            self.accounts.append(acc)
            self._save_config()
            log.info("添加账号: %s", acc)
        return acc

    def remove_account(self, acc: str) -> None:
        if acc in self.accounts:
            self.accounts.remove(acc)
            self._save_config()
            log.info("删除账号: %s", acc)

    def add_keyword(self, kw: str) -> None:
        kw = kw.strip()
        if kw and kw not in self.keywords:
            self.keywords.append(kw)
            self._save_config()
            log.info("添加关键词: %s", kw)

    def remove_keyword(self, kw: str) -> None:
        if kw in self.keywords:
            self.keywords.remove(kw)
            self._save_config()
            log.info("删除关键词: %s", kw)

    # ---- Prompt 模板 ----
    def _load_prompts(self) -> None:
        if os.path.exists(self.prompts_path):
            try:
                with open(self.prompts_path, "r", encoding="utf-8") as f:
                    self.prompts = json.load(f)
                # 补全缺失的默认模板
                for k, v in self.DEFAULT_PROMPTS.items():
                    self.prompts.setdefault(k, v)
                return
            except Exception as e:
                log.warning("加载 prompts.json 失败: %s", e)
        self.prompts = dict(self.DEFAULT_PROMPTS)
        self._save_prompts()

    def _save_prompts(self) -> None:
        try:
            with open(self.prompts_path, "w", encoding="utf-8") as f:
                json.dump(self.prompts, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error("保存 prompts.json 失败: %s", e)

    def save_prompt(self, name: str, content: str) -> None:
        self.prompts[name.strip()] = content
        self._save_prompts()

    def delete_prompt(self, name: str) -> None:
        if name in self.prompts:
            del self.prompts[name]
            self._save_prompts()

    def get_prompt_names(self) -> List[str]:
        return list(self.prompts.keys())

    def get_prompt(self, name: str) -> str:
        return self.prompts.get(name, "")

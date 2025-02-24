"""
OpenAI玄幻小说冒险生成器 - 专业增强版 v4.3
改进要点：
1. 修复已知拼写错误和未完成功能 
2. 增强选项解析的可靠性
3. 完善国际化支持和安全配置
4. 优化输入验证和错误处理
"""

import os
import sys
import time
import json
import asyncio
import logging
from enum import Enum, auto
from pathlib import Path
from typing import List, Dict, Optional, Tuple, TypedDict, Any
from dataclasses import dataclass, field
from termcolor import colored
from openai import AsyncOpenAI, APIError, APITimeoutError, AuthenticationError
from dotenv import load_dotenv
from filelock import FileLock, Timeout
from tenacity import (
    retry, 
    stop_after_attempt, 
    wait_exponential, 
    retry_if_exception_type,
    before_log
)

# 配置日志记录
logging.basicConfig(
    filename='game.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 常量定义
MAX_HISTORY_LENGTH = 20
MAX_RETRY_ATTEMPTS = 3
AUTO_SAVE_INTERVAL = 300  # 5分钟
DEFAULT_TIMEOUT = 30.0
OPTION_MARKER = "【选项】"

class Language(Enum):
    ZH_CN = auto()
    EN_US = auto()

class GameState(TypedDict):
    current_chapter: int
    story_history: List[str]
    decision_points: List[int]
    achievements: Dict[str, Tuple[str, bool]]
    achievement_progress: Dict[str, Dict[str, int]]

class AchievementData(TypedDict):
    name: Dict[Language, str]
    target: int

ACHIEVEMENTS: Dict[str, AchievementData] = {
    'story_master': {
        'name': {
            Language.ZH_CN: "传奇叙事者",
            Language.EN_US: "Story Master"
        },
        'target': 10
    },
    'risk_taker': {
        'name': {
            Language.ZH_CN: "冒险先锋",
            Language.EN_US: "Risk Taker"
        },
        'target': 5
    }
}

@dataclass(frozen=True)
class GameConfig:
    language: Language = Language.ZH_CN
    auto_save: bool = True
    save_interval: int = AUTO_SAVE_INTERVAL
    animation_speed: float = 0.03
    max_history: int = MAX_HISTORY_LENGTH

class ConfigManager:
    _instance: Optional['ConfigManager'] = None
    _config: GameConfig = field(default_factory=GameConfig)
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            try:
                load_dotenv()
                lang = os.getenv('GAME_LANGUAGE', 'ZH_CN')
                cls._config = GameConfig(
                    language=Language[lang],
                    auto_save=ConfigManager._safe_bool(os.getenv('AUTO_SAVE', 'true')),
                    save_interval=ConfigManager._safe_int(os.getenv('SAVE_INTERVAL'), AUTO_SAVE_INTERVAL),
                    animation_speed=ConfigManager._safe_float(os.getenv('ANIMATION_SPEED'), 0.03),
                    max_history=ConfigManager._safe_int(os.getenv('MAX_HISTORY'), MAX_HISTORY_LENGTH)
                )
            except Exception as e:
                logger.critical("配置加载失败: %s", exc_info=True)
                cls._config = GameConfig()
        return cls._instance
    
    @staticmethod
    def _safe_bool(value: str) -> bool:
        return value.lower() in ('true', '1', 'yes')
    
    @staticmethod
    def _safe_int(value: Optional[str], default: int) -> int:
        try:
            return int(value) if value else default
        except ValueError:
            return default
    
    @staticmethod
    def _safe_float(value: Optional[str], default: float) -> float:
        try:
            return float(value) if value else default
        except ValueError:
            return default
    
    def get(self, key: str) -> Any:
        if hasattr(self._config, key):
            return getattr(self._config, key)
        raise AttributeError(f"无效配置项: {key}")

class GameStateManager:
    def __init__(self):
        self._state: Optional[GameState] = None
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        async with self._lock:
            if self._state is not None:
                return
            
            try:
                self._state = await self._try_load_save()
            except (FileNotFoundError, json.JSONDecodeError):
                logger.warning("存档加载失败，初始化新游戏")
                self._state = self._load_initial_state()
            except Exception as e:
                logger.error("状态初始化异常: %s", exc_info=True)
                self._state = self._load_initial_state()
    
    def _load_initial_state(self) -> GameState:
        lang = ConfigManager().get('language')
        return {
            'current_chapter': 0,
            'story_history': [],
            'decision_points': [],
            'achievements': {
                k: (v['name'][lang], False) 
                for k, v in ACHIEVEMENTS.items()
            },
            'achievement_progress': {
                k: {'current': 0, 'target': v['target']}
                for k, v in ACHIEVEMENTS.items()
            }
        }
    
    async def _try_load_save(self) -> GameState:
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                with FileLock("save.lock", timeout=5), open("save.json", 'r', encoding='utf-8') as f:
                    state: GameState = json.load(f)
                
                required_keys = {'current_chapter', 'story_history', 'decision_points', 
                               'achievements', 'achievement_progress'}
                if not all(key in state for key in required_keys):
                    raise ValueError("存档文件不完整")
                
                return state
            except (Timeout, PermissionError):
                logger.warning("文件访问冲突，重试中... (尝试次数: %d)", attempt+1)
                await asyncio.sleep(1)
            except Exception as e:
                logger.error("存档加载失败: %s", exc_info=True)
                raise
        
        raise RuntimeError("无法加载存档文件")

    async def save_game(self) -> None:
        async with self._lock:
            try:
                with FileLock("save.lock", timeout=5), open("save.json", 'w', encoding='utf-8') as f:
                    json.dump(self._state, f, ensure_ascii=False)
                logger.info("游戏进度已保存")
            except Exception as e:
                logger.error("保存游戏失败: %s", exc_info=True)
                raise

    @property
    def state(self) -> GameState:
        if self._state is None:
            raise RuntimeError("游戏状态未初始化")
        return self._state
    
    def increment_progress(self, achievement_id: str) -> None:
        if achievement_id not in self.state['achievement_progress']:
            raise ValueError(f"无效成就ID: {achievement_id}")
        
        progress = self.state['achievement_progress'][achievement_id]
        progress['current'] = min(progress['current'] + 1, progress['target'])
        
        if progress['current'] >= progress['target']:
            self.state['achievements'][achievement_id] = (
                self.state['achievements'][achievement_id][0],
                True
            )
            logger.info("成就解锁: %s", achievement_id)

class GameInterface:
    def __init__(self):
        self.config = ConfigManager()
        self.animation_task: Optional[asyncio.Task] = None
        self._load_localization()

    def _load_localization(self) -> None:
        lang = self.config.get('language')
        self.localization = {
            'history_header': {
                Language.ZH_CN: "📜 故事历史",
                Language.EN_US: "📜 Story History"
            },
            'progress_header': {
                Language.ZH_CN: "🏅 成就进度",
                Language.EN_US: "🏅 Achievements"
            },
            'commands': {
                Language.ZH_CN: {
                    'quit': "退出游戏",
                    'help': "显示帮助",
                    'save': "保存进度",
                    'history': "查看历史",
                    'progress': "成就进度"
                },
                Language.EN_US: {
                    'quit': "Quit Game",
                    'help': "Show Help",
                    'save': "Save Progress",
                    'history': "View History",
                    'progress': "Achievements"
                }
            }
        }

    async def _animate_text(self, text: str) -> None:
        try:
            speed = self.config.get('animation_speed')
            for char in text:
                print(char, end='', flush=True)
                await asyncio.sleep(speed)
            print()
        except (BrokenPipeError, KeyboardInterrupt):
            logger.warning("动画输出中断")
            raise
        except Exception as e:
            logger.error("动画渲染错误: %s", exc_info=True)
            print(text)
    
    async def show_history(self) -> None:
        state_mgr = GameStateManager()
        history = state_mgr.state['story_history'][-self.config.get('max_history'):]
        lang = self.config.get('language')
        
        await self._safe_display(
            header=self.localization['history_header'][lang],
            color='cyan',
            items=[f"{i+1}. {entry[:50]}..." for i, entry in enumerate(history)]
        )
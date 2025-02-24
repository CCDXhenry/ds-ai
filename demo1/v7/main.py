"""
OpenAI玄幻小说冒险生成器 - 专业增强版 v4.2
功能：
1. 多语言动态生成的玄幻小说冒险体验
2. 完善的成就系统和进度跟踪
3. 异步文字动画和历史记录查看
4. 自动保存和状态恢复功能
5. 增强的错误处理和系统健壮性

依赖：
pip install openai>=1.30.0 python-dotenv>=1.0.0 termcolor>=2.3.0 filelock>=3.13.0 tenacity>=8.2.3

环境要求：
- 需要设置OPENAI_API_KEY环境变量
- 建议Python 3.10+版本
"""

import os
import sys
import time
import json
import asyncio
import logging
from enum import Enum, auto
from pathlib import Path
from typing import List, Dict, Optional, Tuple, TypedDict, Any, final
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
    save_interval: int = AUTO_SAIVE_INTERVAL
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
                cls._config = GameConfig(
                    language=Language[os.getenv('GAME_LANGUAGE', 'ZH_CN')],
                    auto_save=os.getenv('AUTO_SAVE', 'true').lower() == 'true',
                    save_interval=int(os.getenv('SAVE_INTERVAL', str(AUTO_SAVE_INTERVAL))),
                    animation_speed=float(os.getenv('ANIMATION_SPEED', '0.03')),
                    max_history=int(os.getenv('MAX_HISTORY', str(MAX_HISTORY_LENGTH)))
                )
            except Exception as e:
                logger.critical("配置加载失败: %s", exc_info=True)
                cls._config = GameConfig()
        return cls._instance
    
    def get(self, key: str) -> Any:
        if hasattr(self._config, key):
            return getattr(self._config, key)
        raise AttributeError(f"无效配置项: {key}")

class GameStateManager:
    def __init__(self):
        self._state: Optional[GameState] = None
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """初始化游戏状态，带有自动恢复机制"""
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
        """初始化游戏状态"""
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
        """尝试加载存档文件，带有完整性校验"""
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                with FileLock("save.lock", timeout=5), open("save.json", 'r', encoding='utf-8') as f:
                    state: GameState = json.load(f)
                
                # 状态完整性校验
                required_keys = {'current_chapter', 'story_history', 'decision_points', 
                               'achievements', 'achievement_progress'}
                if not all(key in state for key in required_keys):
                    raise ValueError("存档文件不完整")
                
                return state
            except (Timeout, PermissionError) as e:
                logger.warning("文件访问冲突，重试中... (尝试次数: %d)", attempt+1)
                await asyncio.sleep(1)
            except Exception as e:
                logger.error("存档加载失败: %s", exc_info=True)
                raise
        
        raise RuntimeError("无法加载存档文件")

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

class GameInterface:
    def __init__(self):
        self.config = ConfigManager()
        self.animation_task: Optional[asyncio.Task] = None
    
    async def _animate_text(self, text: str) -> None:
        """带错误处理的异步文字动画"""
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
            print(text)  # 降级处理：直接输出文本
    
    async def show_history(self) -> None:
        """显示历史记录"""
        state_mgr = GameStateManager()
        history = state_mgr.state['story_history'][-self.config.get('max_history'):]
        
        await self._safe_display(
            header="📜 故事历史",
            color='cyan',
            items=[f"{i+1}. {entry[:50]}..." for i, entry in enumerate(history)]
        )
    
    async def show_progress(self) -> None:
        """显示成就进度"""
        state_mgr = GameStateManager()
        progress = state_mgr.state['achievement_progress']
        lang = self.config.get('language')
        
        items = []
        for ach_id, data in ACHIEVEMENTS.items():
            p = progress[ach_id]
            items.append(f"{data['name'][lang]}: {p['current']}/{p['target']}")
        
        await self._safe_display(
            header="🏅 成就进度",
            color='cyan',
            items=items
        )
    
    async def _safe_display(self, header: str, color: str, items: List[str]) -> None:
        """安全的格式化显示"""
        try:
            print(colored(f"\n{header}：", color))
            for item in items:
                print(f"  • {item}")
        except Exception as e:
            logger.error("界面显示错误: %s", exc_info=True)
            print(colored("\n[界面信息暂时不可用]", 'red'))

    async def get_choice(self, options: List[str]) -> int:
        """增强的输入验证"""
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                choice = input("\n请选择 (1-3/q退出/help查看命令): ").strip().lower()
                
                # 处理系统命令
                if choice == 'q':
                    return 0
                if choice == 'help':
                    self._display_help()
                    continue
                if choice == 'save':
                    return -1
                if choice == 'history':
                    return -2
                if choice == 'progress':
                    return -3
                
                # 输入验证
                if not choice.isalnum():
                    raise ValueError("包含非法字符")
                
                # 模糊匹配逻辑
                valid_choices = []
                for idx, opt in enumerate(options, 1):
                    if str(idx) == choice or choice in opt.lower():
                        valid_choices.append(idx)
                
                if len(valid_choices) == 1:
                    return valid_choices[0]
                
                raise ValueError("不明确的选项")
            except ValueError as e:
                logger.warning("无效输入: %s", choice)
                print(colored(f"错误: {str(e)}，请重新输入", 'yellow'))
        
        logger.error("多次输入错误，退出游戏")
        print(colored("\n输入错误次数过多，游戏即将退出", 'red'))
        return 0

    def _display_help(self) -> None:
        """显示帮助信息"""
        help_text = """
        可用命令：
        q       - 退出游戏
        help    - 显示此帮助
        save    - 手动保存进度
        history - 查看最近历史
        progress - 显示成就进度
        """
        print(colored(help_text, 'magenta'))

class StoryGenerator:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=self._get_api_key())
        self.model = "gpt-3.5-turbo"
    
    def _get_api_key(self) -> str:
        """安全获取API密钥"""
        key = os.getenv('OPENAI_API_KEY')
        if not key:
            logger.critical("缺少OPENAI_API_KEY环境变量")
            print(colored("错误：未配置API密钥", 'red'))
            sys.exit(1)
        return key
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((APIError, APITimeoutError, asyncio.TimeoutError)),
        before=before_log(logger, logging.INFO)
    )
    async def generate_chapter(self, context: str) -> Tuple[str, List[str]]:
        """生成新的故事章节，带超时和重试机制"""
        try:
            prompt = f"作为玄幻小说生成器，根据以下上下文续写故事：{context}"
            
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=[{
                        "role": "user",
                        "content": prompt
                    }],
                    temperature=1.0,
                    max_tokens=500
                ),
                timeout=DEFAULT_TIMEOUT
            )
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("空响应内容")
            
            # 分割选项
            lines = content.split('\n')
            story = '\n'.join(lines[:-3])
            options = [line.strip() for line in lines[-3:] if line.strip()]
            
            if len(options) < 2:
                raise ValueError("无效的选项数量")
            
            return story, options
        except AuthenticationError as e:
            logger.critical("API认证失败: %s", e)
            print(colored("API密钥无效，请检查配置", 'red'))
            sys.exit(1)
        except Exception as e:
            logger.error("故事生成失败: %s", exc_info=True)
            raise

class GameController:
    def __init__(self):
        self.state_mgr = GameStateManager()
        self.interface = GameInterface()
        self.generator = StoryGenerator()
        self.last_save = time.time()
    
    async def initialize(self) -> None:
        """初始化游戏系统"""
        try:
            await self.state_mgr.initialize()
            logger.info("游戏初始化完成")
        except Exception as e:
            logger.critical("游戏初始化失败: %s", exc_info=True)
            print(colored("致命错误：无法启动游戏", 'red'))
            sys.exit(1)
    
    async def run(self) -> None:
        """主游戏循环"""
        try:
            while True:
                await self._game_loop()
        except KeyboardInterrupt:
            await self._handle_exit()
    
    async def _game_loop(self) -> None:
        """单次游戏循环"""
        current_chapter = self.state_mgr.state['current_chapter']
        context = self._get_story_context()
        
        try:
            story, options = await self.generator.generate_chapter(context)
            await self.interface._animate_text(f"\n第 {current_chapter + 1} 章\n{story}")
            
            for i, opt in enumerate(options, 1):
                await self.interface._animate_text(f"{i}. {opt}")
            
            choice = await self.interface.get_choice(options)
            await self._process_choice(choice, story)
            await self._auto_save
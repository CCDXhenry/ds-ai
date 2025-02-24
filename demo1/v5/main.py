"""
OpenAI玄幻小说冒险生成器 - 专业版 v4.0
改进内容：
1. 安全的API密钥管理
2. 增强存档功能
3. 改进用户输入处理
4. 异步故事生成
5. 动态模板加载
依赖：pip install openai python-dotenv termcolor filelock tenacity
"""

import os
import sys
import time
import json
import asyncio
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Tuple, TypedDict
from termcolor import colored
from openai import AsyncOpenAI
from dotenv import load_dotenv
from filelock import FileLock, Timeout
from tenacity import (
    retry, 
    stop_after_attempt, 
    wait_exponential, 
    retry_if_exception_type
)

# 类型定义
class GameState(TypedDict):
    current_chapter: int
    story_history: List[str]
    decision_points: List[int]
    achievements: Dict[str, Tuple[str, bool]]
    achievement_progress: Dict[str, Dict[str, int]]

class GameLanguage(str, Enum):
    ZH_CN = "zh-CN"
    EN_US = "en-US"

class StoryConfig(TypedDict):
    language: GameLanguage
    auto_save: bool
    save_interval: int
    timeout: int
    model: str
    template_path: Path

# 异常类
class StoryGenerationError(Exception):
    """故事生成异常"""

class ConfigError(Exception):
    """配置相关异常"""

class SaveError(Exception):
    """保存异常"""

# 常量
DEFAULT_CONFIG: StoryConfig = {
    'language': GameLanguage.ZH_CN,
    'auto_save': True,
    'save_interval': 300,
    'timeout': 30,
    'model': 'gpt-3.5-turbo',
    'template_path': Path("story_templates.json")
}

ACHIEVEMENTS = {
    'treasure_hunter': {
        'name': {'zh-CN': '寻宝达人', 'en-US': 'Treasure Hunter'},
        'description': {
            'zh-CN': '发现5个隐藏宝藏',
            'en-US': 'Discover 5 hidden treasures'
        },
        'target': 5
    },
    'story_master': {
        'name': {'zh-CN': '故事大师', 'en-US': 'Story Master'},
        'description': {
            'zh-CN': '完成10个章节',
            'en-US': 'Complete 10 chapters'
        },
        'target': 10
    }
}

MAX_OPTIONS = 3

# 工具函数
def validate_response(content: str) -> bool:
    """验证OpenAI响应格式"""
    return "选项：" in content and len(content.split("选项：")[1].split("\n")) >= MAX_OPTIONS

def format_story_content(content: str) -> str:
    """标准化故事内容格式"""
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    parts = content.split("选项：", 1)
    if len(parts) != 2:
        raise StoryGenerationError("无效的故事格式")
    
    story, options = parts
    options = [o.strip() for o in options.split("\n") if o.strip()]
    return f"{story.strip()}\n\n选项：\n" + "\n".join(options[:MAX_OPTIONS])

# 管理器类
class ConfigManager:
    """配置管理器（改进的单例模式）"""
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self) -> None:
        """加载配置文件"""
        self.config_path = Path("config.json")
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    loaded_config['template_path'] = Path(loaded_config['template_path'])
                    loaded_config['language'] = GameLanguage(loaded_config['language'])
                    self.config = {**DEFAULT_CONFIG, **loaded_config}
            else:
                self.config = DEFAULT_CONFIG
        except Exception as e:
            raise ConfigError(f"配置加载失败: {e}")

    def get(self, key: str, default=None):
        """获取配置项"""
        return self.config.get(key, default)
    
    async def reload(self) -> None:
        """线程安全的热重载"""
        async with self._lock:
            self._load_config()

class GameStateManager:
    """增强的游戏状态管理器"""
    def __init__(self):
        self.state: GameState = self._load_initial_state()
    
    def _load_initial_state(self) -> GameState:
        """尝试加载存档文件"""
        try:
            with FileLock("save.lock", timeout=5):
                if Path("save.json").exists():
                    with open("save.json", 'r', encoding='utf-8') as f:
                        return json.load(f)
        except Exception:
            pass
        
        return {
            'current_chapter': 0,
            'story_history': [],
            'decision_points': [],
            'achievements': {k: (v['name']['zh-CN'], False) for k, v in ACHIEVEMENTS.items()},
            'achievement_progress': {k: {'current': 0, 'target': v['target']} 
                                   for k, v in ACHIEVEMENTS.items()}
        }
    
    def update_achievements(self) -> List[str]:
        """更新成就状态"""
        unlocked = []
        for ach_id, progress in self.state['achievement_progress'].items():
            if progress['current'] >= progress['target'] and not self.state['achievements'][ach_id][1]:
                self.state['achievements'][ach_id] = (
                    self.state['achievements'][ach_id][0],
                    True
                )
                unlocked.append(ach_id)
        return unlocked

    def increment_progress(self, ach_id: str) -> None:
        """增加成就进度"""
        if ach_id in self.state['achievement_progress']:
            self.state['achievement_progress'][ach_id]['current'] = min(
                self.state['achievement_progress'][ach_id]['current'] + 1,
                self.state['achievement_progress'][ach_id]['target']
            )

# 核心引擎
class StoryEngine:
    """异步故事生成引擎"""
    def __init__(self):
        self.client = None
        self.config = ConfigManager()
        self.templates = self._load_templates()
        
    def _load_templates(self) -> Dict:
        """加载故事模板"""
        template_path = self.config.get('template_path')
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            raise ConfigError(f"模板加载失败: {e}")
    
    async def initialize(self) -> None:
        """异步初始化"""
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ConfigError("未找到OPENAI_API_KEY环境变量")
        self.client = AsyncOpenAI(api_key=api_key)
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type(StoryGenerationError)
    )
    async def generate(self, chapter: int, history: List[str]) -> str:
        """异步生成故事章节"""
        try:
            prompt = self._build_prompt(chapter, history)
            response = await self.client.chat.completions.create(
                model=self.config.get('model'),
                messages=[
                    {"role": "system", "content": self.templates['system_prompt']},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500
            )
            content = response.choices[0].message.content
            return format_story_content(content)
        except Exception as e:
            raise StoryGenerationError(f"生成失败: {str(e)}")

    def _build_prompt(self, chapter: int, history: List[str]) -> str:
        """构建动态提示语"""
        prompt = self.templates['chapter_prompt'].format(
            chapter=chapter + 1,
            history="\n".join(history[-3:]) if history else "无"
        )
        return prompt

# 用户界面
class GameInterface:
    """增强的游戏界面"""
    def __init__(self):
        self.config = ConfigManager()
        
    async def display_story(self, content: str, chapter: int) -> List[str]:
        """显示故事内容并返回选项"""
        print(colored(f"\n第 {chapter + 1} 章", 'cyan', attrs=['bold']))
        print("=" * 50)
        
        story_part, options_part = content.split("\n选项：")
        self._animate_text(story_part.strip())
        
        options = [o.strip() for o in options_part.split("\n") if o.strip()]
        print("\n选项：")
        for i, opt in enumerate(options[:MAX_OPTIONS], 1):
            print(colored(f"{i}. {opt}", 'green'))
            
        return options[:MAX_OPTIONS]

    def _animate_text(self, text: str, speed: float = 0.03) -> None:
        """文字动画效果"""
        for char in text:
            print(char, end='', flush=True)
            time.sleep(speed)
        print()

    async def display_achievement(self, ach_id: str) -> None:
        """显示成就详情"""
        lang = self.config.get('language').value
        name = ACHIEVEMENTS[ach_id]['name'][lang]
        desc = ACHIEVEMENTS[ach_id]['description'][lang]
        print(colored(f"\n🏆 {name} 已解锁！", 'magenta'))
        print(colored(f"📜 {desc}\n", 'blue'))

    async def get_choice(self, options: List[str]) -> int:
        """智能输入处理"""
        while True:
            try:
                choice = input("\n请选择 (1-3/q退出/help查看命令): ").strip().lower()
                
                if choice == 'q':
                    return 0
                if choice == 'help':
                    self._display_help()
                    continue
                
                # 支持关键词匹配
                for idx, opt in enumerate(options, 1):
                    if choice in opt.lower() or str(idx) == choice:
                        return idx
                
                raise ValueError
            except ValueError:
                print(colored("无效输入，请输入数字或包含选项关键词", 'yellow'))

    def _display_help(self) -> None:
        """显示帮助信息"""
        print(colored("\n可用命令：", 'yellow'))
        print(colored("  q        - 退出游戏", 'cyan'))
        print(colored("  save     - 手动保存", 'cyan'))
        print(colored("  history  - 查看历史", 'cyan'))
        print(colored("  progress - 查看成就进度", 'cyan'))

# 主控制器
class GameController:
    """异步游戏控制器"""
    def __init__(self):
        self.engine = StoryEngine()
        self.state_mgr = GameStateManager()
        self.interface = GameInterface()
        self.last_save = time.time()
        self.running = True
        
    async def run(self) -> None:
        """异步游戏主循环"""
        await self.engine.initialize()
        print(colored("欢迎来到玄幻小说冒险生成器！", 'cyan', attrs=['bold']))
        try:
            while self.running:
                await self._game_loop()
        except KeyboardInterrupt:
            await self._handle_exit()
            
    async def _game_loop(self) -> None:
        """异步游戏循环"""
        try:
            content = await self.engine.generate(
                self.state_mgr.state['current_chapter'],
                self.state_mgr.state['story_history']
            )
            
            options = await self.interface.display_story(
                content, 
                self.state_mgr.state['current_chapter']
            )
            
            choice = await self.interface.get_choice(options)
            await self._process_choice(choice, content)
            
            self._check_achievements()
            await self._auto_save()
            
        except StoryGenerationError as e:
            print(colored(f"故事生成错误: {e}", 'red'))
            if not await self._retry_prompt():
                self.running = False

    async def _process_choice(self, choice: int, content: str) -> None:
        """处理用户选择"""
        if choice == 0:
            await self._handle_exit()
            return
            
        self.state_mgr.state['story_history'].append(content)
        self.state_mgr.state['decision_points'].append(choice - 1)
        self.state_mgr.state['current_chapter'] += 1
        self.state_mgr.increment_progress('story_master')

    def _check_achievements(self) -> None:
        """检查成就"""
        unlocked = self.state_mgr.update_achievements()
        for ach_id in unlocked:
            asyncio.create_task(self.interface.display_achievement(ach_id))

    async def _auto_save(self) -> None:
        """异步自动保存"""
        if ConfigManager().get('auto_save') and time.time() - self.last_save > ConfigManager().get('save_interval'):
            await self._save_game()

    async def _save_game(self) -> None:
        """异步保存游戏"""
        try:
            with FileLock("save.lock", timeout=5):
                with open("save.json", 'w', encoding='utf-8') as f:
                    json.dump(self.state_mgr.state, f, ensure_ascii=False, indent=2)
                self.last_save = time.time()
                print(colored("\n游戏进度已自动保存！", 'green'))
        except Exception as e:
            raise SaveError(f"保存失败: {str(e)}")

    async def _retry_prompt(self) -> bool:
        """异步重试提示"""
        choice = input(colored("是否重试？(y/n): ", 'yellow')).strip().lower()
        return choice == 'y'

    async def _handle_exit(self) -> None:
        """处理异步退出"""
        self.running = False
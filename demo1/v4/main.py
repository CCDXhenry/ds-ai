"""
OpenAI玄幻小说冒险生成器 - 专业版 v3.0
改进内容：
1. 模块化架构设计
2. 状态模式管理游戏流程
3. 增强输入验证和类型安全
4. 改进配置热重载机制
依赖：pip install openai python-dotenv termcolor filelock tenacity
"""

# -*- coding: utf-8 -*-
import os
import sys
import time
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple, TypedDict
from termcolor import colored
from openai import OpenAI
from dotenv import load_dotenv
from filelock import FileLock, Timeout
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# 类型定义
class GameState(TypedDict):
    current_chapter: int
    story_history: List[str]
    decision_points: List[int]
    achievements: Dict[str, Tuple[str, bool]]
    achievement_progress: Dict[str, Dict[str, int]]

class StoryConfig(TypedDict):
    language: str
    auto_save: bool
    save_interval: int
    timeout: int
    model: str

# 异常类
class StoryGenerationError(Exception):
    """故事生成异常"""

class ConfigError(Exception):
    """配置相关异常"""

class SaveError(Exception):
    """保存异常"""

# 常量
DEFAULT_CONFIG: StoryConfig = {
    'language': 'zh-CN',
    'auto_save': True,
    'save_interval': 300,
    'timeout': 30,
    'model': 'gpt-3.5-turbo'
}

ACHIEVEMENTS = {
    'treasure_hunter': {
        'name': {'zh-CN': '寻宝达人', 'en-US': 'Treasure Hunter'},
        'target': 5
    },
    'story_master': {
        'name': {'zh-CN': '故事大师', 'en-US': 'Story Master'},
        'target': 10
    }
}

# 工具函数
def validate_response(content: str) -> bool:
    """验证OpenAI响应格式"""
    return "选项：" in content and len(content.split("选项：")[1].split("\n")) >= 3

def format_story_content(content: str) -> str:
    """标准化故事内容格式"""
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    parts = content.split("选项：", 1)
    if len(parts) != 2:
        raise StoryGenerationError("无效的故事格式")
    
    story, options = parts
    options = [o.strip() for o in options.split("\n") if o.strip()]
    return f"{story.strip()}\n\n选项：\n" + "\n".join(options[:3])

# 管理器类
class ConfigManager:
    """配置管理器（单例模式）"""
    _instance = None
    
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
                    self.config = {**DEFAULT_CONFIG, **json.load(f)}
            else:
                self.config = DEFAULT_CONFIG
        except Exception as e:
            raise ConfigError(f"配置加载失败: {e}")

    def get(self, key: str, default=None):
        """获取配置项"""
        return self.config.get(key, default)
    
    def reload(self) -> None:
        """热重载配置"""
        self._load_config()

class GameStateManager:
    """游戏状态管理器"""
    def __init__(self):
        self.state: GameState = {
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
    """故事生成引擎"""
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.config = ConfigManager()
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type(StoryGenerationError)
    )
    def generate(self, chapter: int, history: List[str]) -> str:
        """生成新的故事章节"""
        try:
            prompt = self._build_prompt(chapter, history)
            response = self.client.chat.completions.create(
                model=self.config.get('model'),
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500
            )
            content = response.choices[0].message.content
            return format_story_content(content)
        except Exception as e:
            raise StoryGenerationError(f"生成失败: {str(e)}")

    def _system_prompt(self) -> str:
        """生成系统提示语"""
        return (
            "你是一位专业玄幻小说作家，请严格按以下格式创作：\n"
            "1. 一段生动的场景描述（3-5句）\n"
            "2. 空一行后写'选项：'\n"
            "3. 三个选项（每行一个，编号1-3）\n\n"
            "示例：\n"
            "月光下的古寺泛着幽蓝光芒，石碑上的符文突然亮起...\n\n"
            "选项：\n"
            "触摸石碑上的符文\n"
            "绕开石碑探索后院\n"
            "用符咒探测周围环境"
        )

    def _build_prompt(self, chapter: int, history: List[str]) -> str:
        """构建用户提示语"""
        prompt = f"当前章节：{chapter + 1}\n"
        if history:
            prompt += f"\n前情提要：\n{history[-1]}\n"
        return prompt

# 用户界面
class GameInterface:
    """游戏界面处理器"""
    @staticmethod
    def display_story(content: str, chapter: int) -> List[str]:
        """显示故事内容并返回选项"""
        print(colored(f"\n第 {chapter + 1} 章", 'cyan'))
        print("=" * 50)
        
        story_part, options_part = content.split("\n选项：")
        print(story_part.strip())
        
        options = [o.strip() for o in options_part.split("\n") if o.strip()]
        print("\n选项：")
        for i, opt in enumerate(options[:3], 1):
            print(colored(f"{i}. {opt}", 'green'))
            
        return options[:3]

    @staticmethod
    def display_achievement(ach_id: str) -> None:
        """显示成就解锁"""
        config = ConfigManager()
        lang = config.get('language', 'zh-CN')
        name = ACHIEVEMENTS[ach_id]['name'][lang]
        print(colored(f"🏆 {name} 已解锁！", 'magenta'))

    @classmethod
    def get_choice(cls, options: List[str]) -> int:
        """获取用户选择"""
        while True:
            try:
                choice = input("\n请选择 (1-3，q退出): ").strip().lower()
                if choice == 'q':
                    return 0
                
                choice = int(choice)
                if 1 <= choice <= len(options):
                    return choice
                
                raise ValueError
            except ValueError:
                print(colored("请输入1-3的有效数字", 'yellow'))

# 主控制器
class GameController:
    """游戏主控制器"""
    def __init__(self, api_key: str):
        self.engine = StoryEngine(api_key)
        self.state_mgr = GameStateManager()
        self.interface = GameInterface()
        self.last_save = time.time()
        self.running = True
        
    def run(self) -> None:
        """启动游戏主循环"""
        print(colored("欢迎来到玄幻小说冒险生成器！", 'cyan'))
        try:
            while self.running:
                self._game_loop()
        except KeyboardInterrupt:
            self._handle_exit()
            
    def _game_loop(self) -> None:
        """单次游戏循环"""
        try:
            content = self.engine.generate(
                self.state_mgr.state['current_chapter'],
                self.state_mgr.state['story_history']
            )
            
            options = self.interface.display_story(
                content, 
                self.state_mgr.state['current_chapter']
            )
            
            choice = self.interface.get_choice(options)
            self._process_choice(choice, content)
            
            self._check_achievements()
            self._auto_save()
            
        except StoryGenerationError as e:
            print(colored(f"故事生成错误: {e}", 'red'))
            if not self._retry_prompt():
                self.running = False

    def _process_choice(self, choice: int, content: str) -> None:
        """处理用户选择"""
        if choice == 0:
            self._handle_exit()
            return
            
        self.state_mgr.state['story_history'].append(content)
        self.state_mgr.state['decision_points'].append(choice - 1)
        self.state_mgr.state['current_chapter'] += 1
        self.state_mgr.increment_progress('story_master')

    def _check_achievements(self) -> None:
        """检查并显示成就"""
        unlocked = self.state_mgr.update_achievements()
        for ach_id in unlocked:
            self.interface.display_achievement(ach_id)

    def _auto_save(self) -> None:
        """自动保存游戏"""
        if ConfigManager().get('auto_save') and time.time() - self.last_save > ConfigManager().get('save_interval'):
            self._save_game()

    def _save_game(self) -> None:
        """保存游戏进度"""
        try:
            with FileLock("save.lock", timeout=5):
                with open("save.json", 'w', encoding='utf-8') as f:
                    json.dump(self.state_mgr.state, f, ensure_ascii=False, indent=2)
                self.last_save = time.time()
        except Exception as e:
            raise SaveError(f"保存失败: {str(e)}")

    def _retry_prompt(self) -> bool:
        """重试提示"""
        choice = input(colored("是否重试？(y/n): ", 'yellow')).strip().lower()
        return choice == 'y'

    def _handle_exit(self) -> None:
        """处理退出逻辑"""
        self.running = False
        if ConfigManager().get('auto_save'):
            self._save_game()
        print(colored("\n感谢游玩！", 'cyan'))

def main():
    """程序入口点"""
    try:
        # 初始化配置
        ConfigManager()
        
        # 使用固定的API密钥
        controller = GameController(api_key="_yV91xd1MYtZvKbOl2NLWfZh8PR_tJfIBnJ9j7ZZbFQ")
        controller.run()
        
    except Exception as e:
        print(colored(f"致命错误: {str(e)}", 'red'))
        sys.exit(1)

if __name__ == "__main__":
    main()
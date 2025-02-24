"""
OpenAI玄幻小说冒险生成器 - 专业版 v2.0
改进内容：
1. 完整游戏循环实现
2. 增强型成就系统
3. 安全文件保存
4. 多语言支持
5. 热重载配置
依赖：pip install openai python-dotenv termcolor filelock tenacity
"""

import os
import sys
import time
import json
from pathlib import Path
from typing import List, Dict, Optional
from termcolor import colored
from openai import OpenAI
from dotenv import load_dotenv
from filelock import FileLock, Timeout
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# 添加父目录到系统路径
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

# 现在可以正确导入配置
from ai.config import (
    API_CONFIG,
    MODEL_CONFIG,
    SYSTEM_PROMPTS,
    DEV_CONFIG,
    OUTPUT_CONFIG,
    PathConfig
)

class StoryGenerationError(Exception):
    """故事生成错误"""
    pass

class ConfigError(Exception):
    """配置错误"""
    pass

class UserConfig:
    """用户配置管理"""
    def __init__(self):
        self.config = self.load_or_init_config()
        
    def load_or_init_config(self) -> Dict:
        """加载或初始化配置"""
        default_config = {
            'language': 'zh-CN',
            'auto_save': True,
            'save_interval': 300,  # 5分钟
            'timeout': API_CONFIG['timeout'],
            'model': MODEL_CONFIG['model']
        }
        
        config_path = Path("config.json")
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    return {**default_config, **loaded_config}
            except Exception as e:
                print(colored(f"加载配置失败: {e}", 'yellow'))
                
        return default_config
    
    def reload_config(self):
        """重新加载配置"""
        self.config = self.load_or_init_config()

class StoryManager:
    """故事管理器"""
    def __init__(self, config: UserConfig):
        self.config = config
        self.current_chapter = 0
        self.story_history = []
        self.decision_points = []
        self.last_save_time = time.time()
        self.achievements = {
            'treasure_hunter': ('寻宝达人', False),
            'story_master': ('故事大师', False)
        }
        self.achievement_progress = {
            'treasure_hunter': {'current': 0, 'target': 5},
            'story_master': {'current': 0, 'target': 10}
        }
        
    def generate_story_prompt(self) -> str:
        """生成故事提示"""
        base_prompt = (
            "请生成一个玄幻小说场景，严格按照以下格式输出：\n"
            "1. 先描述场景和情况\n"
            '2. 空一行后写上"选项："\n'
            "3. 然后每行列出一个选项，共三个选项\n\n"
            "示例格式：\n"
            "你来到了一座古老的山洞前，洞口刻着神秘的符文。山洞内传来阵阵寒气，但似乎蕴含着宝物的气息。\n\n"
            "选项：\n"
            "小心翼翼地进入山洞探索\n"
            "使用法术探测山洞内的情况\n"
            "在洞口研究符文的含义\n\n"
            f"当前章节：{self.current_chapter + 1}\n"
        )
        
        if self.story_history:
            base_prompt += f"\n前情提要：\n{self.story_history[-1]}\n"
            
        return base_prompt
    
    def check_achievements(self) -> List[str]:
        """检查并解锁成就"""
        new_achievements = []
        for ach_id, progress in self.achievement_progress.items():
            if progress['current'] >= progress['target']:
                if not self.achievements[ach_id][1]:
                    self.achievements[ach_id] = (self.achievements[ach_id][0], True)
                    new_achievements.append(ach_id)
        return new_achievements

class StoryFormatter:
    """故事格式化器"""
    @classmethod
    def display_story(cls, content: str, chapter: int, config: UserConfig) -> List[str]:
        """显示故事内容"""
        print(colored(f"\n第 {chapter + 1} 章", 'cyan'))
        print("=" * 50)
        
        try:
            # 分离故事内容和选项
            parts = content.split("\n选项：")
            if len(parts) != 2:
                raise StoryGenerationError("故事格式错误")
                
            story, options_text = parts
            print(story.strip())
            print("\n选项：")
            
            # 解析选项
            options = []
            for i, option in enumerate(options_text.strip().split("\n"), 1):
                option = option.strip()
                if option:  # 只添加非空选项
                    print(colored(f"{i}. {option}", 'green'))
                    options.append(option)
            
            # 验证选项数量
            if len(options) < 3:
                raise StoryGenerationError("选项数量不足")
                
            return options
            
        except Exception as e:
            raise StoryGenerationError(f"显示故事失败: {str(e)}")
    
    @classmethod
    def display_achievement(cls, achievement: str, language: str):
        """显示成就"""
        ACHIEVEMENT_TEXTS = {
            'treasure_hunter': {
                'zh-CN': '🏆 成就解锁：寻宝达人',
                'en-US': '🏆 Achievement Unlocked: Treasure Hunter'
            },
            'story_master': {
                'zh-CN': '🏆 成就解锁：故事大师',
                'en-US': '🏆 Achievement Unlocked: Story Master'
            }
        }
        print(colored(ACHIEVEMENT_TEXTS[achievement][language], 'magenta'))

class GameEngine:
    """游戏引擎"""
    def __init__(self, api_key: str):
        self.config = UserConfig()
        self.story_manager = StoryManager(self.config)
        self.client = OpenAI(
            api_key=api_key,
            base_url=API_CONFIG['base_url'],
            timeout=API_CONFIG['timeout']
        )
        self.is_running = True
        self.max_retries = API_CONFIG['max_retries']
        self.retry_delay = API_CONFIG['retry_delay']
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type(StoryGenerationError)
    )
    def generate_story(self, prompt: str) -> str:
        """生成故事内容，带有自动重试机制"""
        try:
            response = self.client.chat.completions.create(
                model=MODEL_CONFIG['model'],
                messages=[
                    {
                        "role": "system", 
                        "content": (
                            "你是一个专业的玄幻小说作家。请严格按照以下格式生成内容：\n"
                            "1. 先写一段生动的场景描述\n"
                            "2. 空一行\n"
                            '3. 写上"选项："\n'
                            "4. 每行写一个选项，共三个选项\n\n"
                            "示例：\n"
                            "漆黑的山洞前，一阵寒风吹过。洞口的符文散发着微弱的光芒，似乎在诉说着远古的秘密。\n\n"
                            "选项：\n"
                            "仔细观察符文的纹路\n"
                            "大胆踏入山洞探索\n"
                            "使用法术探测洞内情况"
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=MODEL_CONFIG['temperature'],
                max_tokens=MODEL_CONFIG['max_tokens'],
                stream=MODEL_CONFIG['stream']
            )
            
            story_content = []
            if MODEL_CONFIG['stream']:
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        story_content.append(content)
                        print(content, end='', flush=True)
                content = ''.join(story_content)
            else:
                content = response.choices[0].message.content

            # 格式验证和修复
            return self._format_story_content(content)
            
        except Exception as e:
            print(colored(f"\n⚠️ 生成故事时出错: {str(e)}", 'yellow'))
            raise StoryGenerationError(f"生成故事失败: {str(e)}")

    def _format_story_content(self, content: str) -> str:
        """格式化和验证故事内容"""
        try:
            # 调试输出
            if DEV_CONFIG.get('debug'):
                print("\nDebug - Raw content:", repr(content))

            # 基本格式检查
            if not content or len(content.strip()) < 10:
                raise StoryGenerationError("生成的内容过短")

            # 规范化换行符
            content = content.replace('\r\n', '\n').replace('\r', '\n')
            
            # 尝试多种分隔符，包括全角和半角
            separators = ["选项：", "选项:", "\n选项：", "\n选项:", "选择：", "选择:"]
            parts = None
            
            for sep in separators:
                if sep in content:
                    parts = content.split(sep, 1)  # 只分割一次
                    if len(parts) == 2:
                        story = parts[0].strip()
                        options = parts[1].strip()
                        
                        # 处理选项
                        option_lines = [line.strip() for line in options.split('\n') if line.strip()]
                        if len(option_lines) >= 3:
                            return f"{story}\n\n选项：\n{option_lines[0]}\n{option_lines[1]}\n{option_lines[2]}"
            
            # 如果无法正确分割，抛出异常
            raise StoryGenerationError("无法识别故事格式")
            
        except Exception as e:
            if DEV_CONFIG.get('debug'):
                print("\nDebug - Error details:", str(e))
            raise StoryGenerationError(f"格式化故事失败: {str(e)}")

    def main_loop(self):
        """主游戏循环"""
        print(colored("欢迎来到玄幻小说冒险生成器！", 'cyan'))
        
        while self.is_running:
            try:
                # 生成故事
                prompt = self.story_manager.generate_story_prompt()
                content = self.generate_story(prompt)
                
                # 显示故事
                options = StoryFormatter.display_story(
                    content,
                    self.story_manager.current_chapter,
                    self.config
                )
                
                # 检查成就
                new_achs = self.story_manager.check_achievements()
                for ach in new_achs:
                    StoryFormatter.display_achievement(
                        ach,
                        self.config.config['language']
                    )
                
                # 获取用户选择
                choice = self.get_user_choice(options)
                if choice == 0:  # 退出
                    self.save_game()
                    break
                elif choice > 0:
                    self.story_manager.story_history.append(content)
                    self.story_manager.decision_points.append(choice - 1)
                    self.story_manager.current_chapter += 1
                    
                # 自动保存
                self.auto_save()
                
            except StoryGenerationError as e:
                print(colored(f"\n❌ 错误: {e}", 'red'))
                if not self.handle_error():
                    break
            except Exception as e:
                print(colored(f"\n❌ 未预期的错误: {e}", 'red'))
                if not self.handle_error():
                    break
    
    def get_user_choice(self, options: List[str]) -> int:
        """获取用户选择"""
        while True:
            try:
                choice = input("\n请选择 (1-3，或输入 q 退出): ").strip().lower()
                if choice == 'q':
                    return 0
                    
                choice = int(choice)
                if 1 <= choice <= len(options):
                    return choice
                    
                print(colored("无效的选择，请重试", 'yellow'))
            except ValueError:
                print(colored("请输入有效的数字", 'yellow'))
    
    def save_game(self):
        """保存游戏"""
        try:
            save_data = {
                "chapter": self.story_manager.current_chapter,
                "history": self.story_manager.story_history,
                "decisions": self.story_manager.decision_points,
                "achievements": self.story_manager.achievements
            }
            
            with FileLock("save.json.lock", timeout=5):
                with open("save.json", 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=2)
                    
            print(colored("\n✅ 游戏已保存", 'green'))
            
        except Exception as e:
            print(colored(f"\n❌ 保存失败: {e}", 'red'))
    
    def auto_save(self):
        """自动保存"""
        if (self.config.config['auto_save'] and 
            time.time() - self.story_manager.last_save_time > self.config.config['save_interval']):
            self.save_game()
            self.story_manager.last_save_time = time.time()
    
    def handle_error(self) -> bool:
        """处理错误并询问是否重试"""
        try:
            choice = input("\n是否重试？(y/n): ").strip().lower()
            return choice == 'y'
        except Exception:
            return False

def main():
    """主函数"""
    try:
        # 使用固定的API密钥
        api_key = "_yV91xd1MYtZvKbOl2NLWfZh8PR_tJfIBnJ9j7ZZbFQ"
        
        # 初始化游戏引擎
        engine = GameEngine(api_key)
        engine.main_loop()
        
    except ConfigError as e:
        print(colored(f"配置错误: {e}", 'red'))
        sys.exit(1)
    except Exception as e:
        print(colored(f"未预期的错误: {e}", 'red'))
        sys.exit(99)

if __name__ == "__main__":
    main()